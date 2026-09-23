"""Claude usage mapper. Pure: usage JSON plus credentials to metrics."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any

from ... import http as _http, model, parse
from . import auth as _auth

SESSION_MS = 5 * 60 * 60 * 1000
WEEK_MS = 7 * 24 * 60 * 60 * 1000
RATE_LIMITED_WAIT = (
    "Updates blocked by Anthropic. Be patient — manual refreshes will make it worse."
)
_TIER = re.compile(r"\d+x")


def _window(
    value: Any, metric_id: str, period_ms: int
) -> model.Progress | None:
    if not isinstance(value, dict):
        return None
    used = parse.number(value.get("utilization"))
    if used is None:
        return None
    resets = parse.reset_date(value.get("resets_at"))
    return model.Progress(
        metric_id=metric_id,
        used=used,
        limit=100,
        resets_at=resets.isoformat() if resets else None,
        period_ms=period_ms,
    )


def _scoped_weekly(limits: Any, display: str, metric_id: str) -> model.Progress | None:
    if not isinstance(limits, list):
        return None
    for entry in limits:
        if not isinstance(entry, dict) or entry.get("kind") != "weekly_scoped":
            continue
        scope = entry.get("scope")
        found = ""
        if isinstance(scope, dict):
            details = scope.get("model")
            if isinstance(details, dict):
                found = str(details.get("display_name") or "")
        if found != display:
            continue
        used = parse.number(entry.get("percent"))
        if used is None:
            continue
        resets = parse.reset_date(entry.get("resets_at"))
        return model.Progress(
            metric_id=metric_id,
            used=used,
            limit=100,
            resets_at=resets.isoformat() if resets else None,
            period_ms=WEEK_MS,
        )
    return None


def _extra(value: Any) -> model.Metric | None:
    if not isinstance(value, dict) or value.get("is_enabled") is not True:
        return None
    used_cents = parse.number(value.get("used_credits"))
    if used_cents is None:
        return None
    used = parse.cents_to_dollars(used_cents)
    limit_cents = parse.number(value.get("monthly_limit"))
    if limit_cents is not None and limit_cents > 0:
        return model.Progress(
            metric_id="extra",
            used=used,
            limit=parse.cents_to_dollars(limit_cents),
            format_kind="dollars",
        )
    if used > 0:
        return model.Values(
            metric_id="extra",
            values=(model.ScalarValue(number=used, kind="dollars"),),
        )
    return None


def _reset_grants(value: Any, now: dt.datetime) -> model.Values | None:
    if not isinstance(value, dict):
        return None
    count = 0
    expiries: list[str] = []
    if value.get("eligible") is True:
        grants = value.get("grants")
        items = grants if isinstance(grants, list) else []
        for grant in items:
            if not isinstance(grant, dict):
                continue
            left = parse.number(grant.get("resets_left"))
            if left is None or left < 1:
                continue
            resets = int(left // 1)
            ends = parse.reset_date(grant.get("ends_at"))
            if ends is not None and ends <= now:
                continue
            count += resets
            if ends is not None:
                expiries.extend([ends.isoformat()] * resets)
    expiries.sort()
    return model.Values(
        metric_id="rateLimitResets",
        values=(model.ScalarValue(number=float(count), kind="count", label="available"),),
        expiries_at=tuple(expiries),
    )


def format_plan(subscription: str, tier: str) -> str | None:
    raw = (subscription or "").strip()
    if not raw:
        return None
    base = parse.title_cased(raw, lower_tail=True)
    match = _TIER.search(tier or "")
    if match:
        return f"{base} {match.group(0)}"
    return base


def format_live_plan(profile: dict[str, Any], oauth: _auth.OAuth) -> str | None:
    org = profile.get("organization")
    if not isinstance(org, dict):
        return None
    org_type = str(org.get("organization_type") or "").strip()
    if org_type.startswith("claude_"):
        org_type = org_type[len("claude_"):]
    subscription = org_type or oauth.subscription_type
    tier = str(org.get("rate_limit_tier") or "").strip() or oauth.rate_limit_tier
    return format_plan(subscription, tier)


def parse_retry_after(headers: dict[str, str] | None, now: dt.datetime) -> int | None:
    if not headers:
        return None
    raw = ""
    for key, value in headers.items():
        if key.lower() == "retry-after":
            raw = value.strip()
            break
    if not raw:
        return None
    try:
        seconds = int(raw)
        return seconds if seconds >= 0 else None
    except ValueError:
        pass
    moment = parse.parse_time(raw)
    if moment is None:
        return None
    import math

    return max(0, int(math.ceil((moment - now).total_seconds())))


def rate_limit_message(retry_after: int | None) -> str:
    if retry_after is None:
        return RATE_LIMITED_WAIT
    import math

    label = "now" if retry_after <= 0 else f"{int(math.ceil(retry_after / 60))}m"
    return f"{RATE_LIMITED_WAIT} Retrying in ~{label}."


def map_usage(
    body: bytes, oauth: _auth.OAuth, now: dt.datetime
) -> tuple[dict[str, model.Metric], str | None]:
    payload = _http.parse_json_object(body)
    if payload is None:
        raise ValueError("invalid response")
    metrics: dict[str, model.Metric] = {}
    window = _window(payload.get("five_hour"), "session", SESSION_MS)
    if window is not None:
        metrics["session"] = window
    window = _window(payload.get("seven_day"), "weekly", WEEK_MS)
    if window is not None:
        metrics["weekly"] = window
    window = _window(payload.get("seven_day_sonnet"), "sonnet", WEEK_MS)
    if window is not None:
        metrics["sonnet"] = window
    fable = _scoped_weekly(payload.get("limits"), "Fable", "fable")
    if fable is not None:
        metrics["fable"] = fable
    extra = _extra(payload.get("extra_usage"))
    if extra is not None:
        metrics["extra"] = extra
    resets = _reset_grants(payload.get("cedar_ember"), now)
    if resets is not None:
        metrics["rateLimitResets"] = resets
    plan = format_plan(oauth.subscription_type, oauth.rate_limit_tier)
    return metrics, plan
