"""Collector seam. Collectors are pure fetch functions, not processes.

Each collector returns typed snapshots. The engine owns the cache and is the
only writer. Collectors never write cache, state.json, or credential logs.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Any, Protocol

from .. import http as _http
from .. import model, paths


class Clock(Protocol):
    def now(self) -> dt.datetime: ...


class SystemClock:
    def now(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)


@dataclass(frozen=True)
class Env:
    http: _http.HttpClient
    clock: Clock
    paths: paths.Paths
    settings: Any = None  # optional resolver with .get(key, fallback)


class SettingsLike(Protocol):
    def get(self, key: str, fallback: Any = None) -> Any: ...


class Collector(Protocol):
    family: str

    def cards(self, env: Env) -> list[model.CardRef]: ...

    def fetch(self, card: model.CardRef, env: Env) -> model.Snapshot: ...

    def has_credentials(self, env: Env) -> bool: ...


def registry() -> list:
    from . import antigravity, claude, codex, copilot, cursor, devin, grok
    from . import ollama, opencode, openrouter, zai

    modules = {
        "claude": claude,
        "codex": codex,
        "cursor": cursor,
        "antigravity": antigravity,
        "copilot": copilot,
        "devin": devin,
        "grok": grok,
        "ollama": ollama,
        "opencode": opencode,
        "openrouter": openrouter,
        "zai": zai,
    }
    return [modules[family] for family in (
        "claude", "codex", "cursor", "antigravity", "copilot", "devin",
        "grok", "ollama", "opencode", "openrouter", "zai",
    )]


def iso_now(env: Env) -> str:
    return env.clock.now().isoformat()
