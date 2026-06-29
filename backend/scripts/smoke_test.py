#!/usr/bin/env python3
"""
Smoke tests for the SketchStorm backend.

Usage:
  # Start the backend first:
  cd backend && bash dev.sh

  # Then in another terminal:
  python backend/scripts/smoke_test.py

  # Or specify a custom base URL:
  python backend/scripts/smoke_test.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

BACKEND_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent

PASS = 0
FAIL = 0


def report(name: str, ok: bool, detail: str = "") -> None:
    global PASS, FAIL
    status = "✅ PASS" if ok else "❌ FAIL"
    extra = f" — {detail}" if detail else ""
    print(f"  {status}: {name}{extra}")
    if ok:
        PASS += 1
    else:
        FAIL += 1


def _post_json(base_url: str, path: str, body: dict | None = None) -> tuple[int, dict]:
    url = f"{base_url}{path}"
    data = json.dumps(body).encode() if body else None
    req = Request(url, data=data, headers={"Content-Type": "application/json"} if data else {}, method="POST" if data else "GET")
    try:
        with urlopen(req, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else {}
    except HTTPError as e:
        return e.code, json.loads(e.read()) if e.fp else {}
    except URLError as e:
        return 0, {"error": str(e.reason)}


def test_health(base_url: str) -> None:
    code, data = _post_json(base_url, "/health")
    ok = code == 200 and data.get("status") == "ok"
    report("GET /health", ok, f"status={code} {data.get('status','')}")


def test_text_generate(base_url: str) -> None:
    """Generate from a text description only (no sketch)."""
    # Using form data via multipart is tricky with urllib — use the WebSocket
    # endpoint instead or the /generate endpoint with form fields.
    # For simplicity, we test the text-only path.
    from urllib.parse import urlencode

    body = urlencode({
        "description": "A simple login form with email and password",
        "run_audit": "false",
        "run_accessibility": "false",
    }).encode()

    req = Request(f"{base_url}/generate", data=body, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read())
            has_code = bool(data.get("code", ""))
            has_vision = data.get("vision") is not None or True  # text-only may skip vision
            report(
                "POST /generate (text-only)",
                has_code and resp.status == 200,
                f"code_len={len(data.get('code',''))}",
            )
    except HTTPError as e:
        body = e.read().decode() if e.fp else str(e)
        report("POST /generate (text-only)", False, f"HTTP {e.code}: {body[:120]}")
    except URLError as e:
        report("POST /generate (text-only)", False, str(e.reason))


def test_audit(base_url: str) -> None:
    sample_code = """
export default function App() {
  return <div><button onClick={() => alert('hi')}>Click</button></div>;
}
""".strip()
    code, data = _post_json(base_url, "/audit", {
        "code": sample_code,
        "run_accessibility": False,
    })
    ok = code == 200 and "issues" in data
    report("POST /audit", ok, f"issues={len(data.get('issues',[]))}")


def test_chat(base_url: str) -> None:
    code, data = _post_json(base_url, "/chat", {
        "agent": "architect",
        "message": "Suggest a layout for a dashboard.",
        "context": {"route": "/", "layout_summary": "", "code_summary": ""},
    })
    ok = code == 200 and bool(data.get("reply", ""))
    report("POST /chat", ok, f"reply_len={len(data.get('reply',''))}")


def test_auto_refine(base_url: str) -> None:
    sample_code = """
import { useState } from 'react';

export default function App() {
  const [count, setCount] = useState(0);
  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold">Counter</h1>
      <button onClick={() => setCount(count + 1)} className="px-4 py-2 bg-blue-500 text-white rounded">
        Count: {count}
      </button>
    </div>
  );
}
""".strip()
    code, data = _post_json(base_url, "/auto-refine", {
        "code": sample_code,
        "design_contract": "Simple centered counter with button",
        "description": "Counter app",
    })
    ok = code == 200 and bool(data.get("final_code", ""))
    report(
        "POST /auto-refine",
        ok,
        f"iterations={data.get('iterations_run','?')} reason={data.get('stopped_reason','?')}",
    )


def test_refine_region(base_url: str) -> None:
    sample_code = """
export default function App() {
  return (
    <div className="p-8">
      <h1 className="text-xl">Hello</h1>
    </div>
  );
}
""".strip()
    code, data = _post_json(base_url, "/refine-region", {
        "code": sample_code,
        "region_description": "the heading",
        "refinement_request": "Make it blue and larger",
    })
    ok = code == 200 and bool(data.get("patched_code", ""))
    report(
        "POST /refine-region",
        ok,
        f"lines_changed={data.get('diff_stats',{}).get('lines_changed','?')}",
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="SketchStorm backend smoke tests")
    parser.add_argument("--base-url", default="http://localhost:8000", help="Backend base URL")
    args = parser.parse_args()
    base_url = args.base_url.rstrip("/")

    print(f"🔍 Smoke testing {base_url} …\n")

    # 1. Health check — must pass for anything else to work
    test_health(base_url)

    if FAIL > 0:
        print("\n❌ Backend is not reachable. Start it with: cd backend && bash dev.sh")
        sys.exit(1)

    # 2. Core endpoints
    test_text_generate(base_url)
    test_audit(base_url)
    test_chat(base_url)

    # 3. Refinement endpoints (slower — these call LLMs)
    print("  (slower tests — calling LLMs, may take 30-60s each)")
    test_refine_region(base_url)
    test_auto_refine(base_url)

    # Summary
    total = PASS + FAIL
    print(f"\n{'='*40}")
    print(f"Results: {PASS}/{total} passed", end="")
    if FAIL > 0:
        print(f", {FAIL} failed ❌")
        sys.exit(1)
    else:
        print(" ✅")
        print("All smoke tests passed!")


if __name__ == "__main__":
    main()
