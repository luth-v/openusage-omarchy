"""Cursor credentials. State database tokens with SQLite write-back.

Linux port note: the macOS keychain candidate is omitted. Cursor on Linux
keeps its tokens in the state database, which is the source read here.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from ... import log, model, parse
from ...providers import Env

NOT_LOGGED_IN = "Not logged in. Sign in via Cursor app or run `agent login`."
SESSION_EXPIRED = "Session expired. Sign in via Cursor app or run `agent login`."
TOKEN_EXPIRED = "Token expired. Sign in via Cursor app or run `agent login`."


def db_path(env: Env) -> Path:
    return (
        env.paths.config_dir.parent / "Cursor" / "User" / "globalStorage" / "state.vscdb"
    )


def read_state(db: Path) -> dict[str, str]:
    if not db.is_file():
        return {}
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return {}
    out: dict[str, str] = {}
    try:
        conn.execute("PRAGMA query_only = ON")
        for key in (
            "cursorAuth/accessToken",
            "cursorAuth/refreshToken",
            "cursorAuth/stripeMembershipType",
        ):
            try:
                row = conn.execute(
                    "SELECT value FROM ItemTable WHERE key = ?", (key,)
                ).fetchone()
            except sqlite3.Error:
                continue
            if row and row[0] is not None:
                value = row[0]
                text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
                text = text.strip()
                if text:
                    out[key] = text
    finally:
        conn.close()
    return out


def write_state_token(db: Path, previous: str, token: str) -> bool:
    if not previous or not db.is_file():
        return False
    conn = sqlite3.connect(str(db), timeout=5)
    try:
        changed = conn.execute(
            "UPDATE ItemTable SET value = ? WHERE key = ? AND value = ?",
            (token, "cursorAuth/accessToken", previous),
        )
        conn.commit()
        return changed.rowcount == 1
    finally:
        conn.close()


def has_credentials(env: Env) -> bool:
    state = read_state(db_path(env))
    return bool(state.get("cursorAuth/accessToken") or state.get("cursorAuth/refreshToken"))


def token_subject(token: str | None) -> str | None:
    if not token:
        return None
    payload = parse.jwt_payload(token)
    if payload is None:
        return None
    sub = str(payload.get("sub") or "").strip()
    return sub or None


def token_expiry(token: str) -> dt.datetime | None:
    payload = parse.jwt_payload(token)
    if payload is None:
        return None
    exp = parse.number(payload.get("exp"))
    if exp is None:
        return None
    try:
        return dt.datetime.fromtimestamp(exp, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def needs_refresh(token: str | None, now: dt.datetime) -> bool:
    if not token:
        return True
    expires = token_expiry(token)
    if expires is None:
        return True
    return (expires - now).total_seconds() <= 5 * 60


def session_cookie(token: str) -> tuple[str, str] | None:
    subject = token_subject(token)
    if not subject:
        return None
    parts = subject.split("|")
    user_id = parts[1] if len(parts) > 1 else parts[0]
    if not user_id:
        return None
    return user_id, f"{user_id}%3A%3A{token}"


def save_access_token(env: Env, previous: str, token: str) -> bool:
    try:
        saved = write_state_token(db_path(env), previous, token)
    except (sqlite3.Error, OSError):
        log.get_logger("auth.cursor").error(
            "failed to persist rotated access token to the Cursor state DB; "
            "using it for this session only"
        )
        return False
    if saved:
        log.get_logger("auth.cursor").info("rotated (source=cursor)")
    return saved
