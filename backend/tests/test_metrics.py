import pytest
from fastapi.testclient import TestClient

import cerebras_client
import db
import main
import orchestrator
from test_integration import FakeCerebrasClient, _env  # noqa: F401  (_env: autouse fixture)


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "runs.db"))
    db.init_db()
    monkeypatch.setattr(cerebras_client, "_breaker", cerebras_client.CircuitBreaker())


def metrics():
    r = TestClient(main.app).get("/metrics")
    assert r.status_code == 200
    return r.json()


async def pipeline(monkeypatch, run_id, fake):
    monkeypatch.setattr(orchestrator, "call_vision_json", fake.vision_call)

    async def emit(_):
        pass

    await orchestrator.run_sketchstorm_pipeline(
        fake, b"img", "a button", "image/png", emit, run_id=run_id,
        run_audit=True, run_accessibility_pass=True, screenshot_bytes=b"shot",
    )


def test_metrics_shape():
    m = metrics()
    assert set(m) == {
        "runs_total", "runs_complete", "runs_failed", "runs_in_progress",
        "agent_success_counts", "agent_failure_counts",
        "agent_p50_latency_ms", "agent_p95_latency_ms", "circuit_breaker_state",
    }
    assert m["runs_total"] == 0 and m["circuit_breaker_state"] == "CLOSED"


async def test_runs_complete_increments(monkeypatch):
    await pipeline(monkeypatch, "ok1", FakeCerebrasClient())
    m = metrics()
    assert (m["runs_total"], m["runs_complete"], m["runs_failed"], m["runs_in_progress"]) == (1, 1, 0, 0)


async def test_runs_failed_increments(monkeypatch):
    await pipeline(monkeypatch, "bad1", FakeCerebrasClient(fail_at_call=2, fail_count=3))  # architect dies
    m = metrics()
    assert (m["runs_complete"], m["runs_failed"]) == (0, 1)


async def test_agent_counts_reflect_runs(monkeypatch):
    await pipeline(monkeypatch, "ok1", FakeCerebrasClient())
    await pipeline(monkeypatch, "bad1", FakeCerebrasClient(fail_at_call=2, fail_count=3))
    m = metrics()
    assert m["agent_success_counts"] == {
        "vision_parser": 2, "architect": 1, "code_forge": 1, "auditor": 1, "accessibility": 1, "vision_critic": 1,
    }
    assert m["agent_failure_counts"] == {"architect": 1}
    assert set(m["agent_p50_latency_ms"]) == set(m["agent_success_counts"])
    assert all(m["agent_p95_latency_ms"][a] >= m["agent_p50_latency_ms"][a] for a in m["agent_p50_latency_ms"])


def test_breaker_state_is_live(monkeypatch):
    breaker = cerebras_client._breaker
    for state, expected in ((breaker.OPEN, "OPEN"), (breaker.HALF_OPEN, "HALF_OPEN"), (breaker.CLOSED, "CLOSED")):
        breaker.state = state
        assert metrics()["circuit_breaker_state"] == expected
