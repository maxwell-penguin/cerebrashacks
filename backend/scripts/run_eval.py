#!/usr/bin/env python3
"""Run the real SketchStorm pipeline over a directory of sketches and score each one.

Uses real API clients (keys from backend/.env), so it costs money and takes a while.

  python backend/scripts/run_eval.py --limit 3
  python backend/scripts/run_eval.py --dir path/to/sketches --out results.csv

Per sketch it runs run_sketchstorm_pipeline with the app's default audit/a11y flags, then (if code was
produced) renders the JSX with Playwright and runs the Critic on the screenshot. The pipeline itself
only runs the Critic when given a screenshot up front, which can't exist before the code does.
latency_total_ms is the pipeline wall time and excludes that post-hoc render + Critic call.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import math
import statistics
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from dotenv import load_dotenv

load_dotenv(BACKEND_DIR / ".env")

DESCRIPTION = "Build a UI component based on this sketch"
EXTENSIONS = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".svg": "image/png"}
FIELDS = [
    "sketch_id", "render_success", "visual_pass", "latency_vision_ms", "latency_architect_ms",
    "latency_codeforge_ms", "latency_total_ms", "error",
]
# agent whose start/done status events give the per-agent latency columns
TIMED = {"vision_parser": "latency_vision_ms", "architect": "latency_architect_ms", "code_forge": "latency_codeforge_ms"}


def load_image(path: Path) -> tuple[bytes, str]:
    data = path.read_bytes()
    if path.suffix.lower() == ".svg":
        import cairosvg  # lazy: needs the system cairo library, only matters if there are SVGs

        data = cairosvg.svg2png(bytestring=data)  # in memory; the vision API doesn't take SVG
    return data, EXTENSIONS[path.suffix.lower()]


def _ms(start: float, end: float) -> float:
    return round((end - start) * 1000, 1)


async def run_one(client: Any, path: Path) -> dict[str, Any]:
    from orchestrator import run_sketchstorm_pipeline, run_visual_check
    from render_screenshot import render_jsx_to_screenshot

    row: dict[str, Any] = {k: "" for k in FIELDS}
    row.update(sketch_id=path.stem, render_success=False, visual_pass=None)
    starts: dict[str, float] = {}
    failed_agent: list[str] = []

    async def emit(msg: dict[str, Any]) -> None:
        now = time.perf_counter()
        if msg.get("type") == "agent_status":
            agent, status = msg["agent"], msg["status"]
            if status in ("thinking", "streaming"):
                starts.setdefault(agent, now)
            elif status == "done" and agent in TIMED and agent in starts:
                row[TIMED[agent]] = _ms(starts[agent], now)
            elif status == "error" and not failed_agent:
                failed_agent.append(agent)
        elif msg.get("type") == "error" and msg.get("agent") and not failed_agent:
            failed_agent.append(msg["agent"])

    t0 = time.perf_counter()
    try:
        image_bytes, mime = load_image(path)
        result = await run_sketchstorm_pipeline(client, image_bytes, DESCRIPTION, mime, emit)
    except Exception as exc:  # e.g. unreadable image or a bug; the pipeline handles agent errors itself
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["latency_total_ms"] = _ms(t0, time.perf_counter())
        return row
    row["latency_total_ms"] = _ms(t0, time.perf_counter())

    code = (result.get("code") or "").strip()
    row["render_success"] = bool(code)
    if not code:
        row["error"] = failed_agent[0] if failed_agent else "unknown"
        return row

    try:
        shot = await asyncio.to_thread(render_jsx_to_screenshot, code)
        check = await run_visual_check(client, shot, "", DESCRIPTION, "image/png")
        row["visual_pass"] = not any(i.severity in ("critical", "major") for i in check.issues)
    except Exception as exc:
        print(f"  critic did not run for {path.name}: {exc}", file=sys.stderr)  # visual_pass stays None
    return row


def p95(values: list[float]) -> float:
    s = sorted(values)
    return s[max(0, math.ceil(0.95 * len(s)) - 1)]  # nearest-rank


def summarize(rows: list[dict[str, Any]]) -> str:
    n = len(rows)
    ok = sum(1 for r in rows if r["render_success"])
    critic = [r for r in rows if r["visual_pass"] is not None]
    passed = sum(1 for r in critic if r["visual_pass"])
    totals = [r["latency_total_ms"] for r in rows if r["latency_total_ms"] != ""]
    failures = Counter(r["error"] for r in rows if r["error"])
    pct = lambda a, b: f"{100 * a / b:.0f}%" if b else "n/a"  # noqa: E731
    return "\n".join([
        f"render success: {ok}/{n} ({pct(ok, n)})",
        f"visual pass: {passed}/{len(critic)} ({pct(passed, len(critic))})  [critic ran on {len(critic)} of {n}]",
        f"median latency: {statistics.median(totals):.0f}ms" if totals else "median latency: n/a",
        f"p95 latency: {p95(totals):.0f}ms" if totals else "p95 latency: n/a",
        f"most common failure point: {failures.most_common(1)[0][0] if failures else 'none'}",
    ])


async def main_async(args: argparse.Namespace) -> int:
    from cerebras_client import CerebrasClient

    sketch_dir = Path(args.dir)
    if not sketch_dir.is_dir():
        print(f"No such directory: {sketch_dir}", file=sys.stderr)
        return 1
    paths = sorted(p for p in sketch_dir.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONS)
    if args.limit:
        paths = paths[: args.limit]
    if not paths:
        print(f"No jpg/png/svg files in {sketch_dir}", file=sys.stderr)
        return 1

    client = CerebrasClient()
    rows = []
    for i, path in enumerate(paths, 1):  # sequential: parallel runs would just trip the rate limits
        print(f"[{i}/{len(paths)}] {path.name}", flush=True)
        rows.append(await run_one(client, path))

    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\nWrote {args.out}\n")
    print(summarize(rows))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dir", default=str(Path(__file__).parent / "eval_sketches"))
    parser.add_argument("--out", default="eval_results.csv")
    parser.add_argument("--limit", type=int, default=0, help="only run the first N sketches")
    return asyncio.run(main_async(parser.parse_args()))


if __name__ == "__main__":
    sys.exit(main())
