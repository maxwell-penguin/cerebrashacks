# SketchStorm Studio

SketchStorm Studio turns a photo of a hand-drawn UI into a live React + Tailwind app. Upload a sketch (or snap a sticky-note wireframe), describe what you want, and six specialized agents collaborate in real time: vision parses your drawing, an architect plans the layout, code streams into a Monaco editor, an auditor and accessibility pass harden the output, and SimUI’s vision critic compares a rendered screenshot against your intent. The whole loop is built to be shown on stage—sketch in, working UI out.

## Prize tracks

**Multiverse Agents** — Six agents with distinct roles: `vision_parser`, `architect`, `code_forge`, `auditor`, `accessibility`, and `vision_critic`. The first five run on the primary WebSocket generate path; the Studio UI then triggers `vision_critic` automatically via `/visual-check` after code lands. Each agent streams status, structured JSON, or tokens so you can watch collaboration happen.

**Enterprise Impact** — SimUI is a CI/CD-style visual guardrail: headless Chromium (Playwright) renders generated JSX, captures a PNG, and the Vision Critic compares it to a design contract. The same `/visual-check` endpoint can gate merges—pass/fail plus structured issues—without manual screenshot review.

**People's Choice** — The core story is instantly demoable: photograph a sketch, hit Generate, watch agents light up, see code stream, preview the app in-browser. Validated demo artifacts (including a real hand-drawn dashboard) live under `backend/scripts/battery_results/finalists/`; the hero sketch for recording is `dashboard_real/`.

## Architecture

```
sketch photo → vision_parser → architect → code_forge → auditor → accessibility
                                                                    ↓
                                              preview iframe ← final JSX
                                                                    ↓
                                    Playwright render → vision_critic (SimUI)
```

| Layer | Stack |
|-------|--------|
| Backend | FastAPI, WebSockets (`/ws`), Playwright for screenshot render |
| Text agents | Cerebras (`gpt-oss-120b` default via `CEREBRAS_API_KEY`) — Architect, Code Forge, Auditor, Accessibility |
| Vision | Anthropic Claude (`ANTHROPIC_VISION_MODEL`, default `claude-haiku-4-5` in `.env.example`) for Vision Parser + Vision Critic; `VISION_PROVIDER=cerebras` reserved for when Gemma 4 vision lands on Cerebras |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Monaco (`@monaco-editor/react`) |

**Production-minded resilience** (see `backend/cerebras_client.py`, `backend/orchestrator.py`, `backend/parsing.py`):

- Per-call timeouts (20–25s JSON/stream, 8s inter-token stall detection)
- One retry on rate limits (429) and transient API errors
- Per-agent try/except — a failed optional agent does not crash the session; `pipeline_complete` always fires with `success`
- JSON repair for structured agent outputs (Auditor issues use `line_hint` instead of fragile inline patch strings)

Full API and event shapes: [`backend/API.md`](backend/API.md).

## Run locally

**Prerequisites:** Python 3.11+, Node 18+, `CEREBRAS_API_KEY`, and `ANTHROPIC_API_KEY` (vision is Anthropic today).

**Terminal 1 — backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp .env.example .env   # fill in API keys
uvicorn main:app --reload --port 8000
```

**Terminal 2 — frontend**

```bash
cd frontend
npm install
npm run dev
```

Open the Vite URL (default `http://localhost:5173`). The app connects to `ws://localhost:8000/ws`.

**Quick backend-only test** (no UI):

```bash
cd backend && source .venv/bin/activate
python scripts/test_generate_ws.py --sketch scripts/real_dashboard_sketch.jpg \
  --description "admin dashboard with sidebar navigation, header, and two stat cards"
```

## What's real vs. known limitations

**What works today**

- Full 5-agent generate path with Auditor and Accessibility **on by default** (`RUN_AUDIT_DEFAULT=true`, `RUN_ACCESSIBILITY_DEFAULT=true` in `.env.example`)
- Hand-drawn photos: validated at ~9.5s for a real dashboard sketch (vs ~8.2s synthetic); layout detection held up; see `finalists/README.md`
- Studio UI: upload + vision bounding-box overlay, streaming Monaco editor, live srcdoc preview (same CDN React/Babel/Tailwind pattern as `render_screenshot.py`), agent status columns, auto visual-check after success
- SimUI `/visual-check` with server-side Playwright render

**Honest limits**

- **Latency** — End-to-end runs are roughly **5–11 seconds** on tested sketches, not sub-second. Throughput is fast once streaming starts, but vision + five agents add up.
- **Vision provider** — Sketch parsing uses **Claude vision**, not Cerebras Gemma 4 yet (`VISION_PROVIDER=anthropic`). Text generation is Cerebras `gpt-oss-120b`.
- **Sketch fidelity** — If your drawing uses generic labels (“stat”, “side bar”) the vision stage reads layout well, but downstream agents may **invent** nav items and metrics from your description—not from the ink. Write key labels legibly if you need literal text in the output.
- **Auditor JSON** — Structured JSON from the Auditor can still fail on unusual outputs; we mitigate with repair logic and `line_hint`-only issues (no embedded JSX patches). On failure the agent errors gracefully and the pipeline still completes.
- **Preview environment** — In-browser preview transpiles JSX via Babel CDN; it is a demo surface, not a production bundler.
- **Vision Critic** — Runs as a **follow-up** `/visual-check` call (triggered by the Studio UI), not inside the core WebSocket chain unless you pass a screenshot in the generate payload.
- **Rate limits** — Heavy back-to-back runs can hit Cerebras 429s; the client retries once after 2s.

Demo bundles (sketch, `run.txt`, `final.jsx`, `preview.png`): [`backend/scripts/battery_results/finalists/`](backend/scripts/battery_results/finalists/).
