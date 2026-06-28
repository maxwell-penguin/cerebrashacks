"""Pipeline feature flags from environment."""

from __future__ import annotations

import os


def env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


RUN_AUDIT_DEFAULT = env_bool("RUN_AUDIT_DEFAULT", True)
RUN_ACCESSIBILITY_DEFAULT = env_bool("RUN_ACCESSIBILITY_DEFAULT", True)
