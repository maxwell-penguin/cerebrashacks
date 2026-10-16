import json

import pytest

import db
import orchestrator

SERIOUS = {"category": "layout", "severity": "major", "description": "overflow", "suggestion": "wrap"}
PASS_JSON = {"passed": True, "status": "pass", "issues": [], "summary": "ok"}
FAIL_JSON = {"passed": False, "status": "fail", "issues": [SERIOUS], "summary": "bad"}


class FakeClient:
    """Each acall = one Code Forge-style revision, returned as v1, v2, ..."""

    def __init__(self):
        self.calls = 0

    async def acall(self, messages, **_):
        self.calls += 1
        return f"```jsx\nexport default function App() {{ return <div>v{self.calls}</div>; }}\n```"


@pytest.fixture
def setup(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "runs.db"))
    db.init_db()
    monkeypatch.setattr(orchestrator, "render_jsx_to_screenshot", lambda code: b"png")

    def critic(*verdicts):
        it = iter(verdicts)
        monkeypatch.setattr(orchestrator, "call_vision_json", lambda *a: json.dumps(next(it)))

    return critic


async def collect(**kw):
    client = FakeClient()
    events = [e async for e in orchestrator.run_auto_refine(client, "old", [SERIOUS], run_id="r1", **kw)]
    return client, events


async def test_three_iterations_when_issues_persist(setup):
    setup(FAIL_JSON, FAIL_JSON, FAIL_JSON)
    client, events = await collect()
    assert client.calls == 3
    assert events[-1]["iterations_run"] == 3 and events[-1]["stopped_reason"] == "max_iterations"
    assert events[-2]["issues_remaining"][0]["description"] == "overflow"


async def test_early_exit_when_resolved_after_first_iteration(setup):
    setup(PASS_JSON)
    client, events = await collect()
    assert client.calls == 1
    assert events[-1]["iterations_run"] == 1 and events[-1]["stopped_reason"] == "passed"
    assert events[0]["issues_remaining"] == []


async def test_final_code_saved_to_sqlite(setup):
    setup(FAIL_JSON, PASS_JSON)
    _, events = await collect()
    final = events[-1]["final_code"]
    assert "v2" in final
    with db._connect() as conn:
        row = conn.execute("SELECT output FROM agent_outputs WHERE run_id='r1' AND agent_name='auto_refine'").fetchone()
    assert json.loads(row[0]) == {"code": final}


async def test_events_arrive_in_order(setup):
    setup(FAIL_JSON, FAIL_JSON, PASS_JSON)
    _, events = await collect()
    assert [e["type"] for e in events] == ["refine_iteration"] * 3 + ["refine_complete"]
    assert [e["iteration"] for e in events[:3]] == [1, 2, 3]
    assert [("v%d" % n) in e["code"] for n, e in enumerate(events[:3], 1)] == [True] * 3
