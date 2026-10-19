"""Pluggable vision provider for the Vision Parser and Vision Critic agents.

Responsibilities: pick a provider from VISION_PROVIDER ("anthropic" by default, or "cerebras") and
expose one blocking entry point, `call_vision_json`, that sends a prompt plus an image and returns
raw model text.

Interacts with:
  * orchestrator.py and main.py: call `call_vision_json` from worker threads.
  * cerebras_client.py: the Cerebras path reuses `CerebrasClient.acall`, so it gets the same
    retry, timeout and circuit-breaker behaviour as the text agents. The Anthropic path does not.
"""

from __future__ import annotations

import asyncio
import base64
import os

import anthropic

from cerebras_client import CerebrasClient, build_multimodal_messages


def get_vision_provider() -> str:
    # Anthropic today; Cerebras path is for when Gemma vision is ready.
    """Return the configured vision provider, "anthropic" (default) or "cerebras", from VISION_PROVIDER."""
    return os.environ.get("VISION_PROVIDER", "anthropic").lower()


def get_vision_model() -> str:
    """Return the model id for the active vision provider.

    Raises:
        ValueError: VISION_PROVIDER is not "anthropic" or "cerebras".
    """
    provider = get_vision_provider()
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-6")
    if provider == "cerebras":
        return os.environ.get("CEREBRAS_VISION_MODEL", "gemma-4-31b")
    raise ValueError(f"Unknown VISION_PROVIDER: {provider!r} (expected 'anthropic' or 'cerebras')")


# TODO: the Anthropic path (the default provider) has no retry, backoff or circuit breaker; the only
# bound is the caller's 25s wait_for. Route it through the same wrapper as the Cerebras path.
def _call_anthropic(
    system_prompt: str,
    user_text: str,
    image_bytes: bytes,
    image_mime_type: str,
) -> str:
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set")

    client = anthropic.Anthropic(api_key=api_key)
    encoded = base64.b64encode(image_bytes).decode("ascii")
    response = client.messages.create(
        model=os.environ.get("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-6"),
        max_tokens=2048,
        system=system_prompt,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": image_mime_type,
                            "data": encoded,
                        },
                    },
                    {"type": "text", "text": user_text},
                ],
            }
        ],
    )
    return response.content[0].text


def _call_cerebras(
    system_prompt: str,
    user_text: str,
    image_bytes: bytes,
    image_mime_type: str,
) -> str:
    client = CerebrasClient(model=get_vision_model())
    messages = build_multimodal_messages(system_prompt, user_text, image_bytes, image_mime_type)
    # call_vision_json is sync and runs in a worker thread (asyncio.to_thread), which has no event loop.
    # asyncio.run gives acall a private loop, so this path reuses the text agents' retry, timeout and
    # circuit-breaker logic instead of a bare blocking call.
    return asyncio.run(client.acall(messages, max_tokens=2048, temperature=0.1))


def call_vision_json(
    system_prompt: str,
    user_text: str,
    image_bytes: bytes,
    image_mime_type: str,
) -> str:
    """Send a system prompt, user text and one image to the vision provider; return the raw model text.

    Synchronous and blocking: callers run it in a worker thread (`asyncio.to_thread`). Parsing the
    JSON out of the reply is the caller's job (`parsing.extract_json`).

    Args:
        system_prompt: System prompt for the agent.
        user_text: User-turn text.
        image_bytes: Raw image bytes.
        image_mime_type: MIME type of the image (e.g. "image/png").

    Returns:
        The model's reply text.

    Raises:
        ValueError: VISION_PROVIDER is not recognised.
        RuntimeError: The Anthropic provider is selected but ANTHROPIC_API_KEY is unset.
    """
    provider = get_vision_provider()
    if provider == "anthropic":
        return _call_anthropic(system_prompt, user_text, image_bytes, image_mime_type)
    if provider == "cerebras":
        return _call_cerebras(system_prompt, user_text, image_bytes, image_mime_type)
    raise ValueError(f"Unknown VISION_PROVIDER: {provider!r} (expected 'anthropic' or 'cerebras')")
