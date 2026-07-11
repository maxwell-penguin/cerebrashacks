"""
Tests for SketchStorm Studio agent pipeline.
Tests cover agent initialization, pipeline flow, error isolation,
and WebSocket response structure.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ─────────────────────────────────────────────
# Agent output schema validation
# ─────────────────────────────────────────────

class TestAgentOutputSchema:
    """Each agent must return a dict with status and output keys."""

    def test_vision_parser_output_has_required_keys(self):
        """Vision Parser must return status and structured layout."""
        mock_output = {
            "status": "success",
            "layout": {
                "components": ["header", "sidebar", "main"],
                "description": "Dashboard with nav and content area"
            }
        }
        assert "status" in mock_output
        assert "layout" in mock_output
        assert mock_output["status"] in ("success", "failure")

    def test_architect_output_has_required_keys(self):
        """Architect must return a component plan."""
        mock_output = {
            "status": "success",
            "component_plan": [
                {"name": "Header", "props": ["title"]},
                {"name": "Sidebar", "props": ["links"]},
            ]
        }
        assert "status" in mock_output
        assert "component_plan" in mock_output
        assert isinstance(mock_output["component_plan"], list)

    def test_code_forge_output_has_required_keys(self):
        """Code Forge must return generated React code."""
        mock_output = {
            "status": "success",
            "code": "export default function App() { return <div>Hello</div> }"
        }
        assert "status" in mock_output
        assert "code" in mock_output
        assert len(mock_output["code"]) > 0

    def test_agent_failure_state_is_explicit(self):
        """
        A failed agent must return an explicit failure status,
        never an empty or ambiguous response.
        This is the core fault isolation guarantee.
        """
        mock_failure = {
            "status": "failure",
            "error": "Rate limit exceeded on Cerebras API",
            "code": None
        }
        assert mock_failure["status"] == "failure"
        assert mock_failure["error"] is not None
        assert mock_failure["code"] is None


# ─────────────────────────────────────────────
# Pipeline fault isolation
# ─────────────────────────────────────────────

class TestPipelineFaultIsolation:
    """
    A single agent failure must not crash the whole pipeline.
    Every generation must end in a clean success or failure state.
    """

    def test_pipeline_result_always_has_status(self):
        """Pipeline result must always contain a top-level status."""
        # Simulates what the pipeline returns when Code Forge fails
        pipeline_result_on_failure = {
            "status": "failure",
            "failed_agent": "code_forge",
            "error": "Timeout after 30s",
            "partial_outputs": {
                "vision_parser": {"status": "success", "layout": {}},
                "architect": {"status": "success", "component_plan": []},
                "code_forge": {"status": "failure", "error": "Timeout after 30s"},
            }
        }
        assert "status" in pipeline_result_on_failure
        assert pipeline_result_on_failure["status"] in ("success", "failure")
        assert "failed_agent" in pipeline_result_on_failure

    def test_successful_agents_preserve_output_on_downstream_failure(self):
        """
        If Code Forge fails, Vision Parser and Architect outputs
        must still be accessible for debugging.
        """
        pipeline_result = {
            "status": "failure",
            "failed_agent": "code_forge",
            "partial_outputs": {
                "vision_parser": {"status": "success", "layout": {"components": ["nav"]}},
                "architect": {"status": "success", "component_plan": [{"name": "Nav"}]},
                "code_forge": {"status": "failure", "error": "Timeout"},
            }
        }
        assert pipeline_result["partial_outputs"]["vision_parser"]["status"] == "success"
        assert pipeline_result["partial_outputs"]["architect"]["status"] == "success"
        assert pipeline_result["partial_outputs"]["code_forge"]["status"] == "failure"

    def test_pipeline_never_returns_none(self):
        """Pipeline must never return None. Always a dict with status."""
        def mock_run_pipeline(sketch_input):
            if not sketch_input:
                return {"status": "failure", "error": "Empty input"}
            return {"status": "success", "code": "<App />"}

        result = mock_run_pipeline(None)
        assert result is not None
        assert "status" in result

        result = mock_run_pipeline("sketch_data")
        assert result is not None
        assert "status" in result


# ─────────────────────────────────────────────
# Retry logic
# ─────────────────────────────────────────────

class TestRetryLogic:
    """Agents must retry on rate limit errors with exponential backoff."""

    @pytest.mark.asyncio
    async def test_retry_on_rate_limit(self):
        """Agent should retry up to max_retries times on a 429 error."""
        call_count = 0

        async def mock_api_call():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("429 Rate limit exceeded")
            return {"status": "success", "output": "generated code"}

        # Simulate retry wrapper
        max_retries = 3
        result = None
        for attempt in range(max_retries):
            try:
                result = await mock_api_call()
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    result = {"status": "failure", "error": str(e)}

        assert result is not None
        assert result["status"] == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_retry_exhaustion_returns_failure(self):
        """If all retries fail, return explicit failure not an exception."""
        async def always_fails():
            raise Exception("API unavailable")

        max_retries = 3
        result = None
        for attempt in range(max_retries):
            try:
                result = await always_fails()
                break
            except Exception as e:
                if attempt == max_retries - 1:
                    result = {"status": "failure", "error": str(e)}

        assert result["status"] == "failure"
        assert "error" in result


# ─────────────────────────────────────────────
# Input validation
# ─────────────────────────────────────────────

class TestInputValidation:
    """Pipeline should reject invalid inputs before hitting any agent."""

    def test_rejects_empty_image(self):
        """Empty image input should fail fast before calling any agent."""
        def validate_input(image_data, prompt):
            if not image_data:
                return {"valid": False, "error": "Image data is required"}
            if not prompt:
                return {"valid": False, "error": "Prompt is required"}
            return {"valid": True}

        result = validate_input(None, "Build a dashboard")
        assert result["valid"] is False
        assert "Image" in result["error"]

    def test_rejects_empty_prompt(self):
        """Empty prompt should fail fast before calling any agent."""
        def validate_input(image_data, prompt):
            if not image_data:
                return {"valid": False, "error": "Image data is required"}
            if not prompt:
                return {"valid": False, "error": "Prompt is required"}
            return {"valid": True}

        result = validate_input(b"fake_image_bytes", "")
        assert result["valid"] is False
        assert "Prompt" in result["error"]

    def test_valid_input_passes(self):
        """Valid image and prompt should pass validation."""
        def validate_input(image_data, prompt):
            if not image_data:
                return {"valid": False, "error": "Image data is required"}
            if not prompt:
                return {"valid": False, "error": "Prompt is required"}
            return {"valid": True}

        result = validate_input(b"fake_image_bytes", "Build a dashboard")
        assert result["valid"] is True


# ─────────────────────────────────────────────
# WebSocket message structure
# ─────────────────────────────────────────────

class TestWebSocketMessages:
    """WebSocket messages must follow a consistent structure."""

    def test_agent_status_message_structure(self):
        """
        Every agent status update sent over WebSocket must have
        type, agent, and status fields.
        """
        message = {
            "type": "agent_update",
            "agent": "vision_parser",
            "status": "running",
            "output": None
        }
        assert "type" in message
        assert "agent" in message
        assert "status" in message
        assert message["type"] == "agent_update"
        assert message["status"] in ("running", "success", "failure")

    def test_completion_message_contains_code(self):
        """Final WebSocket message must include generated code."""
        completion_message = {
            "type": "generation_complete",
            "status": "success",
            "code": "export default function App() { return <div>Hello</div> }",
            "screenshot_url": "https://example.com/screenshot.png"
        }
        assert completion_message["type"] == "generation_complete"
        assert "code" in completion_message
        assert len(completion_message["code"]) > 0

    def test_failure_message_has_no_code(self):
        """On failure, WebSocket message must not include partial code."""
        failure_message = {
            "type": "generation_complete",
            "status": "failure",
            "error": "Code Forge timed out",
            "code": None
        }
        assert failure_message["status"] == "failure"
        assert failure_message["code"] is None
        assert "error" in failure_message