"""Codex credentials. Auth files across homes; no keychain on Linux.

The Codex CLI on Linux keeps its login in auth.json only, so the macOS
keychain fallback is omitted. Swap cards are read-only: only the Codex CLI
may rotate a shared refresh token.
"""

from __future__ import annotations

import datetime as dt
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ... import credentials as _cas, log, parse
from ...providers import Env

NOT_LOGGED_IN = "Not logged in. Run `codex` to authenticate."
SESSION_EXPIRED = "Session expired. Run `codex` to log in again."
TOKEN_CONFLICT = "Token conflict. Run `codex` to log in again."
TOKEN_REVOKED = "Token revoked. Run `codex` to log in again."
TOKEN_EXPIRED = "Token expired. Run `codex` to log in again."
USAGE_API_KEY = "Usage not available for API key."
REFRESH_WINDOW_S = 5 * 60


@dataclass
class Tokens:
    access_token: str = ""
    refresh_token: str = ""
    id_token: str = ""
    account_id: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> "Tokens":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            access_token=str(raw.get("access_token") or ""),
            refresh_token=str(raw.get("refresh_token") or ""),
            id_token=str(raw.get("id_token") or ""),
            account_id=str(raw.get("account_id") or "").strip(),
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {}
        if self.access_token:
            out["access_token"] = self.access_token
        if self.refresh_token:
            out["refresh_token"] = self.refresh_token
        if self.id_token:
            out["id_token"] = self.id_token
        if self.account_id:
            out["account_id"] = self.account_id
        return out


@dataclass
class Auth:
    tokens: Tokens | None = None
    last_refresh: str = ""
    api_key: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> "Auth | None":
        if not isinstance(raw, dict):
            return None
        tokens = raw.get("tokens")
        return cls(
            tokens=Tokens.from_dict(tokens) if isinstance(tokens, dict) else None,
            last_refresh=str(raw.get("last_refresh") or ""),
            api_key=str(raw.get("OPENAI_API_KEY") or ""),
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {}
        if self.tokens is not None:
            out["tokens"] = self.tokens.to_dict()
        if self.last_refresh:
            out["last_refresh"] = self.last_refresh
        if self.api_key:
            out["OPENAI_API_KEY"] = self.api_key
        return out


@dataclass
class Credential:
    auth: Auth
    path: str = ""
    read_only: bool = False

    @property
    def usable(self) -> bool:
        return bool(self.auth.tokens and self.auth.tokens.access_token)


def parse_auth(text: str) -> Auth | None:
    decoded = parse.decode_json_hex(text)
    if decoded is None:
        return None
    return Auth.from_dict(decoded)


def codex_home() -> str:
    return (os.environ.get("CODEX_HOME") or "").strip()


def auth_paths(extra_homes: list[str] | None = None) -> list[str]:
    homes: list[str] = []
    override = codex_home()
    if override:
        homes.append(override)
    else:
        homes.extend(["~/.config/codex", "~/.codex"])
    homes.extend(extra_homes or [])
    seen: set[str] = set()
    out: list[str] = []
    for home in homes:
        path = str(Path(home).expanduser() / "auth.json")
        if path not in seen:
            seen.add(path)
            out.append(path)
    return out


def load_auth_at(path: str) -> Credential | None:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return None
    found = parse_auth(text)
    if found is None:
        return None
    if not found.tokens and not found.api_key:
        return None
    if found.tokens and not found.tokens.access_token and not found.api_key:
        return None
    return Credential(auth=found, path=path)


def load_candidates(extra_homes: list[str] | None = None) -> list[Credential]:
    out: list[Credential] = []
    for path in auth_paths(extra_homes):
        found = load_auth_at(path)
        if found is not None:
            out.append(found)
    return out


def access_expires_at(token: str) -> dt.datetime | None:
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


def needs_refresh(auth_data: Auth, now: dt.datetime) -> bool:
    token = auth_data.tokens.access_token if auth_data.tokens else ""
    if token:
        expires = access_expires_at(token)
        if expires is not None:
            return (expires - now).total_seconds() <= REFRESH_WINDOW_S
    if not auth_data.last_refresh:
        return False
    moment = parse.parse_time(auth_data.last_refresh)
    if moment is None:
        return False
    return (now - moment).total_seconds() > 8 * 24 * 60 * 60


def save(cred: Credential) -> None:
    if cred.read_only or not cred.path:
        raise ValueError(TOKEN_CONFLICT)

    def _apply(payload: Any) -> Any | None:
        if not isinstance(payload, dict):
            return None
        merged = dict(payload)
        merged.update(cred.auth.to_dict())
        return merged

    _cas.cas_update_json(
        Path(cred.path), _apply, "codex", log.get_logger("auth.codex")
    )
