"""Versioned, validated commands sent to the daemon over stdin."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, ClassVar, TypeAlias

from .. import secrets as _secrets

PROTOCOL_VERSION = 1


class InvalidCommand(Exception):
    pass


@dataclass(frozen=True)
class Refresh:
    card_id: str | None = None
    force: bool = False
    cmd: ClassVar[str] = "refresh"


@dataclass(frozen=True)
class ClaimReset:
    card_id: str
    expiry: str | None = None
    request_id: str | None = None
    cmd: ClassVar[str] = "claimReset"


@dataclass(frozen=True)
class SetKey:
    provider: str
    value: str = field(repr=False)
    cmd: ClassVar[str] = "setKey"


@dataclass(frozen=True)
class DeleteKey:
    provider: str
    cmd: ClassVar[str] = "deleteKey"


@dataclass(frozen=True)
class CheckUpdate:
    cmd: ClassVar[str] = "checkUpdate"


@dataclass(frozen=True)
class SnoozeUpdate:
    version: str
    cmd: ClassVar[str] = "snoozeUpdate"


@dataclass(frozen=True)
class InstallUpdate:
    cmd: ClassVar[str] = "installUpdate"


Command: TypeAlias = (Refresh | ClaimReset | SetKey | DeleteKey |
                      CheckUpdate | SnoozeUpdate | InstallUpdate)


def _fields(raw: dict, allowed: set[str]) -> None:
    if set(raw) - allowed - {"v", "cmd"}:
        raise InvalidCommand("unexpected command field")


def _nonempty(raw: dict, key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str) or not value.strip():
        raise InvalidCommand(f"bad {key}")
    return value


def _optional(raw: dict, key: str) -> str | None:
    return _nonempty(raw, key) if key in raw and raw[key] is not None else None


def _refresh(raw: dict) -> Refresh:
    _fields(raw, {"cardId", "force"})
    if "cardId" in raw and raw["cardId"] is None:
        raise InvalidCommand("bad cardId")
    if not isinstance(raw.get("force", False), bool):
        raise InvalidCommand("bad force")
    return Refresh(_optional(raw, "cardId"), raw.get("force", False))


def _claim(raw: dict) -> ClaimReset:
    _fields(raw, {"cardId", "expiry", "requestId"})
    return ClaimReset(_nonempty(raw, "cardId"), _optional(raw, "expiry"),
                      _optional(raw, "requestId"))


def _set_key(raw: dict) -> SetKey:
    _fields(raw, {"provider", "value"})
    provider = _nonempty(raw, "provider")
    if provider not in _secrets.PROVIDERS:
        raise InvalidCommand("bad provider")
    return SetKey(provider, _nonempty(raw, "value"))


def _delete_key(raw: dict) -> DeleteKey:
    _fields(raw, {"provider"})
    provider = _nonempty(raw, "provider")
    if provider not in _secrets.PROVIDERS:
        raise InvalidCommand("bad provider")
    return DeleteKey(provider)


def _snooze(raw: dict) -> SnoozeUpdate:
    _fields(raw, {"version"})
    return SnoozeUpdate(_nonempty(raw, "version"))


def _no_args(raw: dict, kind: type) -> Command:
    _fields(raw, set())
    return kind()


PARSERS = {
    "refresh": _refresh,
    "claimReset": _claim,
    "setKey": _set_key,
    "deleteKey": _delete_key,
    "checkUpdate": lambda raw: _no_args(raw, CheckUpdate),
    "snoozeUpdate": _snooze,
    "installUpdate": lambda raw: _no_args(raw, InstallUpdate),
}


def parse_line(line: str) -> Command | None:
    if not line.strip():
        return None
    try:
        raw = json.loads(line)
    except ValueError as exc:
        raise InvalidCommand(f"not JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise InvalidCommand("command must be an object")
    if raw.get("v") != PROTOCOL_VERSION:
        raise InvalidCommand("unsupported protocol")
    parser = PARSERS.get(raw.get("cmd")) if isinstance(raw.get("cmd"), str) else None
    if parser is None:
        raise InvalidCommand("unknown command")
    return parser(raw)


def describe(command: Command) -> dict[str, Any]:
    out: dict[str, Any] = {"v": PROTOCOL_VERSION, "cmd": command.cmd}
    if isinstance(command, Refresh):
        out.update(cardId=command.card_id, force=command.force)
    elif isinstance(command, ClaimReset):
        out.update(cardId=command.card_id, expiry=command.expiry,
                   requestId=command.request_id)
    elif isinstance(command, SetKey):
        out.update(provider=command.provider, value="[REDACTED]")
    elif isinstance(command, DeleteKey):
        out["provider"] = command.provider
    elif isinstance(command, SnoozeUpdate):
        out["version"] = command.version
    return out
