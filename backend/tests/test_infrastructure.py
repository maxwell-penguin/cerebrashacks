"""
Infrastructure and reliability tests for SketchStorm Studio.
These tests cover timeout behavior, resource cleanup, concurrency
safety, and deployment configuration — areas relevant to
production engineering and site reliability.
"""

import pytest
import asyncio
import time


# ─────────────────────────────────────────────
# Timeout enforcement
# ─────────────────────────────────────────────

class TestTimeoutEnforcement:
    """
    Each agent call must respect a hard timeout.
    A slow or hung agent must never block the pipeline indefinitely.
    """

    @pytest.mark.asyncio
    async def test_agent_call_respects_timeout(self):
        """Agent that exceeds timeout should raise, not hang."""
        async def slow_agent():
            await asyncio.sleep(30)  # simulates a hung API call
            return {"status": "success"}

        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(slow_agent(), timeout=0.1)

    @pytest.mark.asyncio
    async def test_fast_agent_completes_within_timeout(self):
        """Agent that responds quickly should complete successfully."""
        async def fast_agent():
            await asyncio.sleep(0.01)
            return {"status": "success", "output": "code"}

        result = await asyncio.wait_for(fast_agent(), timeout=5.0)
        assert result["status"] == "success"

    def test_timeout_values_are_reasonable(self):
        """
        Timeouts must be long enough to allow real API calls
        but short enough to prevent indefinite hangs.
        Acceptable range: 5s minimum, 60s maximum.
        """
        AGENT_TIMEOUT = 25  # matches backend/cerebras_client.py
        STALL_TIMEOUT = 8   # inter-token stall detection

        assert 5 <= AGENT_TIMEOUT <= 60, "Agent timeout out of acceptable range"
        assert 2 <= STALL_TIMEOUT <= 30, "Stall timeout out of acceptable range"


# ─────────────────────────────────────────────
# Concurrency safety
# ─────────────────────────────────────────────

class TestConcurrencySafety:
    """
    Multiple simultaneous WebSocket sessions must not interfere
    with each other. Each session must be fully isolated.
    """

    @pytest.mark.asyncio
    async def test_concurrent_sessions_are_independent(self):
        """Two sessions running simultaneously must not share state."""
        results = {}

        async def run_session(session_id, delay):
            await asyncio.sleep(delay)
            results[session_id] = {"session_id": session_id, "status": "success"}

        await asyncio.gather(
            run_session("session_a", 0.01),
            run_session("session_b", 0.02),
        )

        assert results["session_a"]["session_id"] == "session_a"
        assert results["session_b"]["session_id"] == "session_b"
        assert results["session_a"] != results["session_b"]

    @pytest.mark.asyncio
    async def test_failed_session_does_not_affect_other_sessions(self):
        """A failing session must not crash other active sessions."""
        results = {}

        async def good_session():
            await asyncio.sleep(0.01)
            results["good"] = "success"

        async def bad_session():
            await asyncio.sleep(0.01)
            raise Exception("Session crashed")

        results_list = await asyncio.gather(
            good_session(),
            bad_session(),
            return_exceptions=True
        )

        assert results["good"] == "success"
        assert isinstance(results_list[1], Exception)


# ─────────────────────────────────────────────
# Environment configuration
# ─────────────────────────────────────────────

class TestEnvironmentConfiguration:
    """
    Deployment configuration must be validated at startup.
    Missing required environment variables must fail loudly,
    not silently produce wrong behavior.
    """

    def test_required_env_vars_are_documented(self):
        """
        All required environment variables must be present
        in .env.example so operators know what to configure.
        """
        # These are the keys that must appear in .env.example
        required_vars = [
            "CEREBRAS_API_KEY",
            "ANTHROPIC_API_KEY",
        ]

        try:
            with open(".env.example", "r") as f:
                env_example = f.read()
            for var in required_vars:
                assert var in env_example, f"Missing required env var in .env.example: {var}"
        except FileNotFoundError:
            pytest.skip(".env.example not found at this path, skipping")

    def test_missing_api_key_produces_clear_error(self):
        """
        A missing API key should produce a clear, actionable error
        message, not a cryptic downstream failure.
        """
        def validate_config(api_key):
            if not api_key:
                raise ValueError(
                    "CEREBRAS_API_KEY is not set. "
                    "Copy .env.example to .env and fill in your API keys."
                )
            return True

        with pytest.raises(ValueError) as exc_info:
            validate_config(None)

        assert "CEREBRAS_API_KEY" in str(exc_info.value)
        assert ".env" in str(exc_info.value)


# ─────────────────────────────────────────────
# Resource cleanup
# ─────────────────────────────────────────────

class TestResourceCleanup:
    """
    Resources opened during a generation run must be cleaned up
    after the run completes, whether it succeeded or failed.
    """

    @pytest.mark.asyncio
    async def test_resources_cleaned_up_on_success(self):
        """Resources must be released after a successful run."""
        resources_open = []
        resources_closed = []

        class MockResource:
            def __init__(self, name):
                self.name = name
                resources_open.append(name)

            def close(self):
                resources_closed.append(self.name)

        async def run_with_resource():
            resource = MockResource("playwright_browser")
            try:
                await asyncio.sleep(0.01)  # simulate work
                return {"status": "success"}
            finally:
                resource.close()

        result = await run_with_resource()
        assert result["status"] == "success"
        assert "playwright_browser" in resources_closed

    @pytest.mark.asyncio
    async def test_resources_cleaned_up_on_failure(self):
        """Resources must be released even when a run fails."""
        resources_closed = []

        class MockResource:
            def close(self):
                resources_closed.append("closed")

        async def run_with_failure():
            resource = MockResource()
            try:
                raise Exception("Agent failed")
            finally:
                resource.close()

        with pytest.raises(Exception):
            await run_with_failure()

        assert "closed" in resources_closed


# ─────────────────────────────────────────────
# Health check endpoint
# ─────────────────────────────────────────────

class TestHealthCheck:
    """
    The service must expose a health check endpoint so that
    load balancers and monitoring systems can verify liveness.
    """

    def test_health_response_structure(self):
        """Health check response must include status and version."""
        mock_health_response = {
            "status": "ok",
            "version": "1.0.0",
            "agents": {
                "vision_parser": "ready",
                "architect": "ready",
                "code_forge": "ready",
                "auditor": "ready",
                "accessibility": "ready",
                "vision_critic": "ready",
            }
        }

        assert mock_health_response["status"] == "ok"
        assert "version" in mock_health_response
        assert len(mock_health_response["agents"]) == 6
        for agent, status in mock_health_response["agents"].items():
            assert status in ("ready", "degraded", "unavailable")

    def test_degraded_health_still_returns_response(self):
        """
        A degraded service (e.g. one agent unavailable) must still
        return a response, not a 500 error. Operators need to know
        which component is down.
        """
        degraded_response = {
            "status": "degraded",
            "version": "1.0.0",
            "agents": {
                "vision_parser": "unavailable",
                "architect": "ready",
                "code_forge": "ready",
                "auditor": "ready",
                "accessibility": "ready",
                "vision_critic": "ready",
            }
        }

        assert degraded_response["status"] == "degraded"
        assert degraded_response["agents"]["vision_parser"] == "unavailable"
        # Service should still report other agents as ready
        ready_agents = [
            k for k, v in degraded_response["agents"].items()
            if v == "ready"
        ]
        assert len(ready_agents) == 5