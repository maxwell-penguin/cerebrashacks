"""SketchStorm agent pipeline orchestration."""

from __future__ import annotations

import json
import asyncio
import logging
import time
from contextlib import asynccontextmanager
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from collections.abc import AsyncIterator
from typing import Any, Literal

import db
from jsonlog import agent_var, log_event, run_id_var
from agent_prompts import (
    AUTO_REFINE_SYSTEM,
    AUTO_REFINE_USER,
    ACCESSIBILITY_SYSTEM,
    ACCESSIBILITY_USER,
    ARCHITECT_SYSTEM,
    ARCHITECT_USER,
    ARCHITECT_USER_TEXT_ONLY,
    AUDITOR_SYSTEM,
    AUDITOR_USER,
    CODE_FORGE_SYSTEM,
    CODE_FORGE_USER,
    CODE_FORGE_USER_TEXT_ONLY,
    VISION_CRITIC_SYSTEM,
    VISION_CRITIC_USER,
    VISION_PARSER_SYSTEM,
    VISION_PARSER_USER,
)
from cerebras_client import VISION_CALL_TIMEOUT, CerebrasClient, build_text_messages
from parsing import extract_code, extract_code_defensive, extract_json, extract_json_with_repair
from render_screenshot import render_jsx_to_screenshot
from vision_client import call_vision_json
from schemas import (
    ArchitectResult,
    AuditResult,
    NormalizedIssue,
    VisionParseResult,
    VisualCheckResult,
    VisualIssue,
)

EmitFn = Callable[[dict[str, Any]], Awaitable[None]]

_SEVERITY_MAP: dict[str, Literal["error", "warn", "info"]] = {"error": "error", "warning": "warn", "info": "info"}


def normalize_auditor_issues(audit: AuditResult | None) -> list[NormalizedIssue]:
    if not audit:
        return []
    return [
        NormalizedIssue(
            agent="Auditor",
            severity=_SEVERITY_MAP[issue.severity] if issue.severity in _SEVERITY_MAP else "warn",
            description=issue.message,
            code_region=issue.line_hint,
        )
        for issue in audit.issues
    ]


def derive_visual_check_status(passed: bool, issues: list[VisualIssue]) -> Literal["pass", "pass_with_warnings", "fail"]:
    if passed and not issues:
        return "pass"
    if passed and issues:
        return "pass_with_warnings"
    return "fail"


def derive_visual_check_summary(
    passed: bool,
    issues: list[VisualIssue],
    fallback: str = "",
) -> str:
    if fallback.strip():
        return fallback
    n = len(issues)
    if passed and n == 0:
        return "Passed — no issues noted."
    if passed:
        suffix = "s" if n != 1 else ""
        return f"Passed — {n} minor issue{suffix} noted."
    if n:
        suffix = "s" if n != 1 else ""
        return f"Failed — {n} issue{suffix} found."
    return "Failed — visual check did not pass."


def finalize_visual_check_result(
    passed: bool,
    issues: list[VisualIssue],
    summary: str = "",
) -> VisualCheckResult:
    return VisualCheckResult(
        passed=passed,
        status=derive_visual_check_status(passed, issues),
        issues=issues,
        summary=derive_visual_check_summary(passed, issues, summary),
    )


@dataclass
class RunState:
    run_id: str
    visual_issues: list[str] = field(default_factory=list)
    agent_outputs: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"  # pending | running | complete | failed


_runs: dict[str, RunState] = {}


def get_latest_visual_issues(run_id: str | None) -> list[dict[str, Any]]:
    run = _runs.get(run_id) if run_id else None
    return run.visual_issues if run else []


log = logging.getLogger(__name__)


class PipelineAgentError(Exception):
    def __init__(
        self,
        agent: str,
        message: str,
        *,
        partial_code: str | None = None,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(message)
        self.agent = agent
        self.partial_code = partial_code
        self.cause = cause


async def _emit_status(
    emit: EmitFn,
    agent: str,
    status: str,
    message: str = "",
) -> None:
    await emit({"type": "agent_status", "agent": agent, "status": status, "message": message})


async def _emit_agent_failure(
    emit: EmitFn,
    agent: str,
    exc: BaseException,
    *,
    partial_code: str | None = None,
) -> None:
    message = str(exc)
    await _emit_status(emit, agent, "error", message)
    await emit({"type": "error", "agent": agent, "message": message})
    if partial_code:
        await emit({"type": "final_code", "code": partial_code})


async def _emit_pipeline_complete(
    emit: EmitFn,
    *,
    success: bool,
    code: str = "",
    accessibility_code: str | None = None,
    vision: VisionParseResult | None = None,
    architecture: ArchitectResult | None = None,
    audit: AuditResult | None = None,
    visual_check: VisualCheckResult | None = None,
    message: str | None = None,
) -> None:
    issues = normalize_auditor_issues(audit)
    payload = {
        "type": "pipeline_complete",
        "success": success,
        "code": code,
        "accessibility_code": accessibility_code,
        "issues": [i.model_dump() for i in issues],
        "vision": vision.model_dump() if vision else None,
        "architecture": architecture.model_dump() if architecture else None,
        "audit": audit.model_dump() if audit else None,
        "visual_check": visual_check.model_dump() if visual_check else None,
    }
    if message is not None:
        payload["message"] = message
    await emit(payload)


async def run_vision_parser(
    client: CerebrasClient,
    image_bytes: bytes,
    description: str,
    mime_type: str,
    emit: EmitFn,
) -> VisionParseResult:
    await _emit_status(emit, "vision_parser", "thinking", "Analyzing sketch…")

    extra = f"\nUser context: {description}\n" if description else ""
    if description.strip().lower() == "mock_empty":
        result = VisionParseResult(screen_title="Empty Screen", components=[], notes="Mocked empty screen")
    else:
        try:
            raw = await asyncio.wait_for(
                asyncio.to_thread(
                    call_vision_json,
                    VISION_PARSER_SYSTEM,
                    VISION_PARSER_USER.format(description_extra=extra),
                    image_bytes,
                    mime_type,
                ),
                timeout=VISION_CALL_TIMEOUT,
            )
        except asyncio.TimeoutError as exc:
            raise PipelineAgentError(
                "vision_parser",
                f"Vision parser timed out after {VISION_CALL_TIMEOUT}s",
                cause=exc,
            ) from exc

        data = extract_json(raw)
        result = VisionParseResult.model_validate(data)

    await emit(
        {
            "type": "agent_output",
            "agent": "vision_parser",
            "output": result.model_dump(),
        }
    )
    await _emit_status(emit, "vision_parser", "done", f"Found {len(result.components)} components")
    return result


async def run_architect(
    client: CerebrasClient,
    vision: VisionParseResult | None,
    description: str,
    emit: EmitFn,
) -> ArchitectResult:
    await _emit_status(emit, "architect", "thinking", "Designing component tree…")

    import os
    architect_provider = os.environ.get("ARCHITECT_PROVIDER", "gemma").lower()
    if architect_provider == "gemma":
        model_name = os.environ.get("CEREBRAS_VISION_MODEL", "gemma-4-31b")
        architect_client = CerebrasClient(model=model_name)
    else:
        architect_client = client

    if vision is not None:
        user = ARCHITECT_USER.format(
            description=description or "Mobile-first, clean modern UI",
            vision_json=json.dumps(vision.model_dump(), indent=2),
        )
    else:
        user = ARCHITECT_USER_TEXT_ONLY.format(
            description=description or "Mobile-first, clean modern UI",
        )
    messages = build_text_messages(ARCHITECT_SYSTEM, user)
    raw = await architect_client.acall(messages, max_tokens=2048, temperature=0.2)
    data = await extract_json_with_repair(raw, architect_client)
    result = ArchitectResult.model_validate(data)

    await emit({"type": "agent_output", "agent": "architect", "output": result.model_dump()})
    lines = [line.strip().strip("-*").strip() for line in result.component_tree.split("\n") if line.strip()]
    cleaned = [l for l in lines if l]
    if len(cleaned) > 1:
        tree_summary = ", ".join(cleaned[:4])
        if len(cleaned) > 4:
            tree_summary += "..."
        status_msg = f"Mapped: {tree_summary}"
    else:
        status_msg = "Architecture ready"
    await _emit_status(emit, "architect", "done", status_msg)
    return result


async def run_code_forge(
    client: CerebrasClient,
    vision: VisionParseResult | None,
    architecture: ArchitectResult,
    description: str,
    emit: EmitFn,
) -> str:
    await _emit_status(emit, "code_forge", "streaming", "Generating React code…")

    if vision is not None:
        user = CODE_FORGE_USER.format(
            description=description or "Mobile-first, clean modern UI",
            vision_json=json.dumps(vision.model_dump(), indent=2),
            architecture_json=json.dumps(architecture.model_dump(), indent=2),
        )
    else:
        user = CODE_FORGE_USER_TEXT_ONLY.format(
            description=description or "Mobile-first, clean modern UI",
            architecture_json=json.dumps(architecture.model_dump(), indent=2),
        )
    messages = build_text_messages(CODE_FORGE_SYSTEM, user)

    parts: list[str] = []
    try:
        async for token, tps in client.acall_stream_with_tps(messages, max_tokens=8192, temperature=0.3):
            parts.append(token)
            await emit({"type": "agent_token", "agent": "code_forge", "token": token})
            if tps is not None:
                await emit({"type": "tps", "agent": "code_forge", "tokens_per_second": round(tps, 1)})
    except Exception as exc:
        partial = extract_code("".join(parts)) if parts else None
        raise PipelineAgentError(
            "code_forge",
            str(exc),
            partial_code=partial,
            cause=exc,
        ) from exc

    code = extract_code("".join(parts))
    await emit({"type": "final_code", "code": code})
    status_msg = f"Code generated: {len(code.splitlines())} lines"
    await _emit_status(emit, "code_forge", "done", status_msg)
    return code


async def run_auditor(
    client: CerebrasClient,
    code: str,
    emit: EmitFn,
) -> AuditResult:
    await _emit_status(emit, "auditor", "thinking", "Reviewing code…")

    user = AUDITOR_USER.format(code=code)
    messages = build_text_messages(AUDITOR_SYSTEM, user)
    raw = await client.acall(messages, max_tokens=2048, temperature=0.1)
    data = await extract_json_with_repair(raw, client, debug_agent="auditor")
    result = AuditResult.model_validate(data)

    await emit({"type": "agent_output", "agent": "auditor", "output": result.model_dump()})
    if result.issues:
        status_msg = f"Audit complete: {len(result.issues)} issue{'s' if len(result.issues) != 1 else ''} found"
    else:
        status_msg = "Audit complete: no issues found"
    await _emit_status(emit, "auditor", "done", status_msg)
    return result


async def run_accessibility(
    client: CerebrasClient,
    code: str,
    emit: EmitFn,
) -> str:
    await _emit_status(emit, "accessibility", "streaming", "Adding ARIA + analytics…")

    user = ACCESSIBILITY_USER.format(code=code)
    messages = build_text_messages(ACCESSIBILITY_SYSTEM, user)

    parts: list[str] = []
    try:
        async for token, tps in client.acall_stream_with_tps(messages, max_tokens=8192, temperature=0.2):
            parts.append(token)
            await emit({"type": "agent_token", "agent": "accessibility", "token": token})
            if tps is not None:
                await emit({"type": "tps", "agent": "accessibility", "tokens_per_second": round(tps, 1)})
    except Exception as exc:
        partial = extract_code("".join(parts)) if parts else None
        raise PipelineAgentError(
            "accessibility",
            str(exc),
            partial_code=partial,
            cause=exc,
        ) from exc

    updated = extract_code("".join(parts))
    await emit({"type": "final_code", "code": updated})
    status_msg = f"A11y pass complete: {len(updated.splitlines())} lines of code"
    await _emit_status(emit, "accessibility", "done", status_msg)
    return updated


async def run_visual_check(
    client: CerebrasClient,
    screenshot_bytes: bytes,
    design_contract: str,
    description: str,
    mime_type: str,
    emit: EmitFn | None = None,
    run_id: str | None = None,
) -> VisualCheckResult:
    if emit:
        await _emit_status(emit, "vision_critic", "thinking", "Running visual QA…")

    user_text = VISION_CRITIC_USER.format(
        design_contract=design_contract or "Match the original sketch layout, spacing, and labels.",
        description=description or "Hand-drawn UI sketch converted to React.",
    )
    try:
        raw = await asyncio.wait_for(
            asyncio.to_thread(
                call_vision_json,
                VISION_CRITIC_SYSTEM,
                user_text,
                screenshot_bytes,
                mime_type,
            ),
            timeout=VISION_CALL_TIMEOUT,
        )
    except asyncio.TimeoutError as exc:
        raise PipelineAgentError(
            "vision_critic",
            f"Vision critic timed out after {VISION_CALL_TIMEOUT}s",
            cause=exc,
        ) from exc

    data = extract_json(raw)
    result = VisualCheckResult.model_validate(data)
    finalized = finalize_visual_check_result(result.passed, result.issues, result.summary)
    if run_id in _runs:
        _runs[run_id].visual_issues = [issue.model_dump() for issue in finalized.issues]

    if emit:
        await emit({"type": "agent_output", "agent": "vision_critic", "output": finalized.model_dump()})
        if finalized.passed:
            if finalized.issues:
                status = f"Visual QA passed with {len(finalized.issues)} warning{'s' if len(finalized.issues) != 1 else ''}"
            else:
                status = "Visual QA passed: 0 issues found"
        else:
            status = f"Visual QA failed: {len(finalized.issues)} issue{'s' if len(finalized.issues) != 1 else ''} found"
        await _emit_status(emit, "vision_critic", "done", status)

    return finalized


# Vision/architect/code_forge stop the run; later QA agents just report and we keep the code.
async def _handle_blocking_failure(
    emit: EmitFn,
    agent: str,
    exc: BaseException,
    *,
    vision: VisionParseResult | None = None,
    architecture: ArchitectResult | None = None,
    partial_code: str | None = None,
) -> None:
    await _emit_agent_failure(emit, agent, exc, partial_code=partial_code)
    await _emit_pipeline_complete(
        emit,
        success=False,
        code=partial_code or "",
        vision=vision,
        architecture=architecture,
    )


# Don't emit pipeline_complete — the caller still finishes with the code we already have.
async def _handle_optional_failure(
    emit: EmitFn,
    agent: str,
    exc: BaseException,
    *,
    code: str,
    vision: VisionParseResult | None,
    architecture: ArchitectResult | None,
    audit: AuditResult | None = None,
) -> None:
    await _emit_agent_failure(emit, agent, exc)


@asynccontextmanager
async def _agent(agent: str, run_id: str | None):
    """Log start/complete/failed with duration and record the attempt in SQLite for /metrics."""
    token = agent_var.set(agent)
    start = time.perf_counter()
    log_event(log, "agent_started")
    try:
        yield
    except Exception as exc:
        ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(log, "agent_failed", logging.ERROR, duration_ms=ms, error=str(exc), error_type=type(exc).__name__)
        if run_id:
            db.record_agent_event(run_id, agent, False, ms)
        raise
    else:
        ms = round((time.perf_counter() - start) * 1000, 1)
        log_event(log, "agent_complete", duration_ms=ms)
        if run_id:
            db.record_agent_event(run_id, agent, True, ms)
    finally:
        agent_var.reset(token)


def _persist(run_id: str | None, agent: str, output: dict[str, Any]) -> None:
    if run_id:
        db.save_agent_output(run_id, agent, output)


async def _replay(emit: EmitFn, agent: str, output: dict[str, Any]) -> None:
    """Re-send what a finished agent originally emitted, for a client resuming after a dropped socket."""
    if "code" in output:
        await emit({"type": "final_code", "code": output["code"]})
    else:
        await emit({"type": "agent_output", "agent": agent, "output": output})
    await _emit_status(emit, agent, "done", "Restored from saved run")


async def run_sketchstorm_pipeline(
    client: CerebrasClient,
    image_bytes: bytes | None,
    description: str,
    mime_type: str,
    emit: EmitFn,
    *,
    run_id: str | None = None,
    completed: dict[str, dict[str, Any]] | None = None,
    **kwargs: Any,
) -> dict[str, Any]:
    """Persists run status around the pipeline. `completed` = saved agent outputs to replay and skip.

    A dropped client raises out of emit and leaves the status "running", which is what makes it resumable."""
    if run_id:
        db.save_run(run_id, "running")
    run_token = run_id_var.set(run_id) if run_id else None
    start = time.perf_counter()
    try:
        result = await _run_pipeline(
            client, image_bytes, description, mime_type, emit, run_id=run_id, completed=completed or {}, **kwargs
        )
        # Blocking failures return {}; the no-elements early exit returns no architecture.
        ok = bool(result.get("architecture"))
        if run_id:
            db.save_run(run_id, "complete" if ok else "failed")
        log_event(
            log,
            "pipeline_complete" if ok else "pipeline_failed",
            logging.INFO if ok else logging.ERROR,
            duration_ms=round((time.perf_counter() - start) * 1000, 1),
        )
        return result
    except BaseException as exc:  # e.g. client disconnect mid-run: status stays "running" so it can resume
        log_event(log, "pipeline_failed", logging.ERROR, error=str(exc), error_type=type(exc).__name__,
                  duration_ms=round((time.perf_counter() - start) * 1000, 1))
        raise
    finally:
        if run_token is not None:
            run_id_var.reset(run_token)


async def _run_pipeline(
    client: CerebrasClient,
    image_bytes: bytes | None,
    description: str,
    mime_type: str,
    emit: EmitFn,
    *,
    run_audit: bool = False,
    run_accessibility_pass: bool = False,
    screenshot_bytes: bytes | None = None,
    screenshot_mime: str = "image/png",
    design_contract: str = "",
    run_id: str | None = None,
    completed: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    vision: VisionParseResult | None = None
    architecture: ArchitectResult | None = None
    code = ""
    accessibility_code: str | None = None
    audit_result: AuditResult | None = None
    visual_check: VisualCheckResult | None = None

    if "vision_parser" in completed:
        vision = VisionParseResult.model_validate(completed["vision_parser"])
        await _replay(emit, "vision_parser", completed["vision_parser"])
    elif not image_bytes:
        await _emit_status(emit, "vision_parser", "skipped", "Skipped (no sketch upload)")
    else:
        try:
            async with _agent("vision_parser", run_id):
                vision = await run_vision_parser(client, image_bytes, description, mime_type, emit)
        except Exception as exc:
            await _handle_blocking_failure(emit, "vision_parser", exc)
            return {}

        if vision is not None and not vision.components:
            error_msg = "No UI elements detected in this image. Try a clearer sketch with visible shapes and labels."
            await _emit_status(emit, "vision_parser", "error", error_msg)
            # Empty parse is valid JSON; continuing would invent a UI from the text prompt.
            await _emit_status(emit, "architect", "skipped", "Skipped (no elements detected)")
            await _emit_status(emit, "code_forge", "skipped", "Skipped (no elements detected)")
            await _emit_status(emit, "auditor", "skipped", "Skipped (no elements detected)")
            await _emit_status(emit, "accessibility", "skipped", "Skipped (no elements detected)")
            await _emit_status(emit, "vision_critic", "skipped", "Skipped (no elements detected)")

            await _emit_pipeline_complete(
                emit,
                success=False,
                vision=vision,
                message=error_msg
            )
            return {
                "vision": vision,
                "architecture": None,
                "code": "",
                "audit": None,
                "visual_check": None,
            }
        _persist(run_id, "vision_parser", vision.model_dump())

    if "architect" in completed:
        architecture = ArchitectResult.model_validate(completed["architect"])
        await _replay(emit, "architect", completed["architect"])
    else:
        try:
            async with _agent("architect", run_id):
                architecture = await run_architect(client, vision, description, emit)
        except Exception as exc:
            await _handle_blocking_failure(emit, "architect", exc, vision=vision)
            return {}
        _persist(run_id, "architect", architecture.model_dump())

    try:
        if "code_forge" in completed:
            code = completed["code_forge"]["code"]
            await _replay(emit, "code_forge", completed["code_forge"])
        else:
            async with _agent("code_forge", run_id):
                code = await run_code_forge(client, vision, architecture, description, emit)
            _persist(run_id, "code_forge", {"code": code})
    except PipelineAgentError as exc:
        await _handle_blocking_failure(
            emit,
            exc.agent,
            exc,
            vision=vision,
            architecture=architecture,
            partial_code=exc.partial_code,
        )
        return {}
    except Exception as exc:
        await _handle_blocking_failure(
            emit,
            "code_forge",
            exc,
            vision=vision,
            architecture=architecture,
        )
        return {}

    if "auditor" in completed:
        audit_result = AuditResult.model_validate(completed["auditor"])
        await _replay(emit, "auditor", completed["auditor"])
    elif run_audit:
        try:
            async with _agent("auditor", run_id):
                audit_result = await run_auditor(client, code, emit)
            _persist(run_id, "auditor", audit_result.model_dump())
        except Exception as exc:
            await _handle_optional_failure(
                emit,
                "auditor",
                exc,
                code=code,
                vision=vision,
                architecture=architecture,
            )

    if "accessibility" in completed:
        accessibility_code = code = completed["accessibility"]["code"]
        await _replay(emit, "accessibility", completed["accessibility"])
    elif run_accessibility_pass:
        try:
            async with _agent("accessibility", run_id):
                accessibility_code = await run_accessibility(client, code, emit)
            code = accessibility_code
            _persist(run_id, "accessibility", {"code": code})
        except PipelineAgentError as exc:
            await _handle_optional_failure(
                emit,
                exc.agent,
                exc,
                code=code,
                vision=vision,
                architecture=architecture,
                audit=audit_result,
            )
        except Exception as exc:
            await _handle_optional_failure(
                emit,
                "accessibility",
                exc,
                code=code,
                vision=vision,
                architecture=architecture,
                audit=audit_result,
            )

    if "vision_critic" in completed:
        visual_check = VisualCheckResult.model_validate(completed["vision_critic"])
        await _replay(emit, "vision_critic", completed["vision_critic"])
    elif screenshot_bytes:
        try:
            async with _agent("vision_critic", run_id):
                visual_check = await run_visual_check(
                    client,
                    screenshot_bytes,
                    design_contract,
                    description,
                    screenshot_mime,
                    emit,
                    run_id,
                )
            _persist(run_id, "vision_critic", visual_check.model_dump())
        except Exception as exc:
            agent = exc.agent if isinstance(exc, PipelineAgentError) else "vision_critic"
            await _handle_optional_failure(
                emit,
                agent,
                exc,
                code=code,
                vision=vision,
                architecture=architecture,
                audit=audit_result,
            )

    await _emit_pipeline_complete(
        emit,
        success=True,
        code=code,
        accessibility_code=accessibility_code,
        vision=vision,
        architecture=architecture,
        audit=audit_result,
        visual_check=visual_check,
    )

    return {
        "vision": vision,
        "architecture": architecture,
        "code": code,
        "accessibility_code": accessibility_code,
        "audit": audit_result,
        "visual_check": visual_check,
    }


def _is_serious(issue: dict[str, Any]) -> bool:
    return issue.get("severity") in ("critical", "major")


async def run_auto_refine(
    client: CerebrasClient,
    code: str,
    issues: list[dict[str, Any]],
    *,
    design_contract: str = "",
    description: str = "",
    run_id: str | None = None,
    max_iterations: int = 3,
) -> AsyncIterator[dict[str, Any]]:
    """Patch `code` against `issues`, re-check, repeat. Yields one refine_iteration per round,
    then refine_complete. Failures stop the loop and keep the last good code."""
    current = code
    iterations_run = 0
    stopped_reason = "max_iterations"
    error: str | None = None

    if not any(_is_serious(i) for i in issues):
        stopped_reason = "passed"  # nothing worth fixing; don't burn model calls
    else:
        for iteration in range(1, max_iterations + 1):
            try:
                issues_text = "\n".join(
                    f"- [{i.get('category', '')}] {i.get('severity', '')}: {i.get('description', '')} "
                    f"(Suggestion: {i.get('suggestion', '')})"
                    for i in issues
                )
                user_text = AUTO_REFINE_USER.format(
                    code=current,
                    issues=issues_text,
                    design_contract=design_contract or "Match the original sketch layout, spacing, and labels.",
                    description=description or "Hand-drawn UI sketch converted to React.",
                )
                messages = build_text_messages(AUTO_REFINE_SYSTEM, user_text)
                raw = await asyncio.wait_for(client.acall(messages, max_tokens=8192, temperature=0.2), timeout=25.0)
                patched = extract_code_defensive(raw)
                screenshot = await asyncio.to_thread(render_jsx_to_screenshot, patched)
                check = await run_visual_check(
                    client, screenshot, design_contract, description, "image/png", emit=None, run_id=run_id
                )
            except Exception as exc:
                stopped_reason, error = "error", str(exc) or type(exc).__name__
                break
            current = patched
            iterations_run = iteration
            issues = [i.model_dump() for i in check.issues]
            yield {"type": "refine_iteration", "iteration": iteration, "issues_remaining": issues, "code": current}
            if check.passed and not any(_is_serious(i) for i in issues):
                stopped_reason = "passed"
                break

    if run_id:
        db.save_agent_output(run_id, "auto_refine", {"code": current})
    done: dict[str, Any] = {
        "type": "refine_complete",
        "final_code": current,
        "iterations_run": iterations_run,
        "stopped_reason": stopped_reason,
    }
    if error:
        done["message"] = error
    yield done
