import db
from test_integration import FakeCerebrasClient, _env  # noqa: F401  (_env: autouse fixture)


async def test_resume_replays_finished_agents_and_runs_the_rest(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "runs.db"))
    db.init_db()

    async def go(fake, completed=None):
        monkeypatch.setattr("orchestrator.call_vision_json", fake.vision_call)
        events = []

        async def emit(m):
            events.append(m)

        import orchestrator
        res = await orchestrator.run_sketchstorm_pipeline(
            fake, b"img", "a button", "image/png", emit, run_id="r1", completed=completed,
            run_audit=True, run_accessibility_pass=True, screenshot_bytes=b"shot",
        )
        return res, events

    res, _ = await go(FakeCerebrasClient(fail_at_call=2, fail_count=2))  # architect dies after vision
    assert res == {} and db.load_run("r1")["status"] == "failed"
    assert list(db.load_run("r1")["agent_outputs"]) == ["vision_parser"]

    fake = FakeCerebrasClient()
    res, events = await go(fake, db.load_run("r1")["agent_outputs"])
    assert fake.log.count("vision") == 1  # only the critic; the parser was replayed, not re-run
    assert fake.calls == 5
    assert "export default function App" in res["code"]
    assert db.load_run("r1")["status"] == "complete"
    assert set(db.load_run("r1")["agent_outputs"]) == {
        "vision_parser", "architect", "code_forge", "auditor", "accessibility", "vision_critic"}
