"""Devin collector. Quotas from the CLI credentials or the Devin app login.

Sources in order: ``~/.local/share/devin/credentials.toml``, then the app's
local state database. On Linux the app database lives under the XDG config
dir (upstream knows only the macOS path; same file name). A 401/403 moves to
the next source instead of refreshing: Devin has no token refresh.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

from .. import http as _http, log, model, parse
from ..providers import Env, iso_now

family = "devin"
LABEL = "Devin"
SERVICE = "exa.seat_management_pb.SeatManagementService"
COMPAT_VERSION = "1.108.2"
DEFAULT_SERVER = "https://server.codeium.com"
DAY_MS = 24 * 60 * 60 * 1000
WEEK_MS = 7 * DAY_MS
NOT_LOGGED_IN = "Run devin auth login or sign in to Devin and try again."
QUOTA_UNAVAILABLE = "Devin quota data unavailable. Try again later."


def credentials_path(env: Env) -> Path:
    return env.paths.home / ".local" / "share" / "devin" / "credentials.toml"


def app_db_path(env: Env) -> Path:
    return (
        env.paths.config_dir.parent / "Devin" / "User" / "globalStorage"
        / "state.vscdb"
    )


def read_toml_string(text: str, key: str) -> str | None:
    for line in text.splitlines():
        parts = line.split("=", 1)
        if len(parts) != 2 or parts[0].strip() != key:
            continue
        value = parts[1].strip()
        if not value:
            return None
        if value[0] in ("\"", "'"):
            return _read_quoted(value)
        hash_at = value.find("#")
        if hash_at >= 0:
            value = value[:hash_at].strip()
        return value or None
    return None


def _read_quoted(value: str) -> str | None:
    quote = value[0]
    out: list[str] = []
    previous = ""
    for char in value[1:]:
        if char == quote and previous != "\\":
            return "".join(out).strip() or None
        out.append(char)
        previous = char
    return None


def clean_server_url(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    if not trimmed.startswith("https://"):
        return None
    return trimmed.rstrip("/") or None


def load_credentials_file(env: Env) -> tuple[str, str | None] | None:
    try:
        text = credentials_path(env).read_text(encoding="utf-8")
    except OSError:
        return None
    key = read_toml_string(text, "windsurf_api_key")
    if not key:
        return None
    server = clean_server_url(read_toml_string(text, "api_server_url"))
    return key, server


def load_app_auth(env: Env) -> tuple[str, str | None] | None:
    db = app_db_path(env)
    if not db.is_file():
        return None
    try:
        conn = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
    except sqlite3.Error:
        return None
    try:
        conn.execute("PRAGMA query_only = ON")
        try:
            row = conn.execute(
                "SELECT value FROM ItemTable WHERE key = 'windsurfAuthStatus' LIMIT 1"
            ).fetchone()
        except sqlite3.Error:
            return None
    finally:
        conn.close()
    if not row or row[0] is None:
        return None
    raw = row[0].decode("utf-8", "replace") if isinstance(row[0], bytes) else str(row[0])
    try:
        payload = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    key = str(payload.get("apiKey") or "").strip()
    return (key, None) if key else None


def effective_server(auth: tuple[str, str | None]) -> str:
    return auth[1] or DEFAULT_SERVER


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="devin", family=family, label=LABEL)]


def has_credentials(env: Env) -> bool:
    return load_credentials_file(env) is not None or load_app_auth(env) is not None


def _quota_line(
    metric_id: str, remaining: float, resets_at: str | None, period: int
) -> model.Progress:
    return model.Progress(
        metric_id=metric_id, used=parse.clamp_percent(100.0 - remaining),
        limit=100, resets_at=resets_at, period_ms=period,
    )


def _unix_date(value: Any) -> str | None:
    seconds = parse.number(value)
    if seconds is None:
        return None
    try:
        moment = dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat()


def map_user_status(status: dict[str, Any]) -> tuple[str | None, dict[str, model.Metric]]:
    """UserStatus object to plan plus meters. Raises ValueError when empty."""
    plan_status = status.get("planStatus")
    plan_status = plan_status if isinstance(plan_status, dict) else {}
    info = plan_status.get("planInfo")
    info = info if isinstance(info, dict) else {}
    plan = str(info.get("planName") or "").strip() or "Unknown"
    hidden = parse.parse_bool(info.get("hideDailyQuota")) is True
    daily = parse.number(plan_status.get("dailyQuotaRemainingPercent"))
    weekly = parse.number(plan_status.get("weeklyQuotaRemainingPercent"))
    if plan_status.get("weeklyQuotaRemainingPercent") is not None and weekly is None:
        raise ValueError("invalid response")
    daily_reset = None if hidden else _unix_date(plan_status.get("dailyQuotaResetAtUnix"))
    weekly_reset = _unix_date(plan_status.get("weeklyQuotaResetAtUnix"))
    micros = parse.number(plan_status.get("overageBalanceMicros"))
    out: dict[str, model.Metric] = {}
    if not hidden and daily is not None:
        out["daily"] = _quota_line("daily", daily, daily_reset, DAY_MS)
    remaining = weekly if weekly is not None else (0.0 if weekly_reset else None)
    if remaining is not None:
        out["weekly"] = _quota_line("weekly", remaining, weekly_reset, WEEK_MS)
    elif hidden and daily is not None:
        out["weekly"] = _quota_line("weekly", daily, weekly_reset, WEEK_MS)
    if micros is not None:
        out["extra"] = model.Values(
            metric_id="extra",
            values=(model.ScalarValue(number=max(0.0, micros) / 1_000_000,
                                      kind="dollars"),),
        )
    if not out:
        raise ValueError("quota unavailable")
    return plan, out


def _attempt(
    env: Env, auth: tuple[str, str | None]
) -> tuple[str | None, dict[str, model.Metric]] | str:
    """Success tuple, "auth", or "unavailable". Never raises."""
    url = f"{effective_server(auth)}/{SERVICE}/GetUserStatus"
    body = json.dumps({"metadata": {
        "apiKey": auth[0], "ideName": "devin", "ideVersion": COMPAT_VERSION,
        "extensionName": "devin", "extensionVersion": COMPAT_VERSION,
        "locale": "en"}}).encode("utf-8")
    try:
        reply = env.http.post(
            url, body,
            headers={"Content-Type": "application/json",
                     "Connect-Protocol-Version": "1"},
            timeout=15,
        )
    except _http.HttpError:
        return "unavailable"
    if reply.status in (401, 403):
        return "auth"
    if not 200 <= reply.status < 300:
        return "unavailable"
    payload = _http.parse_json_object(reply.body)
    status = payload.get("userStatus") if payload else None
    if not isinstance(status, dict):
        return "unavailable"
    try:
        return map_user_status(status)
    except ValueError:
        log.get_logger("plugin.devin").debug("unusable Devin quota payload")
        return "unavailable"


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    saw_key = False
    saw_auth = False
    first = load_credentials_file(env)
    if first is not None:
        saw_key = True
        outcome = _attempt(env, first)
        if isinstance(outcome, tuple):
            plan, metrics = outcome
            return model.Snapshot(
                card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
        if outcome == "auth":
            saw_auth = True
    second = load_app_auth(env)
    if second is not None and (
        first is None or second[0] != first[0]
        or effective_server(second) != effective_server(first)
    ):
        saw_key = True
        outcome = _attempt(env, second)
        if isinstance(outcome, tuple):
            plan, metrics = outcome
            return model.Snapshot(
                card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
        if outcome == "auth":
            saw_auth = True
    if saw_auth:
        raise model.CollectorError("auth", NOT_LOGGED_IN)
    if saw_key:
        raise model.CollectorError("empty", QUOTA_UNAVAILABLE)
    raise model.CollectorError("auth", NOT_LOGGED_IN)
