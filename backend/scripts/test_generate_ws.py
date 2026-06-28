#!/usr/bin/env python3
"""
End-to-end WebSocket pipeline test: Vision Parser -> Architect -> Code Forge.

Usage:
  cd backend
  source .venv/bin/activate
  ./dev.sh   # in another terminal
  python scripts/test_generate_ws.py
  python scripts/test_generate_ws.py --quiet   # summary only (good for A/B runs)
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

try:
    import websockets
except ImportError:
    print("Install websockets: pip install websockets", file=sys.stderr)
    sys.exit(1)

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))
load_dotenv(BACKEND_DIR / ".env")

from pipeline_config import RUN_ACCESSIBILITY_DEFAULT, RUN_AUDIT_DEFAULT
DEFAULT_SKETCH = BACKEND_DIR / "test_sketch.jpg"
DEFAULT_WS = "ws://localhost:8000/ws"

# Baseline pipeline times without audit/a11y (seconds)
BASELINE_PIPELINE: dict[str, float] = {
    "test_sketch.jpg": 4.5,
    "test_sketch_dashboard.jpg": 6.1,
    "test_sketch_list.jpg": 8.5,
}

EXPECTED_AGENTS = ("vision_parser", "architect", "code_forge", "auditor", "accessibility")

# Expected login-form components for accuracy scoring
EXPECTED_COMPONENTS: list[tuple[tuple[str, ...], str]] = [
    (("heading", "text"), "login"),
    (("input",), "email"),
    (("input",), "password"),
    (("button",), "sign in"),
]


@dataclass
class RunMetrics:
    sketch_path: Path | None = None
    vision_latency: float | None = None
    architect_latency: float | None = None
    code_forge_latency: float | None = None
    auditor_latency: float | None = None
    accessibility_latency: float | None = None
    vision_output: dict | None = None
    architect_output: dict | None = None
    auditor_output: dict | None = None
    total_elapsed: float = 0.0
    final_code: str | None = None
    code_forge_code: str | None = None
    accessibility_code: str | None = None
    error_detail: str | None = None
    pipeline_success: bool | None = None
    pipeline_issues: list[dict] = field(default_factory=list)
    agent_error_events: list[str] = field(default_factory=list)
    saw_error_before_complete: bool = False
    accuracy_hits: list[str] = field(default_factory=list)
    accuracy_misses: list[str] = field(default_factory=list)
    show_accuracy_score: bool = True
    run_audit: bool = True
    run_accessibility: bool = True
    agents_done: list[str] = field(default_factory=list)
    event_trace: list[str] = field(default_factory=list)

    @property
    def accuracy_score(self) -> str:
        hits = len(self.accuracy_hits)
        return f"{hits}/{len(EXPECTED_COMPONENTS)}"

    @property
    def vision_model(self) -> str:
        return os.environ.get("ANTHROPIC_VISION_MODEL", "claude-sonnet-4-6")


def load_image_base64(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(suffix, "image/jpeg")
    return base64.b64encode(path.read_bytes()).decode("ascii"), mime


def score_vision_output(components: list[dict]) -> tuple[list[str], list[str]]:
    """Return (hits, misses) for expected login-form elements."""
    hits: list[str] = []
    misses: list[str] = []
    used: set[int] = set()

    for allowed_types, expected_label in EXPECTED_COMPONENTS:
        found = False
        for i, comp in enumerate(components):
            if i in used:
                continue
            comp_type = comp.get("type", "").lower()
            comp_label = comp.get("label", "").lower().strip()
            if comp_type in allowed_types and expected_label in comp_label:
                hits.append(f"{comp_type}:{comp.get('label', '')}")
                used.add(i)
                found = True
                break
        if not found:
            type_hint = allowed_types[0]
            misses.append(f"{type_hint}:{expected_label}")

    return hits, misses


def format_message(msg: dict, *, full_output: bool = False) -> str:
    msg_type = msg.get("type", "unknown")
    agent = msg.get("agent", "")

    if msg_type == "agent_status":
        return (
            f"[agent_status] {agent}: {msg.get('status')} "
            f"— {msg.get('message', '')}"
        )
    if msg_type == "agent_token":
        token = msg.get("token", "")
        preview = token.replace("\n", "\\n")
        if len(preview) > 80:
            preview = preview[:80] + "…"
        return f"[agent_token] {agent}: {preview!r}"
    if msg_type == "agent_output":
        output = msg.get("output", {})
        preview = json.dumps(output, indent=2)
        if not full_output and len(preview) > 600:
            preview = preview[:600] + "\n… (truncated)"
        return f"[agent_output] {agent}:\n{preview}"
    if msg_type == "final_code":
        code = msg.get("code", "")
        return f"[final_code] ({len(code)} chars)"
    if msg_type == "tps":
        return f"[tps] {agent}: {msg.get('tokens_per_second')} tok/s"
    if msg_type == "pipeline_complete":
        success = msg.get("success", True)
        return f"[pipeline_complete] success={success} code={len(msg.get('code', ''))} chars"
    if msg_type == "error":
        agent_part = f" agent={msg['agent']}" if msg.get("agent") else ""
        return f"[error]{agent_part}: {msg.get('message', msg)}"
    return f"[{msg_type}] {json.dumps(msg)[:300]}"


def assess_code_plausibility(code: str) -> list[str]:
    checks: list[str] = []
    checks.append(f"length={len(code)} chars")
    checks.append("has export default" if "export default" in code else "MISSING export default")
    checks.append("has Tailwind classes" if "className=" in code else "MISSING className")
    checks.append("has JSX" if "<" in code and ">" in code else "MISSING JSX")
    checks.append("has aria-*" if "aria-" in code else "no aria-*")
    checks.append("has trackEvent" if "trackEvent" in code else "no trackEvent")
    return checks


def baseline_for_sketch(sketch_path: Path | None) -> float | None:
    if sketch_path is None:
        return None
    return BASELINE_PIPELINE.get(sketch_path.name)


def trace_line(msg: dict, t0: float) -> str:
    msg_type = msg.get("type", "unknown")
    agent = msg.get("agent", "")
    parts = [f"+{time.perf_counter() - t0:.3f}s", msg_type]
    if agent:
        parts.append(f"agent={agent}")
    if msg_type == "agent_status":
        parts.append(f"status={msg.get('status')}")
    if msg_type == "final_code":
        parts.append(f"code_len={len(msg.get('code', ''))}")
    if msg_type == "error":
        parts.append(f"msg={msg.get('message', '')[:80]}")
    return " ".join(parts)


async def run_test(
    ws_url: str,
    sketch_path: Path,
    description: str,
    *,
    quiet: bool = False,
    full_output: bool = False,
    show_accuracy_score: bool = True,
    run_audit: bool | None = None,
    run_accessibility: bool | None = None,
    trace: bool = False,
) -> RunMetrics:
    image_b64, mime = load_image_base64(sketch_path)
    effective_audit = run_audit if run_audit is not None else RUN_AUDIT_DEFAULT
    effective_accessibility = (
        run_accessibility if run_accessibility is not None else RUN_ACCESSIBILITY_DEFAULT
    )
    payload: dict[str, object] = {
        "type": "generate",
        "image_base64": image_b64,
        "mime_type": mime,
        "description": description,
    }
    if run_audit is not None:
        payload["run_audit"] = run_audit
    if run_accessibility is not None:
        payload["run_accessibility"] = run_accessibility

    metrics = RunMetrics(
        sketch_path=sketch_path,
        show_accuracy_score=show_accuracy_score,
        run_audit=effective_audit,
        run_accessibility=effective_accessibility,
    )
    vision_start: float | None = None
    architect_start: float | None = None
    code_forge_start: float | None = None
    auditor_start: float | None = None
    accessibility_start: float | None = None
    final_code_count = 0
    start = time.perf_counter()
    trace_t0 = start

    if not quiet:
        print(f"Connecting to {ws_url}")
        print(f"Sketch: {sketch_path} ({sketch_path.stat().st_size} bytes)")
        print(f"Description: {description!r}\n")

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps(payload))
        if not quiet:
            print("Sent generate request. Streaming events:\n")

        async for raw in ws:
            msg = json.loads(raw)
            msg_type = msg.get("type", "unknown")
            agent = msg.get("agent", "")

            if agent == "vision_parser" and msg_type == "agent_status":
                if msg.get("status") == "thinking":
                    vision_start = time.perf_counter()
                elif msg.get("status") == "done" and vision_start is not None:
                    metrics.vision_latency = time.perf_counter() - vision_start

            if agent == "architect" and msg_type == "agent_status":
                if msg.get("status") == "thinking":
                    architect_start = time.perf_counter()
                elif msg.get("status") == "done" and architect_start is not None:
                    metrics.architect_latency = time.perf_counter() - architect_start

            if agent == "code_forge" and msg_type == "agent_status":
                if msg.get("status") == "streaming":
                    code_forge_start = time.perf_counter()
                elif msg.get("status") == "done" and code_forge_start is not None:
                    metrics.code_forge_latency = time.perf_counter() - code_forge_start

            if agent == "auditor" and msg_type == "agent_status":
                if msg.get("status") == "thinking":
                    auditor_start = time.perf_counter()
                elif msg.get("status") == "done" and auditor_start is not None:
                    metrics.auditor_latency = time.perf_counter() - auditor_start

            if agent == "accessibility" and msg_type == "agent_status":
                if msg.get("status") == "streaming":
                    accessibility_start = time.perf_counter()
                elif msg.get("status") == "done" and accessibility_start is not None:
                    metrics.accessibility_latency = time.perf_counter() - accessibility_start

            if agent == "vision_parser" and msg_type == "agent_output":
                metrics.vision_output = msg.get("output")

            if agent == "architect" and msg_type == "agent_output":
                metrics.architect_output = msg.get("output")

            if agent == "auditor" and msg_type == "agent_output":
                metrics.auditor_output = msg.get("output")

            if agent and msg_type == "agent_status":
                if msg.get("status") == "done" and agent not in metrics.agents_done:
                    metrics.agents_done.append(agent)
                if msg.get("status") == "error":
                    metrics.agent_error_events.append(f"{agent}: {msg.get('message', '')}")

            if trace:
                line = trace_line(msg, trace_t0)
                metrics.event_trace.append(line)
                print(f"TRACE {line}")

            if not quiet:
                print(format_message(msg, full_output=full_output))

            if msg_type == "final_code":
                code = msg.get("code", "")
                final_code_count += 1
                if final_code_count == 1:
                    metrics.code_forge_code = code
                else:
                    metrics.accessibility_code = code
                metrics.final_code = code
            if msg_type == "pipeline_complete":
                metrics.final_code = msg.get("code", metrics.final_code)
                metrics.pipeline_success = msg.get("success", True)
                metrics.pipeline_issues = msg.get("issues") or []
                break
            if msg_type == "error":
                agent_name = msg.get("agent", "unknown")
                metrics.error_detail = f"[{agent_name}] {msg.get('message', raw)}"
                metrics.saw_error_before_complete = True

    metrics.total_elapsed = time.perf_counter() - start

    if metrics.vision_output and metrics.show_accuracy_score:
        components = metrics.vision_output.get("components", [])
        hits, misses = score_vision_output(components)
        metrics.accuracy_hits = hits
        metrics.accuracy_misses = misses

    return metrics


def print_summary(metrics: RunMetrics, *, show_code: bool = True) -> None:
    print(f"\n{'=' * 60}")
    print("SUMMARY")
    if metrics.sketch_path:
        print(f"  sketch: {metrics.sketch_path.name}")
    print(f"  model: {metrics.vision_model}")
    if metrics.vision_latency is not None:
        print(f"  vision_parser latency: {metrics.vision_latency:.2f}s")
    else:
        print("  vision_parser latency: (not measured)")
    if metrics.architect_latency is not None:
        print(f"  architect latency: {metrics.architect_latency:.2f}s")
    if metrics.code_forge_latency is not None:
        print(f"  code_forge latency: {metrics.code_forge_latency:.2f}s")

    if metrics.vision_output:
        components = metrics.vision_output.get("components", [])
        comp_list = [f"{c.get('type', '?')}:{c.get('label', '')}" for c in components]
        print(f"  vision components ({len(components)}): {', '.join(comp_list)}")
        title = metrics.vision_output.get("screen_title", "")
        if title:
            print(f"  screen_title: {title}")
        notes = metrics.vision_output.get("notes", "")
        if notes:
            print(f"  vision notes: {notes[:200]}")

    if metrics.show_accuracy_score:
        print(f"  login accuracy: {metrics.accuracy_score}", end="")
        if metrics.accuracy_hits:
            print(f" ({', '.join(metrics.accuracy_hits)})")
        else:
            print()
        if metrics.accuracy_misses:
            print(f"  missed: {', '.join(metrics.accuracy_misses)}")

    if metrics.architect_output:
        tree = metrics.architect_output.get("component_tree", "")
        preview = tree[:500] + ("…" if len(tree) > 500 else "")
        print(f"  architect tree:\n{preview}")
        layout = metrics.architect_output.get("layout_plan", "")
        if layout:
            layout_preview = layout[:300] + ("…" if len(layout) > 300 else "")
            print(f"  architect layout: {layout_preview}")

    if metrics.run_audit:
        if metrics.auditor_latency is not None:
            print(f"  auditor latency: {metrics.auditor_latency:.2f}s")
        if metrics.auditor_output:
            issues = metrics.auditor_output.get("issues", [])
            summary = metrics.auditor_output.get("summary", "")
            print(f"  auditor issues ({len(issues)}): {summary}")
            for i, issue in enumerate(issues, 1):
                sev = issue.get("severity", "?")
                msg = issue.get("message", "")
                line_hint = issue.get("line_hint", "")
                print(f"    {i}. [{sev}] {msg}")
                if line_hint:
                    print(f"       line_hint: {line_hint}")
        else:
            print("  auditor: no output captured")

    if metrics.run_accessibility:
        if metrics.accessibility_latency is not None:
            print(f"  accessibility latency: {metrics.accessibility_latency:.2f}s")
        if metrics.code_forge_code:
            cf_checks = assess_code_plausibility(metrics.code_forge_code)
            print(f"  code_forge checks: {', '.join(cf_checks)}")
        if metrics.accessibility_code:
            a11y_checks = assess_code_plausibility(metrics.accessibility_code)
            print(f"  accessibility checks: {', '.join(a11y_checks)}")
        elif metrics.run_accessibility and not metrics.error_detail:
            print("  accessibility: no patched code captured (same as code_forge?)")

    baseline = baseline_for_sketch(metrics.sketch_path)
    print(f"  full pipeline: {metrics.total_elapsed:.1f}s")
    if metrics.pipeline_success is not None:
        print(f"  pipeline_complete.success: {metrics.pipeline_success}")
    if metrics.pipeline_issues:
        print(f"  pipeline_complete.issues ({len(metrics.pipeline_issues)}):")
        for issue in metrics.pipeline_issues:
            agent = issue.get("agent", "?")
            sev = issue.get("severity", "?")
            desc = issue.get("description", "")
            region = issue.get("code_region", "")
            line = f"    [{agent}/{sev}] {desc}"
            if region:
                line += f" ({region})"
            print(line)
    agents_missing = [a for a in EXPECTED_AGENTS if a not in metrics.agents_done]
    print(f"  agents done ({len(metrics.agents_done)}/5): {', '.join(metrics.agents_done) or 'none'}")
    if agents_missing:
        print(f"  agents missing: {', '.join(agents_missing)}")
    if metrics.final_code:
        has_aria = "aria-" in metrics.final_code
        has_track = "trackEvent" in metrics.final_code
        patched = bool(
            metrics.code_forge_code
            and metrics.final_code != metrics.code_forge_code
        )
        print(
            f"  content check: aria-*={'yes' if has_aria else 'NO'}, "
            f"trackEvent={'yes' if has_track else 'NO'}, "
            f"final patched={'yes' if patched else 'NO'}"
        )
    if metrics.saw_error_before_complete:
        print("  error preceded pipeline_complete: yes")
    if metrics.agent_error_events:
        print(f"  agent_status errors: {', '.join(metrics.agent_error_events)}")
    if baseline is not None:
        added = metrics.total_elapsed - baseline
        agent_sum = (metrics.auditor_latency or 0) + (metrics.accessibility_latency or 0)
        print(f"  baseline (no audit/a11y): {baseline:.1f}s")
        print(f"  added latency: {added:+.1f}s (auditor+a11y measured: {agent_sum:.2f}s)")

    if metrics.error_detail and metrics.pipeline_success is False:
        print(f"  FAILED: {metrics.error_detail}")
        if metrics.event_trace:
            print("  event trace:")
            for line in metrics.event_trace:
                print(f"    {line}")
        return

    if metrics.error_detail and metrics.pipeline_success:
        print(f"  partial failure (core OK): {metrics.error_detail}")

    if metrics.pipeline_success is False and not metrics.final_code:
        print("  FAILED: pipeline ended without final code")
        if metrics.event_trace:
            print("  event trace:")
            for line in metrics.event_trace:
                print(f"    {line}")
        return

    if not metrics.final_code and metrics.pipeline_success is not False:
        print("  FAILED: pipeline ended without final code")
        if metrics.event_trace:
            print("  event trace:")
            for line in metrics.event_trace:
                print(f"    {line}")
        return

    checks = assess_code_plausibility(metrics.final_code)
    print(f"  code checks: {', '.join(checks)}")

    if show_code:
        print("\nSUCCESS — final code:\n")
        print("-" * 60)
        print(metrics.final_code)
        print("-" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(description="Test SketchStorm WebSocket pipeline")
    parser.add_argument("--ws", default=DEFAULT_WS, help=f"WebSocket URL (default: {DEFAULT_WS})")
    parser.add_argument("--sketch", type=Path, default=DEFAULT_SKETCH, help="Sketch image path")
    parser.add_argument("--description", default="a login form", help="Text description")
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress streaming events; print summary only",
    )
    parser.add_argument(
        "--no-code",
        action="store_true",
        help="Omit final code block from output",
    )
    parser.add_argument(
        "--full-output",
        action="store_true",
        help="Do not truncate agent_output JSON in verbose mode",
    )
    parser.add_argument(
        "--no-accuracy-score",
        action="store_true",
        help="Skip login-form 4/4 accuracy scoring",
    )
    parser.add_argument(
        "--run-audit",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable auditor (default: server RUN_AUDIT_DEFAULT / omit from WS payload)",
    )
    parser.add_argument(
        "--run-accessibility",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Enable/disable accessibility (default: server RUN_ACCESSIBILITY_DEFAULT / omit from WS payload)",
    )
    parser.add_argument(
        "--trace",
        action="store_true",
        help="Log ordered WS events with timestamps (investigation)",
    )
    args = parser.parse_args()

    if not args.sketch.exists():
        print(f"Sketch not found: {args.sketch}", file=sys.stderr)
        sys.exit(1)

    show_accuracy = not args.no_accuracy_score and args.sketch.name == "test_sketch.jpg"

    try:
        metrics = asyncio.run(
            run_test(
                args.ws,
                args.sketch,
                args.description,
                quiet=args.quiet,
                full_output=args.full_output,
                show_accuracy_score=show_accuracy,
                run_audit=args.run_audit,
                run_accessibility=args.run_accessibility,
                trace=args.trace,
            )
        )
    except Exception as exc:
        print(f"\nFATAL: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)

    print_summary(metrics, show_code=not args.no_code)

    if metrics.error_detail or not metrics.final_code:
        sys.exit(1)


if __name__ == "__main__":
    main()
