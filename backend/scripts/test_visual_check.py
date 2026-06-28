#!/usr/bin/env python3
"""E2E smoke test: render JSX → screenshot → POST /visual-check → Vision Critic."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

DEFAULT_FIXTURE = BACKEND_DIR / "scripts" / "battery_results" / "dashboard.txt"
DEFAULT_API = "http://localhost:8000/visual-check"


def extract_code_from_battery_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "SUCCESS — final code:"
    if marker not in text:
        raise ValueError(f"No final code block in {path}")
    block = text.split(marker, 1)[1]
    if "------------------------------------------------------------" not in block:
        raise ValueError(f"Malformed code block in {path}")
    inner = block.split("------------------------------------------------------------", 2)[1]
    return inner.strip()


def main() -> None:
    parser = argparse.ArgumentParser(description="Test Playwright render + /visual-check")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE, help="Battery file with final code")
    parser.add_argument("--api", default=DEFAULT_API, help="Visual check endpoint URL")
    parser.add_argument("--render-only", action="store_true", help="Only test local render, skip API")
    args = parser.parse_args()

    if not args.fixture.exists():
        print(f"Fixture not found: {args.fixture}", file=sys.stderr)
        sys.exit(1)

    code = extract_code_from_battery_file(args.fixture)
    print(f"Loaded code from {args.fixture.name} ({len(code)} chars)")

    sys.path.insert(0, str(BACKEND_DIR))
    from render_screenshot import render_jsx_to_screenshot

    png = render_jsx_to_screenshot(code)
    print(f"Render OK: {len(png)} bytes PNG")
    if len(png) < 5000:
        print("WARNING: PNG smaller than 5KB — may be blank", file=sys.stderr)

    screenshots = list((BACKEND_DIR / "tmp" / "render" / "screenshots").glob("*.png"))
    if screenshots:
        latest = max(screenshots, key=lambda p: p.stat().st_mtime)
        print(f"Debug screenshot: {latest}")

    if args.render_only:
        return

    payload = {
        "code": code,
        "design_contract": (
            "Sidebar on left with Home, Settings, Reports. "
            "Header with Dashboard title. Two stat cards for Revenue ($12,400) and Users (1,284)."
        ),
        "description": "admin dashboard with sidebar navigation, header, and two stat cards",
    }

    print(f"\nPOST {args.api} …")
    with httpx.Client(timeout=120.0) as client:
        resp = client.post(args.api, json=payload)
        resp.raise_for_status()
        result = resp.json()

    print("\nVision Critic result:")
    print(f"  passed: {result.get('passed')}")
    print(f"  status: {result.get('status')}")
    print(f"  summary: {result.get('summary')}")
    issues = result.get("issues", [])
    print(f"  issues ({len(issues)}):")
    for i, issue in enumerate(issues, 1):
        sev = issue.get("severity", "?")
        cat = issue.get("category", "?")
        desc = issue.get("description", "")
        print(f"    {i}. [{sev}/{cat}] {desc}")

    if "screenshot" in result.get("summary", "").lower() and "no " in result.get("summary", "").lower():
        print("\nFAILED: critic did not receive a real screenshot", file=sys.stderr)
        sys.exit(1)

    print("\nE2E visual-check OK")


if __name__ == "__main__":
    main()
