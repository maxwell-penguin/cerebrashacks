"""SketchStorm Studio backend — FastAPI + WebSockets."""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import math
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from limits import parse as parse_limit
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from cerebras_client import CerebrasClient, build_text_messages
from pipeline_config import RUN_ACCESSIBILITY_DEFAULT, RUN_AUDIT_DEFAULT
from render_screenshot import RenderScreenshotError, render_jsx_to_screenshot
from parsing import extract_code, extract_code_defensive, extract_json, extract_json_with_repair
from vision_client import call_vision_json
from agent_prompts import (
    ARCHITECT_CHAT_SYSTEM,
    CRITIC_CHAT_SYSTEM,
    DESIGN_ADVISOR_CHAT_SYSTEM,
    REFINE_REGION_SYSTEM,
    REFINE_REGION_USER,
    VISION_PARSER_SYSTEM,
    VISION_PARSER_USER,
)
import db
import cerebras_client
from jsonlog import configure_logging, log_event, run_id_var
from orchestrator import (
    RunState,
    _runs,
    get_latest_visual_issues,
    run_accessibility,
    run_auditor,
    run_sketchstorm_pipeline,
    run_auto_refine,
    run_visual_check,
    finalize_visual_check_result,
)
from schemas import (
    ArchitectResult,
    AuditRequest,
    AuditResult,
    AutoRefineRequest,
    ChatRequest,
    ChatResponse,
    DiffStats,
    GenerateResponse,
    RefineRegionRequest,
    RefineRegionResponse,
    VisionParseResult,
    VisualCheckRequest,
    VisualCheckResult,
)

configure_logging()
log = logging.getLogger(__name__)

# In-memory, per process.
# TODO: rate limits are per-process and reset on restart, so they are not shared across replicas;
# use Limiter(storage_uri="redis://...") before running more than one.
limiter = Limiter(key_func=get_remote_address)
WS_LIMIT = parse_limit("5/minute")

_cerebras: CerebrasClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """App lifespan: create the SQLite schema at startup (init_db is idempotent)."""
    db.init_db()
    yield


app = FastAPI(
    title="SketchStorm Studio API",
    description="Multi-agent sketch → React pipeline on Cerebras Gemma 4",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter


def _retry_after(limit_item: Any, *key: str) -> int:
    reset_at, _ = limiter.limiter.get_window_stats(limit_item, *key)
    return max(1, math.ceil(reset_at - time.time()))


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    """Turn a slowapi RateLimitExceeded into a 429 JSON body {"error", "retry_after_seconds"} plus a Retry-After header."""
    limit_item, key = request.state.view_rate_limit
    retry = _retry_after(limit_item, *key)
    return JSONResponse(
        {"error": "rate_limit_exceeded", "retry_after_seconds": retry},
        status_code=429,
        headers={"Retry-After": str(retry)},
    )


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_client() -> CerebrasClient:
    """Return the process-wide `CerebrasClient`, creating it on first use (so the app can import without an API key)."""
    global _cerebras
    if _cerebras is None:
        _cerebras = CerebrasClient()
    return _cerebras


def _payload_bool(payload: dict[str, Any], key: str, default: bool) -> bool:
    if key not in payload:
        return default
    return bool(payload[key])


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness/readiness probe.

    Returns:
        {"status": "ok"|"degraded", "service", "db": "ok"|"error", "circuit_breaker": "CLOSED"|"OPEN"|"HALF_OPEN"}.
        "degraded" means the SQLite check failed; the response is still HTTP 200.
    """
    try:
        with db._connect() as conn:
            conn.execute("SELECT 1")
        db_state = "ok"
    except Exception:
        db_state = "error"
    return {
        "status": "ok" if db_state == "ok" else "degraded",
        "service": "sketchstorm-backend",
        "db": db_state,
        "circuit_breaker": cerebras_client._breaker.state.upper(),
    }


@app.get("/metrics")
@limiter.limit("60/minute")
async def metrics(request: Request) -> dict[str, Any]:
    """Return run counts, per-agent success/failure counts and p50/p95 latency from SQLite, plus the live circuit-breaker state. Limited to 60/min per IP."""
    out = db.compute_metrics()
    out["circuit_breaker_state"] = cerebras_client._breaker.state.upper()
    return out


@app.post("/generate", response_model=GenerateResponse)
@limiter.limit("10/minute")
async def generate(
    request: Request,
    image: UploadFile | None = File(None),
    description: str = Form(""),
    run_audit: bool = Form(RUN_AUDIT_DEFAULT),
    run_accessibility: bool = Form(RUN_ACCESSIBILITY_DEFAULT),
    run_visual_check: bool = Form(False),
    screenshot: UploadFile | None = File(None),
    design_contract: str = Form(""),
) -> GenerateResponse:
    """Synchronous generate (blocks until done). Use WebSocket /ws for streaming."""
    client = get_client()
    image_bytes = None
    mime = ""
    if image is not None:
        image_bytes = await image.read()
        mime = image.content_type or "image/jpeg"

    if not image_bytes and not description.strip():
        raise HTTPException(status_code=400, detail="Either image or a non-empty description must be provided.")

    screenshot_bytes = None
    screenshot_mime = "image/png"
    if run_visual_check and screenshot:
        screenshot_bytes = await screenshot.read()
        screenshot_mime = screenshot.content_type or "image/png"

    result_holder: dict[str, Any] = {}

    async def collect(msg: dict[str, Any]) -> None:
        if msg.get("type") == "pipeline_complete":
            result_holder.update(msg)

    await run_sketchstorm_pipeline(
        client,
        image_bytes,
        description,
        mime,
        collect,
        run_audit=run_audit,
        run_accessibility_pass=run_accessibility,
        screenshot_bytes=screenshot_bytes,
        screenshot_mime=screenshot_mime,
        design_contract=design_contract,
    )

    vision_data = result_holder.get("vision")
    arch_data = result_holder.get("architecture")
    audit_data = result_holder.get("audit")
    visual_data = result_holder.get("visual_check")

    return GenerateResponse(
        session_id=str(uuid.uuid4()),
        vision=VisionParseResult.model_validate(vision_data) if vision_data else None,
        architecture=ArchitectResult.model_validate(arch_data) if arch_data else None,
        code=result_holder.get("code", ""),
        accessibility_code=result_holder.get("accessibility_code"),
        audit=AuditResult.model_validate(audit_data) if audit_data else None,
        visual_check=VisualCheckResult.model_validate(visual_data) if visual_data else None,
    )


@app.post("/audit", response_model=AuditResult)
async def audit(body: AuditRequest) -> AuditResult:
    """Run the Auditor on posted code and return its `AuditResult`."""
    client = get_client()

    async def noop(_: dict[str, Any]) -> None:
        pass

    return await run_auditor(client, body.code, noop)


@app.post("/audit/full")
async def audit_full(body: AuditRequest) -> dict[str, Any]:
    """Run auditor and optionally accessibility pass; returns code + issues."""
    client = get_client()

    async def noop(_: dict[str, Any]) -> None:
        pass

    audit_result = await run_auditor(client, body.code, noop)
    code = body.code
    if body.run_accessibility:
        code = await run_accessibility(client, body.code, noop)
    return {"audit": audit_result.model_dump(), "code": code}


@app.post("/visual-check", response_model=VisualCheckResult)
async def visual_check(body: VisualCheckRequest) -> VisualCheckResult:
    """
    SimUI visual QA. Pass `code` to render a screenshot server-side (Playwright),
    or `screenshot_base64` to use a client-captured image.
    """
    client = get_client()

    screenshot_bytes: bytes | None = None
    mime = "image/png"

    if body.code.strip():
        try:
            screenshot_bytes = await asyncio.to_thread(render_jsx_to_screenshot, body.code)
        except Exception as exc:
            return finalize_visual_check_result(
                False,
                [],
                summary=f"Screenshot render failed: {exc}",
            )
    elif body.screenshot_base64:
        raw = body.screenshot_base64
        if "," in raw:
            raw = raw.split(",", 1)[1]
        screenshot_bytes = base64.b64decode(raw)

    if not screenshot_bytes:
        return finalize_visual_check_result(
            False,
            [],
            summary="No code or screenshot provided. Pass `code` or `screenshot_base64`.",
        )

    return await run_visual_check(
        client,
        screenshot_bytes,
        body.design_contract,
        body.description,
        mime,
        emit=None,
    )


@app.post("/auto-refine")
@limiter.limit("10/minute")
async def auto_refine(request: Request, body: AutoRefineRequest) -> StreamingResponse:
    """Streams NDJSON: one refine_iteration per round, then refine_complete."""
    try:
        max_iterations = int(os.environ.get("AUTO_REFINE_MAX_ITERATIONS", "3"))
    except ValueError:
        max_iterations = 3

    async def lines():
        async for event in run_auto_refine(
            get_client(),
            body.code,
            [i.model_dump() for i in body.visual_issues],
            design_contract=body.design_contract,
            description=body.description,
            run_id=body.run_id,
            max_iterations=max_iterations,
        ):
            yield json.dumps(event) + "\n"

    return StreamingResponse(lines(), media_type="application/x-ndjson")


@app.post("/refine-region", response_model=RefineRegionResponse)
async def refine_region(body: RefineRegionRequest) -> RefineRegionResponse:
    """
    Refine a specific region of the React component based on user input.
    """
    import difflib

    client = get_client()

    try:
        # --- Sketch input: run Vision Parser if a drawing was provided ---
        sketch_description = ""
        if body.sketch_image_base64.strip():
            b64 = body.sketch_image_base64
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            image_bytes = base64.b64decode(b64)

            raw_vision = await asyncio.wait_for(
                asyncio.to_thread(
                    call_vision_json,
                    VISION_PARSER_SYSTEM,
                    VISION_PARSER_USER.format(description_extra=""),
                    image_bytes,
                    "image/png",
                ),
                timeout=25.0,
            )
            vision_data = extract_json(raw_vision)
            vision = VisionParseResult.model_validate(vision_data)

            if vision.components:
                comp_lines = []
                for c in vision.components:
                    cx = c.x + c.width / 2
                    cy = c.y + c.height / 2
                    horiz = "right" if cx > 0.66 else ("left" if cx < 0.33 else "center")
                    vert = "bottom" if cy > 0.66 else ("top" if cy < 0.33 else "middle")
                    pos = f"{vert}-{horiz}" if vert != "middle" or horiz != "center" else "center"
                    label = f' labeled "{c.label}"' if c.label else ""
                    comp_lines.append(f"a {c.type}{label} at {pos}")
                sketch_description = "The user drew: " + ", ".join(comp_lines) + "."

        # --- Build the combined refinement instruction ---
        text_req = body.refinement_request.strip()
        if text_req and sketch_description:
            combined_request = f"{text_req}\n\nVisual sketch context: {sketch_description}"
        elif sketch_description:
            combined_request = sketch_description
        else:
            combined_request = text_req

        user_text = REFINE_REGION_USER.format(
            code=body.code,
            region_description=body.region_description,
            refinement_request=combined_request,
        )
        messages = build_text_messages(REFINE_REGION_SYSTEM, user_text)

        # Call Code Forge with a timeout of 25.0 seconds
        raw_response = await asyncio.wait_for(
            client.acall(messages, max_tokens=8192, temperature=0.2),
            timeout=25.0
        )

        patched_code = extract_code_defensive(raw_response)

        # Compute diff statistics using difflib SequenceMatcher
        original_lines = body.code.splitlines()
        patched_lines = patched_code.splitlines()

        matcher = difflib.SequenceMatcher(None, original_lines, patched_lines)
        deletions = 0
        insertions = 0
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'replace':
                deletions += (i2 - i1)
                insertions += (j2 - j1)
            elif tag == 'delete':
                deletions += (i2 - i1)
            elif tag == 'insert':
                insertions += (j2 - j1)

        lines_changed = deletions + insertions
        lines_total = len(original_lines)
        if lines_total == 0:
            lines_total = 1

        change_ratio = lines_changed / lines_total

        warning = None
        if change_ratio > 0.4:
            warning = "This change affected more of the code than expected — review before keeping it."

        input_summary = body.refinement_request.strip() or sketch_description
        changed_regions_summary = f"Refined the {body.region_description}: {input_summary}"

        return RefineRegionResponse(
            patched_code=patched_code,
            changed_regions_summary=changed_regions_summary,
            diff_stats=DiffStats(
                lines_changed=lines_changed,
                lines_total=lines_total,
                change_ratio=change_ratio,
            ),
            warning=warning,
        )

    except Exception as exc:
        log_event(log, "refine_region_failed", logging.ERROR, error=str(exc))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refine region: {str(exc)}"
        )


@app.post("/chat", response_model=ChatResponse)
@limiter.limit("30/minute")
async def chat(request: Request, body: ChatRequest) -> ChatResponse:
    """
    Agent chat/co-pilot endpoint.
    Handles messages to specific agents and returns text reply + structured changes.
    """
    import json
    client = get_client()

    # 1. Determine system prompt and construct user message based on selected agent
    if body.agent == "architect":
        system_prompt = ARCHITECT_CHAT_SYSTEM
        user_text = (
            f"User context (JSON):\n"
            f"Route: {body.context.route}\n"
            f"Layout Summary: {body.context.layout_summary}\n"
            f"Code Summary: {body.context.code_summary}\n\n"
            f"User message:\n{body.message}"
        )
    elif body.agent == "design_advisor":
        system_prompt = DESIGN_ADVISOR_CHAT_SYSTEM
        user_text = (
            f"User context (JSON):\n"
            f"Route: {body.context.route}\n"
            f"Layout Summary: {body.context.layout_summary}\n"
            f"Code Summary: {body.context.code_summary}\n\n"
            f"User message:\n{body.message}"
        )
    elif body.agent == "critic":
        system_prompt = CRITIC_CHAT_SYSTEM
        issues_list = get_latest_visual_issues(body.run_id)
        issues_str = json.dumps(issues_list, indent=2)
        user_text = (
            f"Known issues (JSON):\n{issues_str}\n\n"
            f"User message:\n{body.message}"
        )
    else:
        raise ValueError(f"Unknown agent: {body.agent}")

    # 2. Query the LLM
    messages = build_text_messages(system_prompt, user_text)
    raw = await client.acall(messages, max_tokens=2048, temperature=0.1)

    # 3. Parse and repair JSON from response
    try:
        data = await extract_json_with_repair(raw, client, debug_agent=body.agent)
        reply = data.get("reply", "Here are my suggestions.")
        suggested_changes = data.get("suggested_changes", None)
    except Exception as exc:
        reply = f"Sorry, I had trouble parsing the suggestions: {exc}. Here is the raw message: {raw}"
        suggested_changes = None

    return ChatResponse(reply=reply, suggested_changes=suggested_changes)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket) -> None:
    """Streaming interface: run the agent pipeline over a WebSocket.

    Each connection gets a UUID `run_id` (sent first as {"type": "run_started", "run_id"}) and an
    in-memory `RunState`, which is removed when the socket closes; the SQLite record stays.

    Client messages (one run per message; the socket can be reused):
      * {"type": "generate" | "new_run", "image_base64", "mime_type", "description", "run_audit",
        "run_accessibility", "screenshot_base64", "design_contract"} starts a run. Either an image or
        a non-empty description is required. `new_run` is an alias for `generate`.
      * {"type": "resume_run", "run_id"} loads that run from SQLite, replays its finished agents, and
        runs the rest with the saved request. An unknown run_id gets an error message.

    Server events: run_started, agent_status, agent_token, agent_output, final_code, tps, error,
    pipeline_complete (see schemas.WS*). Invalid input gets an error event, and for bad images also a
    pipeline_complete(success=False), without closing the socket.

    Rate limit: 5 connections per minute per IP. Over the limit the server accepts, sends
    {"error": "rate_limit_exceeded", "retry_after_seconds": N}, and closes with code 1008.
    """
    await ws.accept()
    ip = ws.client.host if ws.client else "unknown"
    if not limiter.limiter.hit(WS_LIMIT, "ws", ip):  # slowapi decorators don't cover websockets
        await ws.send_json({"error": "rate_limit_exceeded", "retry_after_seconds": _retry_after(WS_LIMIT, "ws", ip)})
        # 1008 (policy violation) is the standard "rejected by policy" close code; clients can tell it apart
        # from a network drop (1006) and avoid a reconnect loop.
        await ws.close(code=1008)
        return
    client = get_client()
    run_id = str(uuid.uuid4())
    run_id_var.set(run_id)  # per-connection task context, so every log line below carries it
    log_event(log, "websocket_connected")
    _runs[run_id] = RunState(run_id=run_id)
    await ws.send_json({"type": "run_started", "run_id": run_id})

    try:
        while True:
            payload = await ws.receive_json()
            msg_type = payload.get("type")
            completed: dict[str, Any] | None = None

            # TODO: the frontend never sends resume_run, so resume is API-only; the UI always starts a new run.
            if msg_type == "resume_run":
                saved = db.load_run(str(payload.get("run_id", "")))
                if saved is None or "_request" not in saved["agent_outputs"]:
                    await ws.send_json({"type": "error", "message": "Unknown run_id; start a new run."})
                    continue
                # Adopt the saved run's identity; replay + skip its finished agents, redo the rest.
                _runs.pop(run_id, None)
                run_id = saved["run_id"]
                run_id_var.set(run_id)
                _runs[run_id] = RunState(run_id=run_id)
                await ws.send_json({"type": "run_started", "run_id": run_id})
                completed = saved["agent_outputs"]
                payload = completed.pop("_request")
                msg_type = "generate"
            elif msg_type == "new_run":  # alias; "generate" is what the current frontend sends
                msg_type = "generate"

            if msg_type != "generate":
                await ws.send_json({"type": "error", "message": f"Unknown message type: {msg_type}"})
                continue

            image_b64 = payload.get("image_base64")
            description = payload.get("description", "").strip()

            has_image = image_b64 is not None and image_b64 != ""

            if not has_image and not description:
                await ws.send_json({"type": "error", "message": "Either image_base64 or a non-empty description must be provided."})
                continue

            image_bytes = None
            mime = ""
            if has_image:
                if "," in image_b64:
                    image_b64 = image_b64.split(",", 1)[1]
                if image_b64:
                    try:
                        image_bytes = base64.b64decode(image_b64)
                    except Exception as exc:
                        await ws.send_json({"type": "error", "message": "That doesn't look like a valid image file."})
                        await ws.send_json({
                            "type": "pipeline_complete",
                            "success": False,
                            "code": "",
                            "message": "That doesn't look like a valid image file."
                        })
                        continue

                    if len(image_bytes) > 10 * 1024 * 1024:
                        await ws.send_json({"type": "error", "message": "Image file size exceeds the 10MB limit."})
                        await ws.send_json({
                            "type": "pipeline_complete",
                            "success": False,
                            "code": "",
                            "message": "Image file size exceeds the 10MB limit."
                        })
                        continue

                    from io import BytesIO
                    from PIL import Image
                    try:
                        with Image.open(BytesIO(image_bytes)) as img:
                            img.load()  # force full decode — verify() is too shallow
                    except Exception:
                        await ws.send_json({"type": "error", "message": "That doesn't look like a valid image file."})
                        await ws.send_json({
                            "type": "pipeline_complete",
                            "success": False,
                            "code": "",
                            "message": "That doesn't look like a valid image file."
                        })
                        continue

                mime = payload.get("mime_type", "image/jpeg")

            screenshot_bytes = None
            screenshot_mime = "image/png"
            screenshot_b64 = payload.get("screenshot_base64", "")
            if screenshot_b64:
                if "," in screenshot_b64:
                    screenshot_b64 = screenshot_b64.split(",", 1)[1]
                screenshot_bytes = base64.b64decode(screenshot_b64)
                screenshot_mime = payload.get("screenshot_mime_type", "image/png")

            async def emit(msg: dict[str, Any]) -> None:
                await ws.send_json(msg)

            _runs[run_id].status = "running"
            if completed is None:
                db.save_run(run_id, "pending")
                # "_request" is a pseudo-agent row: the original payload is stored in agent_outputs (no schema change) so a
                # resumed run can re-run its remaining agents with the same inputs.
                db.save_agent_output(run_id, "_request", payload)
            await run_sketchstorm_pipeline(
                client,
                image_bytes,
                description,
                mime,
                emit,
                run_audit=_payload_bool(payload, "run_audit", RUN_AUDIT_DEFAULT),
                run_accessibility_pass=_payload_bool(
                    payload, "run_accessibility", RUN_ACCESSIBILITY_DEFAULT
                ),
                screenshot_bytes=screenshot_bytes,
                screenshot_mime=screenshot_mime,
                design_contract=payload.get("design_contract", ""),
                run_id=run_id,
                completed=completed,
            )
            _runs[run_id].status = "complete"

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log_event(log, "websocket_error", logging.ERROR, error=str(exc), error_type=type(exc).__name__)
        _runs[run_id].status = "failed"
        try:
            await ws.send_json({"type": "error", "message": str(exc)})
            await ws.send_json(
                {
                    "type": "pipeline_complete",
                    "success": False,
                    "code": "",
                    "issues": [],
                    "vision": None,
                    "architecture": None,
                }
            )
        except Exception:
            pass
    finally:
        log_event(log, "websocket_disconnected")
        _runs.pop(run_id, None)
