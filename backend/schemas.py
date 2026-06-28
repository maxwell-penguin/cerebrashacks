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
    type: str
    label: str = ""
    x: float = 0
    y: float = 0
    width: float = 0
    height: float = 0


class VisionParseResult(BaseModel):
    screen_title: str = "App"
    components: list[VisionComponent] = Field(default_factory=list)
    notes: str = ""


class ArchitectResult(BaseModel):
    component_tree: str
    layout_plan: str
    routing: str = ""
    routes: list[str] = Field(default_factory=list)
    skeleton_jsx: str = ""


class AuditIssue(BaseModel):
    model_config = {"extra": "ignore"}

    severity: Literal["error", "warning", "info"] = "warning"
    message: str
    line_hint: str = ""


class AuditResult(BaseModel):
    issues: list[AuditIssue] = Field(default_factory=list)
    summary: str = ""


class NormalizedIssue(BaseModel):
    agent: Literal["Auditor", "A11y"]
    severity: Literal["error", "warn", "info"]
    description: str
    code_region: str = ""


class VisualIssue(BaseModel):
    category: str
    severity: Literal["critical", "major", "minor"] = "minor"
    description: str
    suggestion: str = ""


class VisualCheckResult(BaseModel):
    passed: bool
    status: Literal["pass", "pass_with_warnings", "fail"] = "fail"
    issues: list[VisualIssue] = Field(default_factory=list)
    summary: str = ""


class GenerateResponse(BaseModel):
    session_id: str
    vision: VisionParseResult | None = None
    architecture: ArchitectResult | None = None
    code: str = ""
    audit: AuditResult | None = None
    accessibility_code: str | None = None
    visual_check: VisualCheckResult | None = None


class AuditRequest(BaseModel):
    code: str
    run_accessibility: bool = True


class VisualCheckRequest(BaseModel):
    code: str = ""
    description: str = ""
    design_contract: str = ""
    # Base64 screenshot (PNG/JPEG). Skip headless browser when provided.
    screenshot_base64: str = ""


# WebSocket message types (server → client)
class WSAgentStatus(BaseModel):
    type: Literal["agent_status"] = "agent_status"
    agent: AgentName
    status: AgentStatus
    message: str = ""


class WSAgentToken(BaseModel):
    type: Literal["agent_token"] = "agent_token"
    agent: AgentName
    token: str


class WSAgentOutput(BaseModel):
    type: Literal["agent_output"] = "agent_output"
    agent: AgentName
    output: dict[str, Any]


class WSFinalCode(BaseModel):
    type: Literal["final_code"] = "final_code"
    code: str


class WSTps(BaseModel):
    type: Literal["tps"] = "tps"
    agent: AgentName
    tokens_per_second: float


class WSError(BaseModel):
    type: Literal["error"] = "error"
    message: str
    agent: AgentName | None = None


class WSPipelineComplete(BaseModel):
    type: Literal["pipeline_complete"] = "pipeline_complete"
    success: bool = True
    code: str
    issues: list[NormalizedIssue] = Field(default_factory=list)
    vision: dict[str, Any] | None = None
    architecture: dict[str, Any] | None = None


#  Chat models

ChatAgent = Literal["architect", "design_advisor", "critic"]


class ChatContext(BaseModel):
    route: str = ""
    layout_summary: str = ""
    code_summary: str = ""


class ChatRequest(BaseModel):
    agent: ChatAgent
    message: str
    context: ChatContext = Field(default_factory=ChatContext)


class ChatResponse(BaseModel):
    reply: str
    suggested_changes: dict[str, Any] | None = None


class AutoRefineRequest(BaseModel):
    code: str
    design_contract: str = ""
    description: str = ""


class AutoRefineResult(BaseModel):
    final_code: str
    iterations_run: int
    stopped_reason: Literal["passed", "max_iterations", "error"]
    issues_per_iteration: list[list[VisualIssue]] = Field(default_factory=list)


class DiffStats(BaseModel):
    lines_changed: int
    lines_total: int
    change_ratio: float


class RefineRegionRequest(BaseModel):
    code: str
    region_description: str
    refinement_request: str = ""
    sketch_image_base64: str = ""

    @model_validator(mode="after")
    def require_at_least_one_input(self) -> "RefineRegionRequest":
        if not self.refinement_request.strip() and not self.sketch_image_base64.strip():
            raise ValueError(
                "At least one of refinement_request or sketch_image_base64 must be provided"
            )
        return self


class RefineRegionResponse(BaseModel):
    patched_code: str
    changed_regions_summary: str
    diff_stats: DiffStats
    warning: str | None = None

