"""Cerebras API client: message builders, retry policy and circuit breaker.

Responsibilities:
  * `CerebrasClient` wraps the Cerebras SDK for sync, async and streaming chat completions.
  * Retry policy: one immediate retry on timeouts and stream stalls; up to 3 attempts on 429s with a
    jittered wait so concurrent runs don't retry in lockstep.
  * `CircuitBreaker` plus one process-wide instance (`_breaker`) that every client shares.
  * Helpers that build chat message lists for text and image prompts.

Interacts with:
  * orchestrator.py: every text agent calls `acall` / `acall_stream`; it also raises the
    `PipelineAgentError` this module imports lazily when the breaker is open.
  * vision_client.py: the Cerebras vision path calls `acall`.
  * main.py: reads `_breaker.state` for /health and /metrics.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import random
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from typing import Any, TypeVar

from cerebras.cloud.sdk import AsyncCerebras, Cerebras
from cerebras.cloud.sdk._exceptions import APITimeoutError, RateLimitError

DEFAULT_MODEL = "gpt-oss-120b"

JSON_CALL_TIMEOUT = 20.0
STREAM_CALL_TIMEOUT = 25.0
INTER_TOKEN_TIMEOUT = 8.0
VISION_CALL_TIMEOUT = 25.0
RATE_LIMIT_RETRY_DELAY = 10.0

log = logging.getLogger(__name__)

T = TypeVar("T")


class StreamStallError(Exception):
    """Raised when no new stream chunk arrives within INTER_TOKEN_TIMEOUT."""


def _resolve_model(model: str | None) -> str:
    return model or os.environ.get("CEREBRAS_MODEL", DEFAULT_MODEL)


def build_image_messages(
    text: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> list[dict[str, Any]]:
    """OpenAI-compatible multimodal user message (text + image_url data URI)."""
    encoded = base64.b64encode(image_bytes).decode("ascii")
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": text},
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{encoded}"},
                },
            ],
        }
    ]


def build_multimodal_messages(
    system: str,
    user_text: str,
    image_bytes: bytes,
    mime_type: str = "image/jpeg",
) -> list[dict[str, Any]]:
    """Build chat messages for a text + image prompt, with an optional system message.

    Args:
        system: System prompt; omitted from the messages when empty.
        user_text: Text part of the user turn.
        image_bytes: Raw image bytes, sent as a base64 data URL.
        mime_type: MIME type of the image.
    """
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(build_image_messages(user_text, image_bytes, mime_type))
    return messages


def build_text_messages(system: str, user: str) -> list[dict[str, Any]]:
    """Build chat messages for a text-only prompt; the system message is omitted when `system` is empty."""
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return messages


def _jittered(base: float) -> float:
    return base + random.uniform(0, base * 0.3)


class CircuitBreakerOpen(Exception):
    """Raised instead of calling the API while the breaker is OPEN."""


class CircuitBreaker:
    """Thread-safe circuit breaker that stops calling an API that keeps failing.

    States: CLOSED (calls pass; `failure_threshold` consecutive failures trip it), OPEN (calls are
    rejected without running; after `recovery_timeout` seconds the next call becomes a probe) and
    HALF_OPEN (one probe call runs; success closes the breaker, failure reopens it).

    Args:
        failure_threshold: Consecutive failures that open the breaker.
        recovery_timeout: Seconds to stay OPEN before allowing a probe.
        clock: Monotonic time source; injectable so tests need not sleep.
    """
    CLOSED, OPEN, HALF_OPEN = "closed", "open", "half_open"

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._clock = clock
        self._lock = threading.Lock()
        self.state = self.CLOSED
        self._failures = 0
        self._opened_at = 0.0
        self._probing = False

    def before_call(self) -> None:
        """Raise CircuitBreakerOpen, or admit the call (possibly as the HALF_OPEN probe)."""
        with self._lock:
            if self.state == self.OPEN:
                if self._clock() - self._opened_at < self.recovery_timeout:
                    raise CircuitBreakerOpen("circuit open")
                self.state = self.HALF_OPEN
            if self.state == self.HALF_OPEN:
                # Only one probe may run in HALF_OPEN. Otherwise every caller queued behind the open breaker would hit the
                # recovering API at once the moment the timeout expires, which is the stampede the breaker exists to stop.
                if self._probing:
                    raise CircuitBreakerOpen("circuit half-open, probe in flight")
                self._probing = True

    def record(self, ok: bool | None) -> None:
        """ok=None means the call ended without a verdict (cancelled); it only frees the probe slot."""
        with self._lock:
            self._probing = False
            if ok is None:
                return
            if ok:
                self.state, self._failures = self.CLOSED, 0
            elif self.state == self.HALF_OPEN or self._failures + 1 >= self.failure_threshold:
                self.state, self._failures, self._opened_at = self.OPEN, 0, self._clock()
            else:
                self._failures += 1

    def call(self, fn: Callable[[], T]) -> T:
        """Run a sync `fn` through the breaker.

        Returns:
            Whatever `fn` returns.

        Raises:
            CircuitBreakerOpen: The breaker is OPEN (or a HALF_OPEN probe is already running); `fn` is not called.
            Exception: Anything `fn` raises is re-raised after being counted as a failure.
        """
        self.before_call()
        verdict: bool | None = None
        try:
            result = fn()
            verdict = True
            return result
        except Exception:
            verdict = False
            raise
        finally:
            self.record(verdict)

    async def acall(self, fn: Callable[[], Awaitable[T]]) -> T:
        """Run an async `fn` through the breaker; same semantics as `call`.

        Args:
            fn: Zero-argument callable returning an awaitable. It is called (and awaited) only if admitted.

        Raises:
            CircuitBreakerOpen: The breaker rejected the call; `fn` was not invoked.
        """
        self.before_call()
        verdict: bool | None = None
        try:
            result = await fn()
            verdict = True
            return result
        except Exception:
            verdict = False
            raise
        finally:
            self.record(verdict)


# One instance for the whole process. Clients are created per call (the architect and vision paths each
# build their own), so per-client state would never accumulate failures, and concurrent runs must see
# the same view of API health.
_breaker = CircuitBreaker()


def _breaker_rejection(call_name: str, exc: CircuitBreakerOpen) -> BaseException:
    # Imported here, not at module top: orchestrator imports this module at load time, so a top-level
    # import would be circular.
    from orchestrator import PipelineAgentError

    return PipelineAgentError(
        "cerebras",
        f"Cerebras API circuit breaker is open ({call_name}); too many recent failures, try again shortly.",
        cause=exc,
    )


def _is_retryable(exc: BaseException) -> bool:
    return isinstance(exc, (APITimeoutError, asyncio.TimeoutError, StreamStallError))


def _is_rate_limit(exc: BaseException) -> bool:
    return isinstance(exc, RateLimitError)


async def _retry_once_on_rate_limit(
    call_name: str,
    fn: Callable[[], Awaitable[T]],
) -> T:
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            return await fn()
        except BaseException as exc:
            if attempt < max_attempts - 1 and _is_rate_limit(exc):
                log.warning(
                    "cerebras rate-limit retry attempt=%d call=%s waiting=%ss",
                    attempt + 1,
                    call_name,
                    RATE_LIMIT_RETRY_DELAY,
                )
                await asyncio.sleep(_jittered(RATE_LIMIT_RETRY_DELAY))
                continue
            raise
    raise RuntimeError("unreachable")


async def _retry_once(
    call_name: str,
    fn: Callable[[], Awaitable[T]],
) -> T:
    for attempt in range(2):
        try:
            return await fn()
        except BaseException as exc:
            if attempt == 0 and _is_retryable(exc):
                log.warning(
                    "cerebras retry attempt=1 call=%s reason=%s",
                    call_name,
                    type(exc).__name__,
                )
                continue
            raise
    raise RuntimeError("unreachable")


class CerebrasClient:
    """Client for one Cerebras model, with sync, async and streaming chat-completion calls.

    The async methods (`acall`, `acall_stream`) are the ones the pipeline uses: they add one retry
    on timeouts and stalls, up to 3 attempts with jittered waits on rate limits, and the shared
    circuit breaker. The SDK's own retries are disabled so they don't stack on that policy.

    Args:
        api_key: Defaults to the CEREBRAS_API_KEY environment variable.
        model: Defaults to CEREBRAS_MODEL, then `gpt-oss-120b`.

    Raises:
        RuntimeError: (on construction) no API key is available.
    """
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or os.environ.get("CEREBRAS_API_KEY")
        if not key:
            raise RuntimeError("CEREBRAS_API_KEY is not set")
        self.model = _resolve_model(model)
        # SDK retries off so they don't stack on the 429/timeout policy below.
        self._sync = Cerebras(api_key=key).with_options(
            timeout=JSON_CALL_TIMEOUT,
            max_retries=0,
        )
        self._sync_stream = Cerebras(api_key=key).with_options(
            timeout=STREAM_CALL_TIMEOUT,
            max_retries=0,
        )
        self._async = AsyncCerebras(api_key=key)
        self._json_client = self._async.with_options(timeout=JSON_CALL_TIMEOUT, max_retries=0)
        self._stream_client = self._async.with_options(timeout=STREAM_CALL_TIMEOUT, max_retries=0)

    def call(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """Blocking chat completion with no retry or breaker; returns the message text ("" if empty)."""
        response = self._sync.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    def call_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> Iterator[str]:
        """Blocking streaming completion with no retry or breaker; yields content deltas as they arrive."""
        stream = self._sync_stream.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in stream:
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    async def _acall_once(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> str:
        response = await self._json_client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""

    async def acall(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 4096,
        temperature: float = 0.2,
    ) -> str:
        """Async chat completion with retries, jitter and the circuit breaker.

        Timeouts get one immediate retry; 429s get up to 3 attempts with a ~10s jittered wait.

        Args:
            messages: Chat messages (see `build_text_messages`).
            max_tokens: Completion token cap.
            temperature: Sampling temperature.

        Returns:
            The message text, or "" if the model returned none.

        Raises:
            PipelineAgentError: The circuit breaker is open.
            Exception: The last API error once retries are exhausted.
        """
        async def _do() -> str:
            return await self._acall_once(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        try:
            return await _breaker.acall(
                lambda: _retry_once_on_rate_limit("acall", lambda: _retry_once("acall", _do))
            )
        except CircuitBreakerOpen as exc:
            raise _breaker_rejection("acall", exc) from exc

    async def _iter_stream_tokens(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        stream = await self._stream_client.chat.completions.create(
            model=self.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        iterator = stream.__aiter__()
        while True:
            try:
                # STREAM_CALL_TIMEOUT only covers create(); this catches a stream that starts then hangs.
                chunk = await asyncio.wait_for(iterator.__anext__(), timeout=INTER_TOKEN_TIMEOUT)
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError as exc:
                raise StreamStallError(
                    f"No stream chunk received within {INTER_TOKEN_TIMEOUT}s"
                ) from exc
            delta = chunk.choices[0].delta
            if delta.content:
                yield delta.content

    async def acall_stream(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> AsyncIterator[str]:
        """Async streaming completion with retries, jitter and the circuit breaker.

        Retries apply to the whole stream, so a retry after a mid-stream failure restarts it and can
        yield tokens that were already yielded. A stream with no chunk for 8s raises StreamStallError
        internally and is retried once.

        Yields:
            Content deltas (strings) as they arrive.

        Raises:
            PipelineAgentError: The circuit breaker is open.
            Exception: The last API error once retries are exhausted.
        """
        try:
            _breaker.before_call()
        except CircuitBreakerOpen as exc:
            raise _breaker_rejection("acall_stream", exc) from exc
        verdict: bool | None = None  # stays None if the consumer stops early or we're cancelled
        try:
            async for token in self._acall_stream_with_retries(
                messages, max_tokens=max_tokens, temperature=temperature
            ):
                yield token
            verdict = True
        except Exception:
            verdict = False
            raise
        finally:
            _breaker.record(verdict)

    async def _acall_stream_with_retries(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int,
        temperature: float,
    ) -> AsyncIterator[str]:
        max_rate_attempts = 3
        for rate_attempt in range(max_rate_attempts):
            try:
                for attempt in range(2):
                    try:
                        async for token in self._iter_stream_tokens(
                            messages,
                            max_tokens=max_tokens,
                            temperature=temperature,
                        ):
                            yield token
                        return
                    except BaseException as exc:
                        if attempt == 0 and _is_retryable(exc):
                            log.warning(
                                "cerebras retry attempt=1 call=acall_stream reason=%s",
                                type(exc).__name__,
                            )
                            continue
                        raise
            except BaseException as exc:
                if rate_attempt < max_rate_attempts - 1 and _is_rate_limit(exc):
                    log.warning(
                        "cerebras rate-limit retry attempt=%d call=acall_stream waiting=%ss",
                        rate_attempt + 1,
                        RATE_LIMIT_RETRY_DELAY,
                    )
                    await asyncio.sleep(_jittered(RATE_LIMIT_RETRY_DELAY))
                    continue
                raise

    async def acall_stream_with_tps(
        self,
        messages: list[dict[str, Any]],
        *,
        max_tokens: int = 8192,
        temperature: float = 0.2,
    ) -> AsyncIterator[tuple[str, float | None]]:
        """Yield (token, tps_snapshot). TPS updates on every token."""
        start = time.perf_counter()
        token_count = 0
        async for token in self.acall_stream(
            messages, max_tokens=max_tokens, temperature=temperature
        ):
            token_count += 1
            elapsed = time.perf_counter() - start
            tps = token_count / elapsed if elapsed > 0 else None
            yield token, tps
