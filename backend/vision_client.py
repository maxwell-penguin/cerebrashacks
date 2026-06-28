"""Pluggable vision provider for Vision Parser and Vision Critic."""

from __future__ import annotations

import base64
import os

import anthropic

from cerebras_client import CerebrasClient, build_multimodal_messages


def get_vision_provider() -> str:
    return os.environ.get("VISION_PROVIDER", "anthropic").lower()


def get_vision_model() -> str:
    provider = get_vision_provider()
    if provider == "anthropic":
        return os.environ.get("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-6")
    if provider == "cerebras":
        return os.environ.get("CEREBRAS_VISION_MODEL", "gemma-4-31b")
    raise ValueError(f"Unknown VISION_PROVIDER: {provider!r} (expected 'anthropic' or 'cerebras')")


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
    return client.call(messages, max_tokens=2048, temperature=0.1)


def call_vision_json(
    system_prompt: str,
    user_text: str,
    image_bytes: bytes,
    image_mime_type: str,
) -> str:
    """Return raw model text; caller uses parsing.extract_json."""
    provider = get_vision_provider()
    if provider == "anthropic":
        return _call_anthropic(system_prompt, user_text, image_bytes, image_mime_type)
    if provider == "cerebras":
        return _call_cerebras(system_prompt, user_text, image_bytes, image_mime_type)
    raise ValueError(f"Unknown VISION_PROVIDER: {provider!r} (expected 'anthropic' or 'cerebras')")
