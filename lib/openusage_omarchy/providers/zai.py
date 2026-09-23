"""Z.ai collector. GLM Coding Plan quotas from the subscription API.

The key comes from the plugin key store (keyring, fallback file, or env).
The quota endpoint is required; the subscription endpoint is best-effort
(plan name only) and never blanks the meters. Credit windows split by length:
sub-daily feeds Session, multi-day feeds Weekly.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from .. import http as _http, model, parse, secrets
from ..providers import Env, iso_now

family = "zai"
LABEL = "Z.ai"
SUBSCRIPTION_URL = "https://api.z.ai/api/biz/subscription/list"
QUOTA_URL = "https://api.z.ai/api/monitor/usage/quota/limit"
MONTHLY_MS = 30 * 24 * 60 * 60 * 1000
MISSING_KEY = "No Z.ai API key. Set ZAI_API_KEY or add it in Settings → API Keys."
INVALID_KEY = "Z.ai API key invalid. Check your key at z.ai/manage-apikey/apikey-list."
CONNECTION_FAILED = "Couldn't reach Z.ai. Check your connection."
INVALID_RESPONSE = "Z.ai quota data unavailable. Try again later."
NO_PLAN = "No active GLM Coding Plan. Subscribe at z.ai/subscribe to see usage."

_UNIT_MS = {3: 3_600_000.0, 4: 86_400_000.0, 6: 604_800_000.0, 5: 2_592_000_000.0}


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="zai", family=family, label=LABEL)]


def has_credentials(env: Env) -> bool:
    return secrets.get_key("zai", env.paths) is not None


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + key, "Accept": "application/json"}


def _get(env: Env, url: str, key: str) -> _http.Response:
    try:
        return env.http.get(url, headers=_headers(key), timeout=15)
    except _http.HttpError as exc:
        if exc.status is not None:
            raise model.CollectorError(
                "status", f"Z.ai request failed (HTTP {exc.status}). Try again later.")
        raise model.CollectorError("transport", CONNECTION_FAILED)


def is_no_coding_plan(body: bytes) -> bool:
    """2xx with success:false plus the coding-plan phrase means no plan."""
    root = _http.parse_json_object(body)
    if root is None or root.get("success") is not False:
        return False
    return "coding plan" in str(root.get("msg") or "").lower()


def _entry_type(entry: dict[str, Any]) -> str:
    return str(entry.get("type") or entry.get("name") or "")


def _reset_at(entry: dict[str, Any]) -> str | None:
    ms = parse.number(entry.get("nextResetTime"))
    if ms is None:
        return None
    try:
        moment = dt.datetime.fromtimestamp(ms / 1000.0, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None
    return moment.isoformat()


def _classify_window(entry: dict[str, Any]) -> tuple[str, int] | None:
    """(metric id, period ms), None for unknown units. Raises on bad shape."""
    unit = parse.number(entry.get("unit"))
    number = parse.number(entry.get("number"))
    if unit is None or number is None or number <= 0:
        raise ValueError("invalid response")
    width = _UNIT_MS.get(int(unit)) if float(int(unit)) == unit else None
    if width is None:
        return None
    duration = width * number
    if duration < 1 or duration >= 2**63:
        raise ValueError("invalid response")
    period = int(duration)
    if period < 86_400_000:
        return "session", period
    return "weekly", period


def _percent_line(entry: dict[str, Any], metric_id: str, period: int) -> model.Progress:
    raw = parse.number(entry.get("percentage"))
    if raw is None:
        raise ValueError("invalid response")
    return model.Progress(
        metric_id=metric_id, used=parse.clamp_percent(raw), limit=100,
        resets_at=_reset_at(entry), period_ms=period,
    )


def _web_search_line(entry: dict[str, Any]) -> model.Progress:
    used = parse.number(entry.get("currentValue"))
    limit = parse.number(entry.get("usage"))
    if used is None or limit is None or used < 0 or limit < 0:
        raise ValueError("invalid response")
    return model.Progress(
        metric_id="webSearches", used=used, limit=limit,
        format_kind="count", suffix="searches",
        resets_at=_reset_at(entry), period_ms=MONTHLY_MS,
    )


def map_quota(body: bytes) -> dict[str, model.Metric]:
    """Quota payload to meters. Empty dict means valid no-data, not failure."""
    root = _http.parse_json_object(body)
    if root is None:
        raise ValueError("invalid response")
    container: Any = root.get("data", root)
    if not isinstance(container, dict):
        raise ValueError("invalid response")
    limits = container.get("limits")
    if not isinstance(limits, list):
        raise ValueError("invalid response")
    if any(not isinstance(entry, dict) for entry in limits):
        raise ValueError("invalid response")
    out: dict[str, model.Metric] = {}
    if not limits:
        return out
    seen = False
    for entry in limits:
        if not isinstance(entry, dict):
            continue
        if _entry_type(entry) in ("CREDIT_LIMIT", "TOKENS_LIMIT"):
            window = _classify_window(entry)
            if window is None:
                continue
            seen = True
            metric_id, period = window
            out[metric_id] = _percent_line(entry, metric_id, period)
    for entry in limits:
        if isinstance(entry, dict) and _entry_type(entry) == "TIME_LIMIT":
            seen = True
            out["webSearches"] = _web_search_line(entry)
            break
    if not out:
        if seen:
            raise ValueError("invalid response")
        return out
    return out


def plan_name(body: bytes) -> str | None:
    root = _http.parse_json_object(body)
    if root is None:
        return None
    items = root.get("data")
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    name = str(first.get("productName") or "").strip()
    return name or None


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    key = secrets.get_key("zai", env.paths)
    if not key:
        raise model.CollectorError("auth", MISSING_KEY)
    reply = _get(env, QUOTA_URL, key)
    if reply.status in (401, 403):
        raise model.CollectorError("auth", INVALID_KEY)
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status", f"Z.ai request failed (HTTP {reply.status}). Try again later.")
    if is_no_coding_plan(reply.body):
        raise model.CollectorError("empty", NO_PLAN)
    try:
        metrics = map_quota(reply.body)
    except ValueError:
        raise model.CollectorError("empty", INVALID_RESPONSE)
    plan: str | None = None
    try:
        sub = _get(env, SUBSCRIPTION_URL, key)
    except model.CollectorError:
        sub = None
    if sub is not None and 200 <= sub.status < 300:
        plan = plan_name(sub.body)
    return model.Snapshot(
        card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
