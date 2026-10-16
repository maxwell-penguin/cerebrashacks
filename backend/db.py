"""SQLite persistence so a dropped WebSocket client can resume a run by run_id."""

from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = Path(__file__).parent / "runs.db"


def _connect() -> sqlite3.Connection:
    # Connection per call: sqlite3 connections aren't shareable across threads.
    # ponytail: sync writes on the event loop; tiny rows, move to a thread if it shows up in latency.
    return sqlite3.connect(os.environ.get("DB_PATH", str(DEFAULT_DB_PATH)), timeout=5)


def init_db() -> None:
    with _connect() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, status TEXT, created_at REAL, updated_at REAL
            );
            CREATE TABLE IF NOT EXISTS agent_events (
                run_id TEXT, agent_name TEXT, ok INTEGER, duration_ms REAL, at REAL
            );
            CREATE TABLE IF NOT EXISTS agent_outputs (
                run_id TEXT, agent_name TEXT, output TEXT, completed_at REAL,
                PRIMARY KEY (run_id, agent_name)
            );
            """
        )


def save_run(run_id: str, status: str) -> None:
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
            (run_id, status, now, now),
        )


def save_agent_output(run_id: str, agent_name: str, output: dict[str, Any]) -> None:
    # REPLACE, not plain insert: a resumed run may redo an agent.
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_outputs (run_id, agent_name, output, completed_at) VALUES (?, ?, ?, ?)",
            (run_id, agent_name, json.dumps(output), time.time()),
        )


def load_run(run_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            "SELECT run_id, status, created_at, updated_at FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        outputs = conn.execute(
            "SELECT agent_name, output FROM agent_outputs WHERE run_id = ? ORDER BY completed_at", (run_id,)
        ).fetchall()
    return {
        "run_id": row[0],
        "status": row[1],
        "created_at": row[2],
        "updated_at": row[3],
        "agent_outputs": {name: json.loads(out) for name, out in outputs},
    }


def record_agent_event(run_id: str, agent_name: str, ok: bool, duration_ms: float) -> None:
    """One row per agent attempt. agent_outputs only ever holds successes, so failures and latency live here."""
    with _connect() as conn:
        conn.execute(
            "INSERT INTO agent_events (run_id, agent_name, ok, duration_ms, at) VALUES (?, ?, ?, ?, ?)",
            (run_id, agent_name, int(ok), duration_ms, time.time()),
        )


def _percentile(sorted_vals: list[float], p: float) -> float:
    return sorted_vals[max(0, math.ceil(p * len(sorted_vals)) - 1)]  # nearest-rank


def compute_metrics() -> dict[str, Any]:
    with _connect() as conn:
        by_status = dict(conn.execute("SELECT status, COUNT(*) FROM runs GROUP BY status"))
        events = conn.execute("SELECT agent_name, ok, duration_ms FROM agent_events").fetchall()
    ok_counts: dict[str, int] = {}
    fail_counts: dict[str, int] = {}
    latencies: dict[str, list[float]] = {}
    for agent, ok, ms in events:
        (ok_counts if ok else fail_counts)[agent] = (ok_counts if ok else fail_counts).get(agent, 0) + 1
        if ok:
            latencies.setdefault(agent, []).append(ms)  # successes only: failures are mostly timeouts
    for vals in latencies.values():
        vals.sort()
    return {
        "runs_total": sum(by_status.values()),
        "runs_complete": by_status.get("complete", 0),
        "runs_failed": by_status.get("failed", 0),
        "runs_in_progress": by_status.get("pending", 0) + by_status.get("running", 0),
        "agent_success_counts": ok_counts,
        "agent_failure_counts": fail_counts,
        "agent_p50_latency_ms": {a: round(_percentile(v, 0.5), 1) for a, v in latencies.items()},
        "agent_p95_latency_ms": {a: round(_percentile(v, 0.95), 1) for a, v in latencies.items()},
    }
