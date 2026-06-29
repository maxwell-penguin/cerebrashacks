# SketchStorm Studio

SketchStorm Studio turns a photo of a hand-drawn UI into a live React and Tailwind app. Upload a sketch, or snap a photo of a sticky-note wireframe, describe what you want, and six specialized AI agents collaborate in real time to build it: a vision agent reads your drawing, an architect plans the layout, code streams live into the editor, an auditor and accessibility agent harden the output, and a vision critic compares the rendered result against your original intent.

Built to be shown live: sketch in, working app out, in seconds.

## Try it now

[cerebrashacks.vercel.app](https://cerebrashacks.vercel.app)

## Why this fits each track

**Multiverse Agents.** Six agents, each with a distinct role and its own reasoning step: Vision Parser, Architect, Code Forge, Auditor, Accessibility, and Vision Critic. They run as a real pipeline, not a single prompt wearing different hats, each one streaming its own status and output so the collaboration is visible as it happens.

**Enterprise Impact.** After the app is generated, our visual QA system renders it server side with headless Chromium, captures a real screenshot, and has the Vision Critic agent compare it against the original design intent, flagging layout, UX, and accessibility issues. That same check can run as a CI gate on a pull request, catching visual regressions before a human ever has to look.

**People's Choice.** The premise is instantly understandable on camera: draw something, photograph it, watch six agents light up, watch code stream in, see the app appear. Our hero demo uses a real hand-drawn sketch on paper, not a clean digital mockup, because that's the actual product promise.

## How it works

A sketch photo goes to the Vision Parser, which hands a structured layout to the Architect, who hands a component plan to Code Forge, which streams real React and Tailwind code into the editor. The Auditor and Accessibility agents review and patch that code. Once the app renders, SimUI's Vision Critic takes a screenshot and checks it against the original intent.

## Under the hood

| Layer | Stack |
|---|---|
| Backend | FastAPI, WebSockets, Playwright for screenshot rendering |
| Vision (Vision Parser, Vision Critic) and Architect | Gemma 4 31B on Cerebras |
| Code Forge, Auditor, Accessibility | Cerebras gpt-oss-120b |
| Frontend | React, TypeScript, Vite, Tailwind, Monaco Editor |

Gemma 4 handles both halves of the multimodal story: it reads the sketch image and reasons in text about layout and architecture. The vision provider is swappable by design, which let us keep building while waiting on model access during the event.

The backend is built with production habits in mind: per call timeouts, automatic retries on rate limits, and per agent error isolation, so one slow or failed step never takes down the whole run. Every generation ends in a clean success or failure state, never a silent hang.

## Run it locally

**Backend**
```bash
cd backend

python -m venv .venv && source .venv/bin/activate

pip install -r requirements.txt

playwright install chromium

cp .env.example .env   # add your API keys

uvicorn main:app --reload --port 8000
```

**Frontend**
```bash
cd frontend

npm install

npm run dev
```

Open the local Vite URL, usually http://localhost:5173. The app connects to the backend over WebSocket automatically.

## Demo artifacts

A set of validated demo runs, including a real hand-drawn dashboard sketch, lives under `backend/scripts/battery_results/finalists/`. The hero sketch used for recording is `dashboard_real/`.

---

Built at the Cerebras and Google DeepMind Gemma 4 hackathon.
