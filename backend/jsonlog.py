"""Structured JSON logging on stdlib logging. run_id / agent_name ride along via contextvars."""

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
    def format(self, record: logging.LogRecord) -> str:
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
    logger.log(level, event, extra={"event": event, "fields": fields})


def configure_logging() -> None:
    root = logging.getLogger()
    if any(isinstance(h.formatter, JsonFormatter) for h in root.handlers):
        return  # idempotent; leave other handlers (pytest's caplog) alone
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.addHandler(handler)
    root.setLevel(os.environ.get("LOG_LEVEL", "INFO").upper())
