"""Structured JSON logging on top of stdlib `logging`.

Responsibilities: a JSON formatter, a `log_event` helper, and two context variables (`run_id_var`,
`agent_var`). Code sets them once per run or agent call, and every log line emitted in that
context, including library logs, carries them automatically.

Interacts with: main.py (configures logging, sets the run id per WebSocket connection) and
orchestrator.py (sets the agent name and emits agent and pipeline events).
"""

from __future__ import annotations

import json
import logging
import os
import sys
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any

run_id_var: ContextVar[str | None] = ContextVar("run_id", default=None)
agent_var: ContextVar[str | None] = ContextVar("agent_name", default=None)


class JsonFormatter(logging.Formatter):
    """Logging formatter that renders each record as one JSON object, adding run_id and agent_name from context variables."""
    def format(self, record: logging.LogRecord) -> str:
        """Return the record as a JSON string with timestamp (ISO 8601 UTC), level, event and any contextual or extra fields."""
        out: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "event": getattr(record, "event", None) or "log",  # foreign records (e.g. SDK retries)
        }
        if not hasattr(record, "event"):
            out["message"] = record.getMessage()
            out["logger"] = record.name
        for key, var in (("run_id", run_id_var), ("agent_name", agent_var)):
            if var.get() is not None:
                out[key] = var.get()
        out.update(getattr(record, "fields", {}))
        if record.exc_info:
            out["exc"] = self.formatException(record.exc_info)
        return json.dumps(out, default=str)


def log_event(logger: logging.Logger, event: str, level: int = logging.INFO, **fields: Any) -> None:
    """Log a structured event.

    Args:
        logger: Logger to write to.
        event: Short snake_case event name, e.g. "agent_complete".
        level: Logging level.
        **fields: Extra fields merged into the JSON line (e.g. duration_ms, error).
    """
    logger.log(level, event, extra={"event": event, "fields": fields})


def configure_logging() -> None:
    """Attach the JSON handler to the root logger (stdout, level from LOG_LEVEL); idempotent and leaves other handlers alone."""
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return  # idempotent; leave other handlers (pytest's caplog) alone
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
