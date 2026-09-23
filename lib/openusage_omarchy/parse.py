"""Shared parsing chores. One definition so providers cannot drift.

Mirrors upstream ProviderParse: permissive numbers, JWT payloads, ISO-8601
with Claude/Codex timestamp shapes, percent clamping, cents, title case.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import re
from typing import Any

_WS = re.compile(r"\s+")


def number(value: Any) -> float | None:
    """JSON numbers and numeric strings. Rejects bools and non-finite."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    if isinstance(value, str):
        try:
            result = float(value.strip())
        except (TypeError, ValueError):
            return None
        return result if result == result and abs(result) != float("inf") else None
    return None


def clamp_percent(value: float) -> float:
    if value != value or abs(value) == float("inf"):
        return 0.0
    return min(100.0, max(0.0, value))


def parse_bool(value: Any) -> bool | None:
    """Permissive boolean read. True/False, nonzero numbers, true/1/false/0."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value != value or abs(value) == float("inf"):
            return None
        return value != 0
    if isinstance(value, str):
        text = value.strip().lower()
        if text in ("true", "1"):
            return True
        if text in ("false", "0"):
            return False
    return None


def unwrap_go_keyring(raw: str) -> str | None:
    """Unwrap a go-keyring-base64 value, else the trimmed text itself."""
    import base64

    text = raw.strip()
    prefix = "go-keyring-base64:"
    if text.startswith(prefix):
        encoded = text[len(prefix):].strip()
        try:
            decoded = base64.b64decode(encoded, validate=True).decode("utf-8")
        except (ValueError, UnicodeError):
            return None
        text = decoded.strip()
    return text or None


def cents_to_dollars(cents: float) -> float:
    return round(cents) / 100.0


def jwt_payload(token: str) -> dict[str, Any] | None:
    parts = token.split(".")
    if len(parts) < 2:
        return None
    payload = parts[1].replace("-", "+").replace("_", "/")
    payload += "=" * (-len(payload) % 4)
    try:
        raw = base64.b64decode(payload, validate=False)
        decoded = json.loads(raw.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeError):
        return None
    return decoded if isinstance(decoded, dict) else None


def parse_time(raw: Any) -> dt.datetime | None:
    """ISO-8601 plus Claude/Codex shapes (space separator, UTC suffix)."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith(" UTC"):
        text = text[:-4] + "Z"
    if " " in text and "T" not in text:
        text = text.replace(" ", "T", 1)
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def parse_epoch(value: Any) -> dt.datetime | None:
    """Epoch seconds or milliseconds to an aware datetime."""
    moment = number(value)
    if moment is None:
        return None
    seconds = moment / 1000.0 if abs(moment) >= 1e10 else moment
    try:
        return dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def reset_date(value: Any) -> dt.datetime | None:
    moment = parse_time(value)
    if moment is not None:
        return moment
    return parse_epoch(value)


def title_cased(text: str, lower_tail: bool = False) -> str:
    words = [word for word in _WS.split(text.replace("_", " ").strip()) if word]
    out = []
    for word in words:
        head = word[:1].upper()
        tail = word[1:].lower() if lower_tail else word[1:]
        out.append(head + tail)
    return " ".join(out)


def decode_json_hex(text: str) -> Any | None:
    """Plain JSON, else hex-encoded JSON (optional 0x prefix)."""
    try:
        return json.loads(text)
    except (ValueError, UnicodeError):
        pass
    blob = text.strip()
    if blob[:2].lower() == "0x":
        blob = blob[2:]
    blob = "".join(blob.split())
    if not blob or len(blob) % 2 or any(c not in "0123456789abcdefABCDEF" for c in blob):
        return None
    try:
        decoded = bytes.fromhex(blob).decode("utf-8")
    except (ValueError, UnicodeError):
        return None
    try:
        return json.loads(decoded)
    except (ValueError, UnicodeError):
        return None
