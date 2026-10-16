import pytest
from fastapi.testclient import TestClient

import db
import main


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("DB_PATH", str(tmp_path / "runs.db"))
    db.init_db()
    main.limiter.reset()
    yield
    main.limiter.reset()


def client(ip="1.1.1.1"):
    return TestClient(main.app, client=(ip, 50000))


def hit_generate(c):
    # No image and no description => 400 before any model call, but the request still counts.
    return c.post("/generate", data={})


def test_11th_generate_request_is_429():
    c = client()
    assert [hit_generate(c).status_code for _ in range(10)] == [400] * 10
    assert hit_generate(c).status_code == 429


def test_429_shape():
    c = client()
    for _ in range(10):
        hit_generate(c)
    r = hit_generate(c)
    body = r.json()
    assert body["error"] == "rate_limit_exceeded"
    assert isinstance(body["retry_after_seconds"], int) and 1 <= body["retry_after_seconds"] <= 61
    assert set(body) == {"error", "retry_after_seconds"}
    assert r.headers["retry-after"] == str(body["retry_after_seconds"])


def test_different_ips_have_separate_limits():
    a, b = client("1.1.1.1"), client("2.2.2.2")
    for _ in range(10):
        hit_generate(a)
    assert hit_generate(a).status_code == 429
    assert hit_generate(b).status_code == 400


def test_websocket_limit_is_5_per_minute():
    c = client()
    for _ in range(5):
        with c.websocket_connect("/ws") as ws:
            assert ws.receive_json()["type"] == "run_started"
    with c.websocket_connect("/ws") as ws:
        assert ws.receive_json()["error"] == "rate_limit_exceeded"


def test_health_reports_db_and_breaker(monkeypatch):
    body = client().get("/health").json()
    assert body["status"] == "ok" and body["db"] == "ok" and body["circuit_breaker"] == "CLOSED"
    monkeypatch.setenv("DB_PATH", "/nonexistent-dir/runs.db")
    body = client().get("/health").json()
    assert body["status"] == "degraded" and body["db"] == "error"
