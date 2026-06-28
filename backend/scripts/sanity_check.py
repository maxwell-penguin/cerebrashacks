#!/usr/bin/env python3
"""
Hour-0 sanity check: one real multimodal vision call via VISION_PROVIDER.

Usage:
  cd backend
  cp .env.example .env   # add API keys
  pip install -r requirements.txt
  python scripts/sanity_check.py path/to/sketch.jpg
"""

from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from vision_client import call_vision_json, get_vision_model, get_vision_provider  # noqa: E402

SYSTEM = "You are a helpful vision assistant."
USER = "Describe this image in 2-3 sentences. What UI elements do you see?"


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python scripts/sanity_check.py <image_path>")
        sys.exit(1)

    image_path = Path(sys.argv[1])
    if not image_path.exists():
        print(f"Image not found: {image_path}")
        sys.exit(1)

    suffix = image_path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")

    image_bytes = image_path.read_bytes()
    provider = get_vision_provider()
    model = get_vision_model()

    print(f"Provider: {provider}")
    print(f"Model: {model}")
    print(f"Image: {image_path} ({len(image_bytes)} bytes, {mime})")
    print("Sending multimodal test call…\n")

    if provider == "anthropic":
        block_format = (
            'content: [{type: "image", source: {type: "base64", media_type, data}}, '
            '{type: "text", text}]'
        )
    else:
        block_format = (
            'content: [{type: "text", text}, '
            '{type: "image_url", image_url: {url: "data:<mime>;base64,..."}}]'
        )
    print(f"Image block format: {block_format}\n")

    try:
        response = call_vision_json(SYSTEM, USER, image_bytes, mime)
    except Exception as exc:
        print(f"FAILED: {exc}")
        if provider == "anthropic":
            print("\nCheck ANTHROPIC_API_KEY and ANTHROPIC_VISION_MODEL in .env")
        else:
            print("\nCheck CEREBRAS_API_KEY and CEREBRAS_MODEL in .env")
        sys.exit(1)

    print("SUCCESS — model response:")
    print("-" * 40)
    print(response)
    print("-" * 40)
    print("\nVision API looks good. Proceed with the pipeline.")


if __name__ == "__main__":
    main()
