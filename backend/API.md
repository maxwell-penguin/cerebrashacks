# SketchStorm Backend API

Frontend integration reference for the React app.

## Quick start

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # set CEREBRAS_API_KEY
uvicorn main:app --reload --port 8000
```

Hour-0 check (confirm model id + image format):

```bash
python scripts/sanity_check.py path/to/sketch.jpg
```

## Endpoints

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/health` | Liveness |
| POST | `/generate` | Sync pipeline (multipart form) |
| POST | `/audit` | Code audit only |
| POST | `/audit/full` | Audit + optional accessibility pass |
| POST | `/visual-check` | SimUI one-pass (JSON body) |
| WS | `/ws` | **Primary** — streaming generate |

## WebSocket protocol (`/ws`)

Connect, then send one message to start the pipeline:

```json
{
  "type": "generate",
  "image_base64": "<base64 or data-uri>",
  "mime_type": "image/jpeg",
  "description": "Mobile dashboard, dark mode",
  "run_audit": true,
  "run_accessibility": true,
  "screenshot_base64": "",
  "screenshot_mime_type": "image/png",
  "design_contract": ""
}
```

Set `screenshot_base64` (after Code Forge finishes) to run SimUI in the same session.

Omit `run_audit` / `run_accessibility` to use server defaults from `.env` (both default to **true**).

`pipeline_complete` includes a normalized `issues` array (Auditor findings today; A11y reserved for future structured output):

```json
{
  "type": "pipeline_complete",
  "success": true,
  "code": "...",
  "issues": [
    {
      "agent": "Auditor",
      "severity": "warn",
      "description": "Nav items lack keyboard accessibility",
      "code_region": "Sidebar li"
    }
  ],
  "vision": { },
  "architecture": { },
  "audit": { }
}
```

Severity values: `error`, `warn`, `info` (mapped from Auditor `warning` → `warn`).

### Server → client events

| type | fields | when |
|------|--------|------|
| `agent_status` | `agent`, `status`, `message?` | Agent lifecycle |
| `agent_token` | `agent`, `token` | Streaming tokens (code_forge, accessibility) |
| `agent_output` | `agent`, `output` | Structured JSON result |
| `final_code` | `code` | Complete JSX snapshot |
| `tps` | `agent`, `tokens_per_second` | Throughput overlay |
| `pipeline_complete` | `success`, `code`, `issues`, `vision`, `architecture`, `audit`, `visual_check` | **Terminal** — pipeline finished (always last) |
| `error` | `message`, `agent?` | Agent failure; may precede `pipeline_complete` on partial failures |

### Agent names

`vision_parser` → `architect` → `code_forge` → (`auditor`) → (`accessibility`) → (`vision_critic`)

### Status values

`idle` | `thinking` | `streaming` | `done` | `error` | `skipped`

## POST `/generate` (sync / curl testing)

Multipart form fields:

- `image` (file, required)
- `description` (string, optional)
- `run_audit` (bool, default **true** via `RUN_AUDIT_DEFAULT`)
- `run_accessibility` (bool, default **true** via `RUN_ACCESSIBILITY_DEFAULT`)
- `run_visual_check` (bool, default false)
- `screenshot` (file, optional — required if `run_visual_check=true`)
- `design_contract` (string, optional)

Returns full JSON with `vision`, `architecture`, `code`, optional `audit` / `visual_check`.

## POST `/visual-check`

```json
{
  "code": "import { useState } from 'react';\n\nexport default function App() { ... }",
  "design_contract": "Cards aligned in 2-column grid, primary CTA at bottom",
  "description": "Original sketch context",
  "screenshot_base64": ""
}
```

**Primary path:** pass `code` — the server renders JSX to a PNG via headless Chromium (Playwright + React/Babel/Tailwind CDN), then runs Vision Critic.

**Fallback:** pass `screenshot_base64` (PNG/JPEG) to skip server-side rendering (e.g. frontend-captured iframe).

**Response** (additive fields on existing `passed` / `issues` / `summary`):

```json
{
  "passed": true,
  "status": "pass_with_warnings",
  "summary": "Passed — 2 minor issues noted.",
  "issues": [
    {
      "category": "spacing",
      "severity": "minor",
      "description": "Stat cards could use more vertical padding",
      "suggestion": "Increase p-6 to p-8 on card containers"
    }
  ]
}
```

`status` is derived: `pass` (passed + no issues), `pass_with_warnings` (passed + issues), `fail` (passed false). `summary` is derived when the Vision Critic omits one.

Debug screenshots are saved under `backend/tmp/render/screenshots/`.

## Preview iframe contract

Code Forge outputs a single default-exported `App` component using Tailwind utilities. The preview iframe should load:

- React 18 (UMD or esm.sh)
- Tailwind CDN
- Babel standalone to transpile JSX, or receive pre-transpiled code

Example wrapper your friend can use in the iframe `srcdoc`.

## Environment

| Variable | Default | Notes |
|----------|---------|-------|
| `CEREBRAS_API_KEY` | — | Required for text agents (Architect, Code Forge, etc.) |
| `CEREBRAS_MODEL` | `gpt-oss-120b` | Text-only agents; confirm in Cerebras console |
| `ANTHROPIC_API_KEY` | — | Required when `VISION_PROVIDER=anthropic` |
| `VISION_PROVIDER` | `anthropic` | `anthropic` or `cerebras` — flip to `cerebras` when Gemma 4 vision lands |
| `ANTHROPIC_VISION_MODEL` | `claude-sonnet-4-6` | Vision Parser + Vision Critic when using Anthropic |
| `RUN_AUDIT_DEFAULT` | `true` | Run Skeptical Auditor when WS/client omits `run_audit` |
| `RUN_ACCESSIBILITY_DEFAULT` | `true` | Run Accessibility pass when WS/client omits `run_accessibility` |
