"""Pydantic models shared by the API and the pipeline.

Responsibilities: the structured output each agent must produce (Vision Parser, Architect, Auditor,
Critic), HTTP request and response bodies, and the shapes of server-to-client WebSocket events.
Validation here is what rejects malformed model output and bad requests.

Interacts with: orchestrator.py (validates agent output), main.py (request/response models) and
parsing.py (its JSON is validated against these models).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

AgentName = Literal[
    "vision_parser",
    "architect",
    "code_forge",
    "auditor",
    "accessibility",
    "vision_critic",
]

AgentStatus = Literal["idle", "thinking", "streaming", "done", "error", "skipped"]


class VisionComponent(BaseModel):
    """One UI element the Vision Parser found in a sketch: type, label and bounding box."""
    type: str
    label: str = ""
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0


class VisionParseResult(BaseModel):
    """Vision Parser output: screen title, the components found, and free-form notes."""
    screen_title: str = "App"
    components: list[VisionComponent] = Field(default_factory=list)
    notes: str = ""


class ArchitectResult(BaseModel):
    """Architect output: component tree, layout plan, routing and an optional skeleton."""
    component_tree: str
    layout_plan: str
    routing: str = ""
    routes: list[str] = Field(default_factory=list)
    skeleton_jsx: str = ""


class AuditIssue(BaseModel):
    """One finding from the Auditor."""
    model_config = {"extra": "ignore"}

    severity: Literal["error", "warning", "info"] = "warning"
    message: str
    line_hint: str = ""


class AuditResult(BaseModel):
    """Auditor output: list of issues and a summary."""
    issues: list[AuditIssue] = Field(default_factory=list)
    summary: str = ""


class NormalizedIssue(BaseModel):
    """Auditor or A11y finding in the unified form the UI shows."""
    agent: Literal["Auditor", "A11y"]
    severity: Literal["error", "warn", "info"]
    description: str
    code_region: str = ""


class VisualIssue(BaseModel):
    """One visual problem reported by the Critic."""
    category: str
    severity: Literal["critical", "major", "minor"] = "minor"
    description: str
    suggestion: str = ""


class VisualCheckResult(BaseModel):
    """Critic output: pass/fail verdict, derived status, issues and summary."""
    passed: bool
    status: Literal["pass", "pass_with_warnings", "fail"] = "fail"
    issues: list[VisualIssue] = Field(default_factory=list)
    summary: str = ""


class GenerateResponse(BaseModel):
    """Response body of the synchronous POST /generate."""
    session_id: str
    vision: VisionParseResult | None = None
    architecture: ArchitectResult | None = None
    code: str = ""
    audit: AuditResult | None = None
    accessibility_code: str | None = None
    visual_check: VisualCheckResult | None = None


class AuditRequest(BaseModel):
    """Request body for /audit and /audit/full."""
    code: str
    run_accessibility: bool = True


class VisualCheckRequest(BaseModel):
    """Request body for /visual-check: code to render, or a client-captured screenshot."""
    code: str = ""
    description: str = ""
    design_contract: str = ""
    # Base64 screenshot (PNG/JPEG). Skip headless browser when provided.
    screenshot_base64: str = ""


# WebSocket message types (server → client)
class WSAgentStatus(BaseModel):
    """WebSocket event: an agent changed status."""
    type: Literal["agent_status"] = "agent_status"
    agent: AgentName
    status: AgentStatus
    message: str = ""


class WSAgentToken(BaseModel):
    """WebSocket event: one streamed token from an agent."""
    type: Literal["agent_token"] = "agent_token"
    agent: AgentName
    token: str


class WSAgentOutput(BaseModel):
    """WebSocket event: an agent finished and produced structured output."""
    type: Literal["agent_output"] = "agent_output"
    agent: AgentName
    output: dict[str, Any]


class WSFinalCode(BaseModel):
    """WebSocket event: the full generated (or revised) code."""
    type: Literal["final_code"] = "final_code"
    code: str


class WSTps(BaseModel):
    """WebSocket event: streaming throughput in tokens per second."""
    type: Literal["tps"] = "tps"
    agent: AgentName
    tokens_per_second: float


class WSError(BaseModel):
    """WebSocket event: an error, optionally tied to an agent."""
    type: Literal["error"] = "error"
    message: str
    agent: AgentName | None = None


class WSPipelineComplete(BaseModel):
    """WebSocket event: the run ended; carries success, code and the agent results."""
    type: Literal["pipeline_complete"] = "pipeline_complete"
    success: bool = True
    code: str
    issues: list[NormalizedIssue] = Field(default_factory=list)
    vision: dict[str, Any] | None = None
    architecture: dict[str, Any] | None = None
    audit: dict[str, Any] | None = None
    visual_check: dict[str, Any] | None = None
    accessibility_code: str | None = None
    message: str | None = None


#  Chat models

ChatAgent = Literal["architect", "design_advisor", "critic"]


class ChatContext(BaseModel):
    """UI context sent with a chat message."""
    route: str = ""
    layout_summary: str = ""
    code_summary: str = ""


class ChatRequest(BaseModel):
    """Request body for POST /chat. `run_id` lets the critic agent look up that run's issues."""
    agent: ChatAgent
    message: str
    run_id: str | None = None
    context: ChatContext = Field(default_factory=ChatContext)


class ChatResponse(BaseModel):
    """Response body for POST /chat: reply text and optional structured change suggestions."""
    reply: str
    suggested_changes: dict[str, Any] | None = None


class AutoRefineRequest(BaseModel):
    """Request body for POST /auto-refine: the code, design contract and the Critic issues to fix."""
    code: str
    design_contract: str = ""
    description: str = ""
    run_id: str | None = None
    visual_issues: list[VisualIssue] = Field(default_factory=list)


class DiffStats(BaseModel):
    """Line-level change statistics between original and patched code."""
    lines_changed: int
    lines_total: int
    change_ratio: float


class RefineRegionRequest(BaseModel):
    """Request body for POST /refine-region."""
    code: str
    region_description: str
    refinement_request: str = ""
    sketch_image_base64: str = ""

    @model_validator(mode="after")
    def require_at_least_one_input(self) -> "RefineRegionRequest":
        """Validate that a text request or a sketch was provided.

        Raises:
            ValueError: Both `refinement_request` and `sketch_image_base64` are empty.
        """
        if not self.refinement_request.strip() and not self.sketch_image_base64.strip():
            raise ValueError(
                "At least one of refinement_request or sketch_image_base64 must be provided"
            )
        return self


class RefineRegionResponse(BaseModel):
    """Response body for POST /refine-region: patched code, summary, diff stats and an optional warning."""
    patched_code: str
    changed_regions_summary: str
    diff_stats: DiffStats
    warning: str | None = None

