"""SketchStorm agent pipeline orchestration."""

from __future__ import annotations

import json
import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from agent_prompts import (
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
from parsing import extract_code, extract_json, extract_json_with_repair
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


_latest_visual_issues: list[dict[str, Any]] = []


def get_latest_visual_issues() -> list[dict[str, Any]]:
    global _latest_visual_issues
    return _latest_visual_issues


def set_latest_visual_issues(issues: list[dict[str, Any]]) -> None:
    global _latest_visual_issues
    _latest_visual_issues = issues


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
    raw = await client.acall(messages, max_tokens=2048, temperature=0.2)
    data = await extract_json_with_repair(raw, client)
    result = ArchitectResult.model_validate(data)

    await emit({"type": "agent_output", "agent": "architect", "output": result.model_dump()})
    await _emit_status(emit, "architect", "done", "Architecture ready")
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
    await _emit_status(emit, "code_forge", "done", "Code generation complete")
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
    await _emit_status(emit, "auditor", "done", result.summary or "Audit complete")
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
    await _emit_status(emit, "accessibility", "done", "Accessibility pass complete")
    return updated


async def run_visual_check(
    client: CerebrasClient,
    screenshot_bytes: bytes,
    design_contract: str,
    description: str,
    mime_type: str,
    emit: EmitFn | None = None,
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
    set_latest_visual_issues([issue.model_dump() for issue in finalized.issues])

    # cache for /chat critic queries
    global _latest_visual_issues
    _latest_visual_issues = [i.model_dump() for i in finalized.issues]

    if emit:
        await emit({"type": "agent_output", "agent": "vision_critic", "output": finalized.model_dump()})
        status = "Visual QA: OK" if finalized.passed else "Visual QA: issues found"
        await _emit_status(emit, "vision_critic", "done", status)

    return finalized


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


async def run_sketchstorm_pipeline(
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
) -> dict[str, Any]:
    vision: VisionParseResult | None = None
    architecture: ArchitectResult | None = None
    code = ""
    accessibility_code: str | None = None
    audit_result: AuditResult | None = None
    visual_check: VisualCheckResult | None = None

    if not image_bytes:
        await _emit_status(emit, "vision_parser", "skipped", "Skipped (no sketch upload)")
    else:
        try:
            vision = await run_vision_parser(client, image_bytes, description, mime_type, emit)
        except Exception as exc:
            await _handle_blocking_failure(emit, "vision_parser", exc)
            return {}

        if vision is not None and not vision.components:
            error_msg = "No UI elements detected in this image. Try a clearer sketch with visible shapes and labels."
            await _emit_status(emit, "vision_parser", "error", error_msg)
            # Explicitly mark all downstream agents as skipped
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

    try:
        architecture = await run_architect(client, vision, description, emit)
    except Exception as exc:
        await _handle_blocking_failure(emit, "architect", exc, vision=vision)
        return {}

    try:
        code = await run_code_forge(client, vision, architecture, description, emit)
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

    if run_audit:
        try:
            audit_result = await run_auditor(client, code, emit)
        except Exception as exc:
            await _handle_optional_failure(
                emit,
                "auditor",
                exc,
                code=code,
                vision=vision,
                architecture=architecture,
            )

    if run_accessibility_pass:
        try:
            accessibility_code = await run_accessibility(client, code, emit)
            code = accessibility_code
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

    if screenshot_bytes:
        try:
            visual_check = await run_visual_check(
                client,
                screenshot_bytes,
                design_contract,
                description,
                screenshot_mime,
                emit,
            )
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
