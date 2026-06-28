#!/usr/bin/env python3
"""Extract final code from a harness run, copy sketch, and render preview PNG."""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
FINALISTS_DIR = BACKEND_DIR / "scripts" / "battery_results" / "finalists"

SKETCH_SOURCES = {
    "login": BACKEND_DIR / "test_sketch.jpg",
    "dashboard": BACKEND_DIR / "test_sketch_dashboard.jpg",
    "dashboard_handdrawn": BACKEND_DIR / "scripts" / "real_dashboard_sketch.jpg",
    "dashboard_real": BACKEND_DIR / "scripts" / "real_dashboard_sketch.jpg",
    "list": BACKEND_DIR / "test_sketch_list.jpg",
}


def extract_code_from_run(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    marker = "SUCCESS — final code:"
    if marker not in text:
        raise ValueError(f"No final code block in {path}")
    block = text.split(marker, 1)[1]
    if "------------------------------------------------------------" not in block:
        raise ValueError(f"Malformed code block in {path}")
    inner = block.split("------------------------------------------------------------", 2)[1]
    return inner.strip()


def capture(name: str) -> None:
    out_dir = FINALISTS_DIR / name
    run_path = out_dir / "run.txt"
    if not run_path.exists():
        raise FileNotFoundError(f"Missing {run_path}")

    code = extract_code_from_run(run_path)
    jsx_path = out_dir / "final.jsx"
    jsx_path.write_text(code + "\n", encoding="utf-8")
    print(f"Wrote {jsx_path} ({len(code)} chars)")

    sketch_src = SKETCH_SOURCES[name]
    sketch_dst = out_dir / "sketch.jpg"
    shutil.copy2(sketch_src, sketch_dst)
    print(f"Copied {sketch_src.name} -> {sketch_dst}")

    sys.path.insert(0, str(BACKEND_DIR))
    from render_screenshot import render_jsx_to_screenshot

    png_bytes = render_jsx_to_screenshot(code)
    preview_path = out_dir / "preview.png"
    preview_path.write_bytes(png_bytes)
    print(f"Wrote {preview_path} ({len(png_bytes)} bytes)")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build finalist bundle from run.txt")
    parser.add_argument(
        "names",
        nargs="*",
        choices=["login", "dashboard", "dashboard_handdrawn", "dashboard_real", "list"],
        help="Finalist names to capture (default: all)",
    )
    args = parser.parse_args()
    names = args.names if args.names else ["login", "dashboard", "list"]
    for name in names:
        print(f"\n--- {name} ---")
        capture(name)


if __name__ == "__main__":
    main()
