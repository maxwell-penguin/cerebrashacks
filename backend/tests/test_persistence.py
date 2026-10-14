import pytest

import db


@pytest.fixture(autouse=True)
def _db(tmp_path, monkeypatch):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "runs.db"))
    db.init_db()


def test_init_db_creates_tables():
    with db._connect() as conn:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"runs", "agent_outputs"} <= names


def test_save_and_load_run_round_trip():
    db.save_run("r1", "running")
    run = db.load_run("r1")
    assert run["run_id"] == "r1" and run["status"] == "running" and run["agent_outputs"] == {}
    assert run["created_at"] <= run["updated_at"]


def test_agent_output_round_trip():
    db.save_run("r1", "running")
    db.save_agent_output("r1", "architect", {"component_tree": "App", "n": [1, 2]})
    assert db.load_run("r1")["agent_outputs"] == {"architect": {"component_tree": "App", "n": [1, 2]}}


def test_multiple_agent_outputs_all_load():
    db.save_run("r1", "running")
    db.save_run("r2", "running")
    for name in ("vision_parser", "architect", "code_forge"):
        db.save_agent_output("r1", name, {"agent": name})
    db.save_agent_output("r2", "architect", {"agent": "other"})
    outs = db.load_run("r1")["agent_outputs"]
    assert list(outs) == ["vision_parser", "architect", "code_forge"]
    assert outs["code_forge"] == {"agent": "code_forge"}


def test_load_unknown_run_is_none():
    assert db.load_run("nope") is None


def test_status_update_reflected_on_reload():
    db.save_run("r1", "running")
    created = db.load_run("r1")["created_at"]
    db.save_run("r1", "complete")
    run = db.load_run("r1")
    assert run["status"] == "complete" and run["created_at"] == created
