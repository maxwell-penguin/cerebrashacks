#!/usr/bin/env python3
"""E2E test for the /auto-refine endpoint."""

from __future__ import annotations

import json
import sys
from pathlib import Path
import httpx
from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_DIR / ".env")

API_URL = "http://localhost:8000/auto-refine"

def main() -> None:
    # Starting code with absolutely NO login form elements
    start_code = """
import React from 'react';

export default function App() {
  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center p-4">
      <div className="text-center">
        <h1 className="text-2xl font-bold text-slate-800">Hello World</h1>
      </div>
    </div>
  );
}
"""

    design_contract = (
      "A clean professional Login form. Should have email input, password input, and a Sign In submit button."
    )
    description = "Login page with email/password input fields and a Sign In button."

    payload = {
        "code": start_code,
        "design_contract": design_contract,
        "description": description,
    }

    print(f"POSTing to {API_URL} ... (This may take up to 90 seconds to run up to 3 iterations)")
    
    try:
        with httpx.Client(timeout=150.0) as client:
            resp = client.post(API_URL, json=payload)
            resp.raise_for_status()
            result = resp.json()
    except Exception as exc:
        print(f"Request failed: {exc}", file=sys.stderr)
        sys.exit(1)

    print("\n--- Auto Refine Result ---")
    print(f"Iterations Run: {result.get('iterations_run')}")
    print(f"Stopped Reason: {result.get('stopped_reason')}")
    
    issues_per_iter = result.get("issues_per_iteration", [])
    print(f"Issues Per Iteration ({len(issues_per_iter)}):")
    for idx, issues in enumerate(issues_per_iter, 1):
        print(f"  Iteration {idx} - Found {len(issues)} issues:")
        for issue in issues:
            print(f"    - [{issue.get('category')}] ({issue.get('severity')}): {issue.get('description')}")
            
    final_code = result.get("final_code", "")
    print(f"\nFinal code length: {len(final_code)} chars")
    
    # Save final code to scratch to inspect it
    output_path = BACKEND_DIR / "tmp" / "auto_refine_output.tsx"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(final_code, encoding="utf-8")
    print(f"Saved final code to: {output_path}")

if __name__ == "__main__":
    main()
