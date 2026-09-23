"""OpenCode collector. Go plan windows plus local spend history."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from .. import http as _http, log, model, parse
from ..providers import Env, iso_now
from ..spend import context as _spend_ctx
from ..spend import opencode_scan as _scan
from ..spend import tiles as _tiles

family = "opencode"
LABEL = "OpenCode"
URL = "https://opencode.ai/zen/go/v1/usage"
SESSION_MS = 5 * 60 * 60 * 1000
WEEK_MS = 7 * 24 * 60 * 60 * 1000
MONTH_MS = 30 * 24 * 60 * 60 * 1000
NOT_LOGGED_IN = "OpenCode not detected. Log in with OpenCode Go or use OpenCode locally first."
UNREADABLE = "Couldn't read OpenCode's auth.json. Check its file permissions or log into OpenCode Go again."
UNAUTHORIZED = "OpenCode Go key was rejected. Log into OpenCode Go again."
NO_SUBSCRIPTION = "No OpenCode Go subscription on this key."


def data_dir(env: Env) -> Path:
    override = (os.environ.get("OPENCODE_DATA_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if xdg:
        return Path(xdg).expanduser() / "opencode"
    return env.paths.home / ".local" / "share" / "opencode"


def auth_path(env: Env) -> Path:
    return data_dir(env) / "auth.json"


def read_key(env: Env) -> str:
    """The Go key, else empty. Raises when auth.json is unreadable."""
    path = auth_path(env)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except OSError as exc:
        raise model.CollectorError("auth", UNREADABLE) from exc
    try:
        found = json.loads(text)
    except ValueError as exc:
        raise model.CollectorError("auth", UNREADABLE) from exc
    if not isinstance(found, dict):
        raise model.CollectorError("auth", UNREADABLE)
    entry = found.get("opencode-go")
    if not isinstance(entry, dict):
        return ""
    key = entry.get("key")
    if not isinstance(key, str):
        return ""
    return key.strip()


def has_credentials(env: Env) -> bool:
    try:
        return bool(read_key(env))
    except model.CollectorError:
        return True


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="opencode", family=family, label=LABEL)]


def error_type(body: bytes) -> str | None:
    payload = _http.parse_json_object(body)
    if not isinstance(payload, dict):
        return None
    error = payload.get("error")
    if not isinstance(error, dict):
        return None
    text = str(error.get("type") or "").strip()
    return text or None


def _window(raw: Any, metric_id: str, period: int) -> model.Progress:
    if not isinstance(raw, dict):
        raise ValueError("invalid response")
    percent = parse.number(raw.get("percent"))
    if percent is None:
        raise ValueError("invalid response")
    resets = parse.parse_time(raw.get("resetsAt"))
    return model.Progress(
        metric_id=metric_id,
        used=parse.clamp_percent(percent),
        limit=100,
        resets_at=resets.isoformat() if resets else None,
        period_ms=period,
    )


def parse_windows(payload: Any) -> dict[str, model.Metric]:
    """Pure mapper: usage payload to the three Go meters."""
    if not isinstance(payload, dict) or "error" in payload:
        raise ValueError("invalid response")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ValueError("invalid response")
    return {
        "session": _window(usage.get("rolling"), "session", SESSION_MS),
        "weekly": _window(usage.get("weekly"), "weekly", WEEK_MS),
        "monthly": _window(usage.get("monthly"), "monthly", MONTH_MS),
    }


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    try:
        key = read_key(env)
    except model.CollectorError:
        raise
    if not key:
        raise model.CollectorError("auth", NOT_LOGGED_IN)
    try:
        reply = env.http.get(
            URL,
            headers={"Authorization": "Bearer " + key, "Accept": "application/json"},
            timeout=15,
        )
    except _http.HttpError as exc:
        if exc.status is not None:
            raise model.CollectorError(
                "status",
                f"Usage request failed (HTTP {exc.status}). Try again later.",
            )
        raise model.CollectorError(
            "transport", "Usage request failed. Check your connection.")
    if reply.status == 401:
        raise model.CollectorError("auth", UNAUTHORIZED)
    if reply.status == 403 and error_type(reply.body) == "EntitlementError":
        raise model.CollectorError("empty", NO_SUBSCRIPTION)
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status", f"Usage request failed (HTTP {reply.status}). Try again later.")
    try:
        metrics = parse_windows(_http.parse_json_object(reply.body))
    except ValueError:
        raise model.CollectorError("empty", "Usage response invalid. Try again later.")
    snap = model.Snapshot(card=card, plan="Go", fetched_at=iso_now(env), metrics=metrics)
    return _with_spend(card, env, snap, env.clock.now())


NOTE = "From your OpenCode logs"


def _with_spend(card: model.CardRef, env: Env, snap: model.Snapshot,
                now: dt.datetime) -> model.Snapshot:
    try:
        stamp = _spend_ctx.since_ts(env)
        found = _scan.scan(data_dir(env), stamp)
        if found is None:
            return snap
        metrics = dict(snap.metrics)
        _tiles.append_token_usage(
            found.series, metrics, now, estimated=False,
            unknown_by_day=found.unknown_by_day, model_usage=found.model_usage,
            model_note=NOTE)
        _tiles.append_trend(found.series, metrics, now, NOTE)
        return model.Snapshot(card=snap.card, plan=snap.plan,
                              fetched_at=snap.fetched_at, metrics=metrics,
                              error=snap.error)
    except Exception as exc:
        log.get_logger("plugin.opencode").warning("spend scan failed: %s", exc)
        return snap
