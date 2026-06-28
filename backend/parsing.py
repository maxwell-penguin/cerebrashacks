"""JSON extraction helpers for LLM outputs."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from cerebras_client import CerebrasClient

REPAIR_SYSTEM = (
    "Your previous response was not valid JSON. "
    "Return ONLY the corrected valid JSON object, with no markdown fences or commentary."
)

REPAIR_RAW_MAX_CHARS = 12_000

BACKEND_DIR = Path(__file__).resolve().parent
JSON_DEBUG_DIR = BACKEND_DIR / "tmp" / "auditor_debug"

log = logging.getLogger(__name__)


def _json_debug_enabled() -> bool:
    return os.environ.get("AUDITOR_JSON_DEBUG", "").lower() in ("1", "true", "yes")


def _json_debug_write(agent: str, stage: str, content: str) -> None:
    if not _json_debug_enabled():
        return
    JSON_DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    ts = int(time.time() * 1000)
    path = JSON_DEBUG_DIR / f"{ts}_{agent}_{stage}.txt"
    path.write_text(content, encoding="utf-8")
    preview = content[:500].replace("\n", "\\n")
    log.warning("json_debug agent=%s stage=%s file=%s preview=%s", agent, stage, path.name, preview)


def strip_code_fences(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json|jsx|javascript|tsx?)?\s*\n?(.*?)\n?```\s*$", text, re.DOTALL)
    if fence:
        return fence.group(1).strip()
    return text


def extract_json(text: str) -> dict[str, Any]:
    cleaned = strip_code_fences(text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        return json.loads(cleaned[start : end + 1])

    raise ValueError(f"Could not parse JSON from model output: {cleaned[:200]}...")


async def extract_json_with_repair(
    raw: str,
    client: CerebrasClient,
    *,
    debug_agent: str | None = None,
) -> dict[str, Any]:
    """Parse JSON from model output; on failure, one repair call then re-parse."""
    agent = debug_agent or "unknown"
    if debug_agent and _json_debug_enabled():
        _json_debug_write(agent, "raw", raw)

    parse_error: BaseException | None = None
    try:
        return extract_json(raw)
    except (json.JSONDecodeError, ValueError) as exc:
        parse_error = exc
        if debug_agent:
            _json_debug_write(agent, "parse_error", f"{type(exc).__name__}: {exc}")

    from cerebras_client import build_text_messages

    truncated = raw if len(raw) <= REPAIR_RAW_MAX_CHARS else raw[:REPAIR_RAW_MAX_CHARS] + "\n…(truncated)"
    user = (
        f"Here is the parse error: {parse_error}\n\n"
        f"Here is your previous output:\n{truncated}\n\n"
        "Return ONLY the corrected valid JSON, nothing else."
    )
    if debug_agent:
        _json_debug_write(agent, "repair_attempted", f"yes\n\nparse_error={parse_error}\n\nprompt_user=\n{user}")

    repaired = await client.acall(
        build_text_messages(REPAIR_SYSTEM, user),
        max_tokens=4096,
        temperature=0.0,
    )
    if debug_agent:
        _json_debug_write(agent, "repair_raw", repaired)

    try:
        return extract_json(repaired)
    except (json.JSONDecodeError, ValueError) as exc:
        if debug_agent:
            _json_debug_write(agent, "repair_parse_error", f"{type(exc).__name__}: {exc}")
        raise ValueError(f"JSON repair failed: {exc}") from exc


def extract_code(text: str) -> str:
    cleaned = strip_code_fences(text)
    if cleaned.startswith("import ") or cleaned.startswith("function ") or cleaned.startswith("export "):
        return cleaned
    if "<" in cleaned and ">" in cleaned:
        return cleaned
    return cleaned


def extract_code_defensive(text: str) -> str:
    """
    Extract code block from text defensively.
    Looks for the first ```tsx or ```jsx or ``` or ```html block.
    If not found, searches for a block of code starting with import/export/function or containing JSX syntax.
    If no code block can be verified, raises ValueError.
    """
    text = text.strip()
    
    # 1. Search for markdown code block fences using regex search
    pattern = r"```(?:tsx|jsx|javascript|js|html)?\s*\n(.*?)\n```"
    match = re.search(pattern, text, re.DOTALL)
    if match:
        code = match.group(1).strip()
        if code:
            return code
            
    # 2. Try simple strip_code_fences
    cleaned = strip_code_fences(text)
    if cleaned != text:
        return cleaned
        
    # 3. If no fences, check if the raw text looks like code (starts with imports, functions, exports, or has JSX)
    if cleaned.startswith("import ") or cleaned.startswith("function ") or cleaned.startswith("export ") or cleaned.startswith("const "):
        return cleaned
        
    if "<" in cleaned and ">" in cleaned:
        return cleaned
        
    # 4. If nothing else, raise ValueError (so it is treated as an error iteration)
    raise ValueError("Failed to extract valid code block from LLM response.")
