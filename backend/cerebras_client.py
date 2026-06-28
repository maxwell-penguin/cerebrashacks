"""Thin wrapper around the Cerebras SDK (OpenAI-compatible chat completions)."""

from __future__ import annotations

import asyncio
import base64
import logging
import os
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
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.extend(build_image_messages(user_text, image_bytes, mime_type))
    return messages


def build_text_messages(system: str, user: str) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": user})
    return messages


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
                await asyncio.sleep(RATE_LIMIT_RETRY_DELAY)
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
    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        key = api_key or os.environ.get("CEREBRAS_API_KEY")
        if not key:
            raise RuntimeError("CEREBRAS_API_KEY is not set")
        self.model = _resolve_model(model)
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
        async def _do() -> str:
            return await self._acall_once(
                messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )

        return await _retry_once_on_rate_limit("acall", lambda: _retry_once("acall", _do))

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
                    await asyncio.sleep(RATE_LIMIT_RETRY_DELAY)
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
