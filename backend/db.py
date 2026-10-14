"""SQLite persistence so a dropped WebSocket client can resume a run by run_id."""

from __future__ import annotations

import json
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
