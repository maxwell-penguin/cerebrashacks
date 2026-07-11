# SketchStorm Studio

SketchStorm Studio converts a photo of a hand-drawn UI sketch into a working React and Tailwind app in real time. Upload a sketch or snap a sticky-note wireframe, describe what you want, and six specialized AI agents collaborate to build it: a vision agent reads your drawing, an architect plans the layout, code streams live into a Monaco editor, an auditor and accessibility agent harden the output, and a vision critic compares a rendered screenshot against your original intent.

Built at the **Cerebras x Google DeepMind Gemma 4 Hackathon**. Live at [cerebrashacks.vercel.app](https://cerebrashacks.vercel.app).

---

## How it works

```
sketch photo → vision_parser → architect → code_forge → auditor → accessibility
                                                                    ↓
                                              preview iframe ← final JSX
                                                                    ↓
                                    Playwright render → vision_critic (SimUI)
```

Six agents run sequentially, each with a distinct role:

- **Vision Parser** — reads the sketch image and extracts a structured layout description
- **Architect** — turns the layout into a component plan
- **Code Forge** — streams live React and Tailwind code into the editor
- **Auditor** — reviews the generated code and flags issues
- **Accessibility** — patches the code for ARIA compliance and accessibility
- **Vision Critic** — renders the app with headless Chromium via Playwright and compares the screenshot against the original sketch intent

---

## Tech stack

| Layer | Stack |
|-------|--------|
| Backend | FastAPI, WebSockets, Playwright |
| Text agents | Cerebras `gpt-oss-120b` (Architect, Code Forge, Auditor, Accessibility) |
| Vision agents | Anthropic Claude (Vision Parser, Vision Critic) |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Monaco Editor |

---

## Reliability

The backend is built with production habits in mind. See `cerebras_client.py`, `orchestrator.py`, and `parsing.py`:

- Per-call timeouts (20-25s for JSON/stream, 8s inter-token stall detection)
- One retry on rate limits (429) and transient API errors
- Per-agent error isolation — a failed optional agent does not crash the session; `pipeline_complete` always fires with a clean success or failure state
- JSON repair for structured agent outputs so malformed responses degrade gracefully

Full API and event shapes: [`backend/API.md`](backend/API.md).

---

## Run locally

**Prerequisites:** Python 3.11+, Node 18+, `CEREBRAS_API_KEY`, `ANTHROPIC_API_KEY`

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

**Backend-only test (no UI):**

```bash
cd backend && source .venv/bin/activate
python tests/test_generate_ws.py --sketch scripts/real_dashboard_sketch.jpg \
  --description "admin dashboard with sidebar navigation, header, and two stat cards"
```

---

## Tests

```bash
cd backend && pytest tests/ -v
```

Covers agent output schemas, pipeline fault isolation, retry logic, input validation, and WebSocket message structure.

---

## Known limitations

- **Latency** — End-to-end runs take roughly 5-11 seconds depending on sketch complexity, not sub-second
- **Vision provider** — Sketch parsing uses Claude vision today; Cerebras Gemma 4 vision support is reserved for when it becomes available
- **Sketch fidelity** — If your drawing uses generic labels the vision agent reads layout well, but downstream agents may invent content from your description rather than the ink. Write key labels legibly for literal text in the output
- **Vision Critic** — Runs as a follow-up `/visual-check` call triggered by the Studio UI, not inside the core WebSocket chain by default
- **Rate limits** — Heavy back-to-back runs can hit Cerebras 429s; the client retries once after 2s

---

## Demo artifacts

Validated demo runs including a real hand-drawn dashboard sketch live under `backend/scripts/battery_results/finalists/`. The hero sketch used for recording is `dashboard_real/`.