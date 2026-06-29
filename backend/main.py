"""SketchStorm Studio backend — FastAPI + WebSockets."""

from __future__ import annotations

import asyncio
import base64
import json
import uuid
from contextlib import asynccontextmanager
from typing import Any

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, File, Form, UploadFile, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from cerebras_client import CerebrasClient, build_text_messages
from pipeline_config import RUN_ACCESSIBILITY_DEFAULT, RUN_AUDIT_DEFAULT
from render_screenshot import RenderScreenshotError, render_jsx_to_screenshot
from parsing import extract_code, extract_code_defensive, extract_json, extract_json_with_repair
from vision_client import call_vision_json
from agent_prompts import (
    ARCHITECT_CHAT_SYSTEM,
    AUTO_REFINE_SYSTEM,
    AUTO_REFINE_USER,
    CRITIC_CHAT_SYSTEM,
    DESIGN_ADVISOR_CHAT_SYSTEM,
    REFINE_REGION_SYSTEM,
    REFINE_REGION_USER,
    VISION_PARSER_SYSTEM,
    VISION_PARSER_USER,
)
from orchestrator import (
    get_latest_visual_issues,
    run_accessibility,
    run_auditor,
    run_sketchstorm_pipeline,
    run_visual_check,
    finalize_visual_check_result,
)
from schemas import (
    ArchitectResult,
    AuditRequest,
    AuditResult,
    AutoRefineRequest,
    AutoRefineResult,
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

_cerebras: CerebrasClient | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(
    title="SketchStorm Studio API",
    description="Multi-agent sketch → React pipeline on Cerebras Gemma 4",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_client() -> CerebrasClient:
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
    return {"status": "ok", "service": "sketchstorm-backend"}


@app.post("/generate", response_model=GenerateResponse)
async def generate(
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


@app.post("/auto-refine", response_model=AutoRefineResult)
async def auto_refine(body: AutoRefineRequest) -> AutoRefineResult:
    """
    Self-correcting loop that renders, critiques, and patches code up to 3 times.
    """
    import os
    import logging

    log = logging.getLogger(__name__)
    
    max_iterations_str = os.environ.get("AUTO_REFINE_MAX_ITERATIONS", "3")
    try:
        max_iterations = int(max_iterations_str)
    except ValueError:
        max_iterations = 3
        
    client = get_client()
    
    current_code = body.code
    issues_per_iteration = []
    iterations_run = 0
    stopped_reason = "max_iterations"
    
    for i in range(max_iterations):
        iterations_run += 1
        
        # 1. Render screenshot
        try:
            screenshot_bytes = await asyncio.to_thread(render_jsx_to_screenshot, current_code)
        except Exception as exc:
            log.warning("Auto-refine render failure on iteration %d: %s", iterations_run, exc)
            stopped_reason = "error"
            break
            
        # 2. Run visual check
        try:
            check_res = await run_visual_check(
                client,
                screenshot_bytes,
                body.design_contract,
                body.description,
                "image/png",
                emit=None,
            )
        except Exception as exc:
            log.warning("Auto-refine QA call failure on iteration %d: %s", iterations_run, exc)
            stopped_reason = "error"
            break
            
        issues_per_iteration.append(check_res.issues)
        
        # 3. Check if passed without serious issues
        has_serious_issues = any(issue.severity in ("critical", "major") for issue in check_res.issues)
        if check_res.passed and not has_serious_issues:
            stopped_reason = "passed"
            break
            
        # If this is the last iteration, don't refine again
        if iterations_run == max_iterations:
            break
            
        # 4. Refine/patch code
        try:
            issues_text = "\n".join([
                f"- [{issue.category}] {issue.severity}: {issue.description} (Suggestion: {issue.suggestion})"
                for issue in check_res.issues
            ])
            
            user_text = AUTO_REFINE_USER.format(
                code=current_code,
                issues=issues_text,
                design_contract=body.design_contract or "Match the original sketch layout, spacing, and labels.",
                description=body.description or "Hand-drawn UI sketch converted to React."
            )
            
            messages = build_text_messages(AUTO_REFINE_SYSTEM, user_text)
            
            # Use JSON call timeout (20.0s) or vision call timeout (25.0s)
            raw_response = await asyncio.wait_for(
                client.acall(messages, max_tokens=8192, temperature=0.2),
                timeout=25.0
            )
            
            patched_code = extract_code_defensive(raw_response)
            current_code = patched_code
        except Exception as exc:
            log.warning("Auto-refine code refinement call failure on iteration %d: %s", iterations_run, exc)
            stopped_reason = "error"
            # Stop loop and keep the current_code from before this failed iteration
            break
            
    return AutoRefineResult(
        final_code=current_code,
        iterations_run=iterations_run,
        stopped_reason=stopped_reason,
        issues_per_iteration=issues_per_iteration,
    )


@app.post("/refine-region", response_model=RefineRegionResponse)
async def refine_region(body: RefineRegionRequest) -> RefineRegionResponse:
    """
    Refine a specific region of the React component based on user input.
    """
    import difflib
    import logging

    log = logging.getLogger(__name__)
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
        log.error("Region refinement failed: %s", exc)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to refine region: {str(exc)}"
        )


@app.post("/chat", response_model=ChatResponse)
async def chat(body: ChatRequest) -> ChatResponse:
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
        issues_list = get_latest_visual_issues()
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
    """
  Primary streaming interface. Client sends:
    {"type": "generate", "image_base64": "...", "mime_type": "image/jpeg",
     "description": "...", "run_audit": false, "run_accessibility": false,
     "screenshot_base64": "...", "design_contract": "..."}

  Server streams agent_status, agent_token, agent_output, final_code, tps, pipeline_complete.
    """
    await ws.accept()
    client = get_client()

    try:
        while True:
            payload = await ws.receive_json()
            msg_type = payload.get("type")

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
            )

    except WebSocketDisconnect:
        pass
    except Exception as exc:
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
