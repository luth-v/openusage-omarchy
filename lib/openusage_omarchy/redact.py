"""Secret redaction. Pure functions; the log handler applies them to each line.

Rules mirror upstream logging.md: a sensitive value becomes ``first4...last4``
(or ``[REDACTED]`` when too short), home paths become ``[PATH]``.
"""

from __future__ import annotations

import os
import re
from typing import Any

_JWT = re.compile(r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b")
_TOKEN_WORD = re.compile(r"\b(sk-[A-Za-z0-9_-]{4,}|xox[bap]-[A-Za-z0-9-]+)\b")
_BEARER = re.compile(r"(Bearer\s+)([A-Za-z0-9._~+/-]{6,}={0,2})", re.IGNORECASE)
_PARAM = re.compile(
    r"((?:api[_-]?key|access[_-]?token|refresh[_-]?token|session[_-]?token|token|key|secret|password|passwd|pwd)\s*[:=]\s*)([^\s&;\"']{4,})",
    re.IGNORECASE,
)
_USERINFO = re.compile(r"(://)([^/\s:@]+:[^/\s@]+)@")
_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9.-]{1,253}\.[A-Za-z]{2,}\b")
_QUERY_SECRET = re.compile(r"([?&](?:key|token|api_key|access_token)[^=]*=)([^&\s]*)", re.IGNORECASE)


def mask_value(value: str) -> str:
    if len(value) > 12:
        return f"{value[:4]}...{value[-4:]}"
    return "[REDACTED]"


def _mask_match(match: "re.Match[str]") -> str:
    return mask_value(match.group(0))


def _mask_group(match: "re.Match[str]") -> str:
    return match.group(1) + mask_value(match.group(2))


def redact_text(text: str, home: str | None = None) -> str:
    out = _JWT.sub(_mask_match, text)
    out = _TOKEN_WORD.sub(_mask_match, out)
    out = _BEARER.sub(_mask_group, out)
    out = _PARAM.sub(_mask_group, out)
    out = _USERINFO.sub(lambda m: m.group(1) + "[REDACTED]@", out)
    out = _QUERY_SECRET.sub(_mask_group, out)
    out = _EMAIL.sub("[EMAIL]", out)
    base = home if home is not None else os.path.expanduser("~")
    if base and base != "/":
        out = out.replace(base, "[PATH]")
    return out


def redact_command(command: Any) -> Any:
    """Deep copy of a parsed command with credential fields masked by key."""
    if isinstance(command, dict):
        return {
            key: ("[REDACTED]" if key == "value" else redact_command(val))
            for key, val in command.items()
        }
    if isinstance(command, list):
        return [redact_command(item) for item in command]
    if isinstance(command, str):
        return redact_text(command)
    return command
