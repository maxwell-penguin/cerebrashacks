# Contributing to SketchStorm Studio

## Dev environment

You need Python 3.11+ and Node 18+.

**Backend**

```bash
cd backend
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
pip install pytest pytest-asyncio     # test deps are not in requirements.txt
playwright install chromium           # needed by /visual-check and /auto-refine
cp .env.example .env                  # then fill in keys
./dev.sh                              # uvicorn main:app --reload on :8000
```

Environment variables (read from `backend/.env`):

| Variable | Needed | Default |
|----------|--------|---------|
| `CEREBRAS_API_KEY` | yes | none |
| `ANTHROPIC_API_KEY` | yes, unless `VISION_PROVIDER=cerebras` | none |
| `VISION_PROVIDER` | no | `anthropic` |
| `ANTHROPIC_VISION_MODEL` | no | `claude-sonnet-4-6` |
| `CEREBRAS_MODEL` | no | `gpt-oss-120b` (Code Forge, Auditor, A11y) |
| `CEREBRAS_VISION_MODEL` | no | `gemma-4-31b` (Architect, and vision if `VISION_PROVIDER=cerebras`) |
| `ARCHITECT_PROVIDER` | no | `gemma`; any other value runs the Architect on `CEREBRAS_MODEL` |
| `DB_PATH` | no | `backend/runs.db` |
| `AUTO_REFINE_MAX_ITERATIONS`, `LOG_LEVEL` | no | `3`, `INFO` |

**Frontend**

```bash
cd frontend
npm install
npm run dev                           # http://localhost:5173
npx tsc --noEmit -p tsconfig.app.json # type-check
```

Set `VITE_API_BASE_URL` if the backend is not on `http://localhost:8000`.

## Running the tests

The tests import backend modules directly, so run them from `backend/` with it on `PYTHONPATH`. CI does the same.

```bash
cd backend
PYTHONPATH=. pytest tests/ -v
```

All model calls are faked, so no API keys are needed. Use `tests/`, not bare `pytest`: `backend/scripts/smoke_test.py` needs a running server and is run separately (`python backend/scripts/smoke_test.py --base-url http://localhost:8000`).

## Running the eval set

`backend/scripts/run_eval.py` runs the real pipeline over a flat directory of jpg/png/svg sketches and writes `eval_results.csv`. It uses real API clients, so it costs money.

```bash
python backend/scripts/run_eval.py --dir path/to/sketches --limit 3   # try 3 first
python backend/scripts/run_eval.py --dir path/to/sketches --out results.csv
```

Defaults: `--dir backend/scripts/eval_sketches` (not committed), `--out eval_results.csv`. After the pipeline returns code, the script renders it with Playwright and runs the Critic on the screenshot. If that step fails, `visual_pass` is left empty.

**Apple Silicon and SVGs.** SVG sketches are converted to PNG with `cairosvg`, which needs the system cairo library. If you get "no library called cairo" on an Apple Silicon Mac, install it with Homebrew (`brew install cairo`) and point the dynamic loader at it:

```bash
export DYLD_LIBRARY_PATH=/opt/homebrew/lib:$DYLD_LIBRARY_PATH
```

jpg and png sketches do not need this.

## Pipeline architecture

A run starts when the browser opens a WebSocket to `/ws`. The server gives the connection a `run_id`, creates an in-memory `RunState` for it, and runs six agents in order. Vision Parser (Claude vision) reads the sketch into a JSON layout; Architect (Gemma by default) turns that into a component plan; Code Forge streams the React + Tailwind code; Auditor reviews it; A11y rewrites it with accessibility fixes; Critic judges a rendered screenshot against the design contract. The first three are blocking: they produce the artifact, so if one fails the run ends with `pipeline_complete success=false`. The last three are optional: they only review or polish code that already exists, so a failure is reported as an error event and the run still returns code. State flows forward through return values: the parsed layout feeds the Architect, layout and plan feed Code Forge, and the code feeds the Auditor, A11y and Critic. Every agent call is timed and logged, and each successful output is written to SQLite (`runs.db`) as it completes, along with the original request, so a client can reconnect with `resume_run` and the server will replay finished agents and run the rest. The in-memory `RunState` (which holds the Critic's issues for the chat panel) is dropped when the socket closes; the SQLite record is not. Auto-refine is a separate request: it takes the code and the Critic's issues, patches the code, re-renders and re-checks, up to three rounds, and streams one event per round. All Cerebras calls share one retry wrapper and one process-wide circuit breaker (`backend/cerebras_client.py`).

## Known limitations and TODOs

Known gaps are marked in the code with `TODO` comments:

```bash
grep -rn "TODO" backend/ frontend/src --include="*.py" --include="*.ts" --include="*.tsx"
```

In short: the Anthropic vision calls (Vision Parser, Critic) bypass the retry wrapper and circuit breaker; the frontend does not send `resume_run` yet; saved requests in `agent_outputs` (the `_request` row, which can include the uploaded image) are never cleaned up; `runs_in_progress` in `/metrics` can overcount because dropped connections stay "running"; rate limits and the circuit breaker are per process and reset on restart; and database writes in the pipeline are synchronous on the event loop. The README's "Known limitations" section has the user-facing list.
