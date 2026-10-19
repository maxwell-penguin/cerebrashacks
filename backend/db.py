"""SQLite persistence for pipeline runs.

Responsibilities:
  * Store each run's status and each agent's output as it completes, so a client whose WebSocket
    dropped can resume with its run_id.
  * Record one row per agent attempt (success, failure, duration) that /metrics aggregates.
  * Aggregate those tables into the /metrics payload.

Tables: `runs`, `agent_outputs` (successful outputs, keyed by run and agent) and `agent_events`
(every attempt). The file lives at the DB_PATH environment variable, default backend/runs.db.

Interacts with: main.py (init at startup, resume, /metrics, /health) and orchestrator.py (writes
status, outputs and attempt timings).
"""

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
    """Create the SQLite file at DB_PATH and the runs, agent_events and agent_outputs tables if missing; safe to call repeatedly."""
    with _connect() as conn:
        # agent_events is separate from agent_outputs on purpose: agent_outputs has one row per (run, agent) and only
        # holds successes (it is what resume replays), while /metrics needs every attempt, including failures,
        # with durations.
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
    """Insert a run or update its status; `created_at` is set on first insert, `updated_at` on every call."""
    now = time.time()
    with _connect() as conn:
        conn.execute(
            "INSERT INTO runs (run_id, status, created_at, updated_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(run_id) DO UPDATE SET status = excluded.status, updated_at = excluded.updated_at",
            (run_id, status, now, now),
        )


# "_request" is a reserved pseudo-agent name: the original WebSocket payload is stored as an agent_outputs row
# so resume can re-run later agents with the same inputs, without a separate table.
# TODO: nothing ever deletes old runs, and "_request" rows can hold full uploaded images, so the
# database grows without bound; add a retention sweep (e.g. delete runs older than N days).
def save_agent_output(run_id: str, agent_name: str, output: dict[str, Any]) -> None:
    # REPLACE, not plain insert: a resumed run may redo an agent.
    """Store one agent's output for a run as JSON, replacing any earlier output for the same agent.

    Args:
        run_id: Run the output belongs to.
        agent_name: Agent name, or the reserved pseudo-agent "_request" (the saved WebSocket request).
        output: JSON-serialisable dict.
    """
    with _connect() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO agent_outputs (run_id, agent_name, output, completed_at) VALUES (?, ?, ?, ?)",
            (run_id, agent_name, json.dumps(output), time.time()),
        )


def load_run(run_id: str) -> dict[str, Any] | None:
    """Load a run and everything saved for it.

    Returns:
        A dict with run_id, status, created_at, updated_at and `agent_outputs` (agent name -> output,
        oldest first, including "_request" if present), or None if the run is unknown.
    """
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
    """Compute the /metrics numbers from the runs and agent_events tables.

    Returns:
        Run counts by status, per-agent success and failure counts, and per-agent p50/p95 latency in
        ms. Latency uses successful attempts only. `circuit_breaker_state` is added by the caller.
    """
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
        # TODO: overcounts. A run whose client dropped stays "pending"/"running" forever (that is what lets it
        # resume), so it is counted as in progress; track liveness or expire stale runs.
        "runs_in_progress": by_status.get("pending", 0) + by_status.get("running", 0),
        "agent_success_counts": ok_counts,
        "agent_failure_counts": fail_counts,
        "agent_p50_latency_ms": {a: round(_percentile(v, 0.5), 1) for a, v in latencies.items()},
        "agent_p95_latency_ms": {a: round(_percentile(v, 0.95), 1) for a, v in latencies.items()},
    }
