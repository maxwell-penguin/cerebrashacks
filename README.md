![CI](https://github.com/maxwell-penguin/cerebrashacks/actions/workflows/ci.yml/badge.svg)

# SketchStorm Studio

SketchStorm Studio converts a photo of a hand-drawn UI sketch into a working React and Tailwind app in real time. Upload a sketch or snap a sticky-note wireframe, describe what you want, and six specialized AI agents collaborate to build it: a vision agent reads your drawing, an architect plans the layout, code streams live into a Monaco editor, an auditor and accessibility agent harden the output, and a vision critic compares a rendered screenshot against your original intent.

Built at the **Cerebras x Google DeepMind Gemma 4 Hackathon**. Live at [cerebrashacks.vercel.app](https://cerebrashacks.vercel.app).

  Video Demo: https://x.com/wobblbobby/status/2071649115717447968?s=20

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
| Backend | FastAPI, WebSockets, Playwright, SQLite (`runs.db`), slowapi |
| Text agents | Cerebras `gemma-4-31b` (Architect, default) and `gpt-oss-120b` (Code Forge, Auditor, Accessibility; set by `CEREBRAS_MODEL`) |
| Vision agents | Anthropic Claude (Vision Parser, Vision Critic); `VISION_PROVIDER=cerebras` switches them to Gemma |
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, Monaco Editor; preview in a sandboxed iframe |

---

## Reliability

The backend is built with production habits in mind. See `cerebras_client.py`, `orchestrator.py`, `db.py`, and `parsing.py`:

The same retry amplification pattern was found and fixed in 
grafana/loki PR #24057 — the same fix is applied here.

**Blocking vs optional agents.** Vision Parser, Architect and Code Forge are blocking: they produce the artifact, so if one fails the run ends with `pipeline_complete success=false` (Code Forge's partial code is still sent). Auditor, A11y and Critic are optional: they only review or polish code that already exists, so a failure is reported as an error event and the run still returns code. `pipeline_complete` fires exactly once per run either way.

**Timeouts, retries and jitter.**
- Per-call timeouts: 20s for JSON calls, 25s for streams and vision calls, 8s inter-token stall detection on streams.
- Timeouts and stream stalls get one immediate retry.
- Rate limits (429) get up to 3 attempts with a 10s wait. The wait is `base + uniform(0, 0.3 * base)`, so concurrent runs do not retry in lockstep. The timeout retry has no wait, so it has no jitter.
- JSON repair for structured agent outputs so malformed responses degrade gracefully.

**Circuit breaker** (`CircuitBreaker` in `cerebras_client.py`, one per process, shared by every Cerebras call).
- `CLOSED`: calls pass through. 5 consecutive failures (counted after retries are exhausted) trip it.
- `OPEN`: calls are rejected immediately with a `PipelineAgentError`, without touching the API. After a 30s recovery timeout the next call moves it to `HALF_OPEN`.
- `HALF_OPEN`: one probe call is allowed. Success closes the breaker, failure reopens it; other callers are rejected while the probe is in flight.
- Calls already in flight are not cancelled. A run that reaches a Cerebras agent while the breaker is open fails at that agent: a blocking agent ends the run, an optional agent is skipped.

**Per-run persistence and resume.** Each run is stored in `runs.db` (SQLite, path from `DB_PATH`): its status, the original request, and every agent's output as that agent completes. Because the data is on disk, runs survive server restarts. A client can reconnect and send `{"type": "resume_run", "run_id": "..."}`; the server replays the finished agents' outputs and runs the rest, starting at the first incomplete agent. Replay re-sends outputs, not the token stream.

Full API and event shapes: [`backend/API.md`](backend/API.md).

---

## Observability

**`GET /metrics`** returns JSON computed from SQLite on each request, not from in-memory counters: `runs_total`, `runs_complete`, `runs_failed`, `runs_in_progress`, `agent_success_counts`, `agent_failure_counts`, `agent_p50_latency_ms`, `agent_p95_latency_ms`, plus `circuit_breaker_state` read from the live breaker. Latency percentiles use successful attempts only.

**`GET /health`** returns `status` (`ok`, or `degraded` if the database check fails), `db` and `circuit_breaker`.

**Structured logs.** `jsonlog.py` writes one JSON object per line to stdout using stdlib `logging`. Every line has `timestamp` (ISO 8601, UTC), `level` and `event`. `run_id` and `agent_name` are added whenever the line is logged inside a run or an agent call, and `duration_ms` is added on `agent_complete`, `agent_failed` and `pipeline_*` events, along with event-specific fields such as `error`. Events: `websocket_connected`, `websocket_disconnected`, `agent_started`, `agent_complete`, `agent_failed`, `pipeline_complete`, `pipeline_failed`. Log lines from libraries are wrapped as `event: "log"` with a `message` field. `LOG_LEVEL` sets the level (default `INFO`).

---

## Rate limiting

Limits are per client IP, enforced with slowapi (the WebSocket limit is checked by hand on the same limiter):

| Endpoint | Limit |
|----------|-------|
| `POST /generate`, `POST /auto-refine` | 10 requests/min |
| `POST /chat` | 30 requests/min |
| `GET /metrics` | 60 requests/min |
| WebSocket `/ws` | 5 connections/min |

Exceeding a limit returns `429` with `{"error": "rate_limit_exceeded", "retry_after_seconds": N}` and a `Retry-After` header. A rejected WebSocket gets the same JSON body, then is closed with code 1008. Behind a reverse proxy all clients share one IP unless uvicorn is set to trust forwarded headers.

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

Open the Vite URL (default `http://localhost:5173`). The app connects to `ws://localhost:8000/ws`; set `VITE_API_BASE_URL` to point it elsewhere.

**Docker**

```bash
cp backend/.env.example backend/.env   # fill in API keys
docker compose up --build
```

This starts the backend on `:8000` (non-root user, `init_db()` before uvicorn, `runs.db` on the `sketchstorm-data` volume, `/health` checked every 30s) and the frontend dev server on `:5173`. The image has not been tested in CI yet.

---

## Tests

64 tests, all with faked model calls (no API keys needed):

```bash
cd backend
PYTHONPATH=. pytest tests/ -v
```

`pytest` and `pytest-asyncio` are not in `requirements.txt`; install them first. They cover agent output schemas, pipeline fault isolation with a fake client (blocking and optional failures, retry on a transient error), the circuit breaker, SQLite persistence and resume, auto-refine streaming, `/metrics`, and rate limiting.

The smoke tests in `backend/scripts/smoke_test.py` call a running server and are not part of the suite. Start the backend, then run them separately: `python backend/scripts/smoke_test.py --base-url http://localhost:8000`.

---

## Known limitations

- **Vision provider** — Sketch parsing uses Claude vision today; Cerebras Gemma 4 vision support is reserved for when it becomes available
- **Sketch fidelity** — If your drawing uses generic labels the vision agent reads layout well, but downstream agents may invent content from your description rather than the ink. Write key labels legibly for literal text in the output
- **Vision Critic** — Runs as a follow-up `/visual-check` call triggered by the Studio UI, not inside the core WebSocket chain by default
- **Rate limits** — Heavy back-to-back runs can hit Cerebras 429s; the client retries up to 3 times, waiting about 10s each time
- **Anthropic vision calls bypass the retry wrapper and circuit breaker** — Vision Parser and Critic only have the 25s timeout
- **Resume is API-only** — The frontend doesn't send `resume_run` yet; resume works at the API level but the UI always starts a new run
- **`runs_in_progress` can overcount** — Dropped connections stay "running" in the database, which is what makes them resumable
- **Per-process state** — Rate limits and the circuit breaker live in memory and reset on restart

---

## Demo artifacts

Validated demo runs including a real hand-drawn dashboard sketch live under `backend/scripts/battery_results/finalists/`. The hero sketch used for recording is `dashboard_real/`.
