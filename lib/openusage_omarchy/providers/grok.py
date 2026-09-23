"""Grok collector. Billing quotas plus local spend history."""

from __future__ import annotations

import datetime as dt
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote

from .. import credentials, http as _http, log, model, parse
from ..providers import Env, iso_now
from ..spend import context as _spend_ctx
from ..spend import grok_scan as _scan
from ..spend import tiles as _tiles

family = "grok"
LABEL = "Grok"
TOKEN_URL = "https://auth.x.ai/oauth2/token"
BILLING_URL = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
SETTINGS_URL = "https://cli-chat-proxy.grok.com/v1/settings"
DEFAULT_CLIENT_ID = "b1a00492-073a-47ea-816f-4c329264a828"
WEEKLY_PERIOD = "USAGE_PERIOD_TYPE_WEEKLY"
NOT_LOGGED_IN = "Grok not logged in. Run `grok login`."
INVALID_AUTH = "Grok auth invalid. Run `grok login` again."
EXPIRED = "Grok auth expired. Run `grok login` again."


@dataclass
class Entry:
    key: str = ""
    refresh_token: str = ""
    refresh_alt: str = ""
    id_token: str = ""
    expires_at: str = ""
    expires_alt: str = ""
    oidc_client_id: str = ""

    @classmethod
    def from_dict(cls, raw: Any) -> "Entry":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            key=str(raw.get("key") or "").strip(),
            refresh_token=str(raw.get("refresh_token") or "").strip(),
            refresh_alt=str(raw.get("refresh") or "").strip(),
            id_token=str(raw.get("id_token") or "").strip(),
            expires_at=str(raw.get("expires_at") or "").strip(),
            expires_alt=str(raw.get("expires") or "").strip(),
            oidc_client_id=str(raw.get("oidc_client_id") or "").strip(),
        )


@dataclass
class Candidate:
    entry_key: str
    entry: Entry
    token: str


def _grok_home(env: Env) -> Path:
    override = (os.environ.get("GROK_HOME") or "").strip()
    if override:
        return Path(override).expanduser()
    return env.paths.home / ".grok"


def auth_path(env: Env) -> Path:
    return _grok_home(env) / "auth.json"


def load_candidates(env: Env) -> list[Candidate]:
    try:
        raw = json.loads(auth_path(env).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise model.CollectorError("auth", NOT_LOGGED_IN)
    if not isinstance(raw, dict):
        raise model.CollectorError("auth", INVALID_AUTH)
    out: list[Candidate] = []
    for key, value in raw.items():
        entry = Entry.from_dict(value)
        if entry.key:
            out.append(Candidate(entry_key=str(key), entry=entry, token=entry.key))
    if not out:
        raise model.CollectorError("auth", INVALID_AUTH)
    return out


def read_auth_entry(env: Env) -> tuple[str, dict[str, Any]]:
    """First keyed entry as (key, dict). Kept for the seam tests."""
    try:
        found = load_candidates(env)
    except model.CollectorError:
        return "", {}
    first = found[0]
    return first.entry_key, {
        "key": first.entry.key,
        "refresh_token": first.entry.refresh_token,
        "expires_at": first.entry.expires_at,
    }


def has_credentials(env: Env) -> bool:
    try:
        return bool(load_candidates(env))
    except model.CollectorError:
        return False


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="grok", family=family, label=LABEL)]


def parse_expiry(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds / 1000.0 if seconds > 10_000_000_000 else seconds
    moment = parse.parse_time(value)
    if moment is None:
        return 0.0
    return moment.timestamp()


def token_expires_at(token: str) -> dt.datetime | None:
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


def entry_expires_at(entry: Entry) -> dt.datetime | None:
    for raw in (entry.expires_at, entry.expires_alt):
        moment = parse.parse_time(raw) if raw else None
        if moment is not None:
            return moment
    return None


def needs_refresh(entry: Entry, token: str, now: dt.datetime) -> bool:
    for moment in (entry_expires_at(entry), token_expires_at(token)):
        if moment is not None and (moment - now).total_seconds() <= 5 * 60:
            return True
    return False


def is_expired(entry: Entry, token: str, now: dt.datetime) -> bool:
    moment = token_expires_at(token) or entry_expires_at(entry)
    if moment is None:
        return False
    return now >= moment


def refresh_token_for(entry: Entry) -> str:
    return entry.refresh_token or entry.refresh_alt


def client_id(entry_key: str, entry: Entry) -> str:
    if entry.oidc_client_id:
        return entry.oidc_client_id
    tail = str(entry_key).split("::")[-1].strip()
    return tail or DEFAULT_CLIENT_ID


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + token.strip(),
        "X-XAI-Token-Auth": "xai-grok-cli",
        "Accept": "application/json",
    }


def _save(env: Env, candidate: Candidate) -> None:
    path = auth_path(env)
    entry_key = candidate.entry_key
    entry = candidate.entry

    def _apply(payload: Any) -> Any | None:
        if not isinstance(payload, dict) or entry_key not in payload:
            return None
        payload = dict(payload)
        stored = dict(payload.get(entry_key) or {})
        stored["key"] = entry.key
        if entry.refresh_token:
            stored["refresh_token"] = entry.refresh_token
        if entry.id_token:
            stored["id_token"] = entry.id_token
        if entry.expires_at:
            stored["expires_at"] = entry.expires_at
        payload[entry_key] = stored
        return payload

    try:
        credentials.cas_update_json(path, _apply, "grok", log.get_logger("auth.grok"))
    except (OSError, ValueError) as exc:
        log.get_logger("auth.grok").error("rotation persist failed: %s", type(exc).__name__)


def refresh_access_token(env: Env, candidate: Candidate) -> str | None:
    refresh = refresh_token_for(candidate.entry)
    if not refresh:
        return None
    body = (
        "grant_type=refresh_token"
        f"&client_id={quote(client_id(candidate.entry_key, candidate.entry), safe='')}"
        f"&refresh_token={quote(refresh, safe='')}"
    ).encode("utf-8")
    try:
        reply = env.http.post(
            TOKEN_URL,
            body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    except _http.HttpError as exc:
        log.get_logger("auth.grok").warning(
            "token refresh request failed (transport): %s", type(exc).__name__)
        return None
    if not 200 <= reply.status < 300:
        log.get_logger("auth.grok").warning(
            "token refresh failed (HTTP %s)", reply.status)
        return None
    payload = _http.parse_json_object(reply.body) or {}
    token = str(payload.get("access_token") or "").strip()
    if not token:
        log.get_logger("auth.grok").warning("token refresh returned no access token")
        return None
    candidate.token = token
    candidate.entry.key = token
    new_refresh = str(payload.get("refresh_token") or "").strip()
    if new_refresh:
        candidate.entry.refresh_token = new_refresh
    new_id = str(payload.get("id_token") or "").strip()
    if new_id:
        candidate.entry.id_token = new_id
    now = env.clock.now()
    expires_in = parse.number(payload.get("expires_in"))
    if expires_in is not None and expires_in > 0:
        expires = now + dt.timedelta(seconds=expires_in)
    else:
        expires = token_expires_at(token) or (now + dt.timedelta(hours=1))
    candidate.entry.expires_at = expires.isoformat()
    _save(env, candidate)
    return token


def _fetch(env: Env, url: str, token: str) -> _http.Response:
    try:
        return env.http.get(url, headers=_headers(token), timeout=10)
    except _http.HttpError as exc:
        if exc.status is not None:
            raise model.CollectorError(
                "status", f"Grok billing request failed (HTTP {exc.status}). Try again later."
            )
        raise model.CollectorError(
            "transport", "Grok billing request failed. Check your connection.")


def _billing_with_retry(env: Env, candidate: Candidate) -> _http.Response:
    reply = _fetch(env, BILLING_URL, candidate.token)
    if reply.status not in (401, 403):
        return reply
    refreshed = refresh_access_token(env, candidate)
    if not refreshed:
        raise model.CollectorError("auth", EXPIRED)
    reply = _fetch(env, BILLING_URL, refreshed)
    if reply.status in (401, 403):
        raise model.CollectorError("auth", EXPIRED)
    return reply


def decode_config(body: bytes) -> dict[str, Any]:
    payload = _http.parse_json_object(body)
    if payload is None:
        raise model.CollectorError("empty", "Grok billing response changed.")
    config = payload.get("config")
    if not isinstance(config, dict):
        raise model.CollectorError("empty", "Grok billing response changed.")
    period = config.get("currentPeriod")
    if not isinstance(period, dict):
        raise model.CollectorError("empty", "Grok billing response changed.")
    period_type = str(period.get("type") or "").strip()
    start = parse.parse_time(period.get("start"))
    end = parse.parse_time(period.get("end"))
    if not period_type or start is None or end is None or end <= start:
        raise model.CollectorError("empty", "Grok billing response changed.")
    if "creditUsagePercent" in config:
        percent = parse.number(config.get("creditUsagePercent"))
        if percent is None:
            raise model.CollectorError("empty", "Grok billing response changed.")
    else:
        percent = 0.0
    cap_raw = config.get("onDemandCap")
    if cap_raw is None:
        cap = 0.0
    elif isinstance(cap_raw, dict):
        cap = parse.number(cap_raw.get("val", 0))
        if cap is None:
            raise model.CollectorError("empty", "Grok billing response changed.")
    else:
        raise model.CollectorError("empty", "Grok billing response changed.")
    return {
        "periodType": period_type,
        "percent": percent,
        "start": start,
        "end": end,
        "cap": cap,
    }


def _format_units(value: float) -> str:
    return str(int(value)) if value == round(value) else str(value)


def plan_from_settings(body: bytes) -> str | None:
    payload = _http.parse_json_object(body)
    if payload is None:
        return None
    plan = str(payload.get("subscription_tier_display") or "").strip()
    return plan or None


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    candidates = load_candidates(env)
    now = env.clock.now()
    saw_expired = False
    for candidate in candidates:
        if needs_refresh(candidate.entry, candidate.token, now):
            refreshed = refresh_access_token(env, candidate)
            if refreshed is not None:
                return _probe(env, card, candidate)
            if is_expired(candidate.entry, candidate.token, now):
                saw_expired = True
                continue
        return _probe(env, card, candidate)
    raise model.CollectorError("auth", EXPIRED if saw_expired else INVALID_AUTH)


def _probe(env: Env, card: model.CardRef, candidate: Candidate) -> model.Snapshot:
    reply = _billing_with_retry(env, candidate)
    if reply.status in (401, 403):
        raise model.CollectorError("auth", EXPIRED)
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status",
            f"Grok billing request failed (HTTP {reply.status}). Try again later.",
        )
    config = decode_config(reply.body)
    metrics: dict[str, model.Metric] = {}
    if config["periodType"] == WEEKLY_PERIOD:
        start, end = config["start"], config["end"]
        metrics["weekly"] = model.Progress(
            metric_id="weekly",
            used=parse.clamp_percent(config["percent"]),
            limit=100,
            resets_at=end.isoformat(),
            period_ms=int((end - start).total_seconds() * 1000),
        )
    cap = config["cap"]
    metrics["payAsYouGo"] = model.Badge(
        metric_id="payAsYouGo",
        text=f"{_format_units(float(cap))} cap" if cap > 0 else "Disabled",
    )
    plan: str | None = None
    try:
        settings = _fetch(env, SETTINGS_URL, candidate.token)
    except model.CollectorError:
        settings = None
    if settings is not None and 200 <= settings.status < 300:
        plan = plan_from_settings(settings.body)
    return model.Snapshot(card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)


NOTE = "From your Grok logs (estimated)"


def attach_spend(card: model.CardRef, env: Env, snap: model.Snapshot,
                 now: dt.datetime) -> model.Snapshot:
    """Spend tiles for a quota snapshot. Never raises; quota wins on failure.

    Runs after the quota batch publishes (see engine.refresh.attach_spend),
    priced from the cached store while it revalidates in the background.
    """
    try:
        pricing = _spend_ctx.load_pricing(env)
        stamp = _spend_ctx.since_ts(env)
        found = _scan.scan(env.paths.home, env.paths.scan_dir, stamp, pricing)
        if found is None:
            return snap
        metrics = dict(snap.metrics)
        _tiles.append_token_usage(
            found.series, metrics, now, estimated=True,
            unknown_by_day=found.unknown_by_day, model_usage=found.model_usage,
            model_note=NOTE)
        _tiles.append_trend(found.series, metrics, now, NOTE)
        return model.Snapshot(card=snap.card, plan=snap.plan,
                              fetched_at=snap.fetched_at, metrics=metrics,
                              error=snap.error)
    except Exception as exc:
        log.get_logger("plugin.grok").warning("spend scan failed: %s", exc)
        return snap
