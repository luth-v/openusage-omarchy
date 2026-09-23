"""Cursor usage mapper. Pure: usage JSON to catalog metrics."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ... import model, parse

MONTH_MS = 30 * 24 * 60 * 60 * 1000
WEEK_MS = 7 * 24 * 60 * 60 * 1000


def map_grok_bot(usage: dict[str, Any]) -> model.Progress | None:
    if usage.get("usesPooledEnterpriseAllowance") is True:
        return None
    if usage.get("hasNonZeroIncludedLimit") is False:
        return None
    if usage.get("includedLimitZero") is True:
        return None
    percent = parse.number(usage.get("usagePercent"))
    if percent is None or percent < 0:
        return None
    resets = parse.parse_time(usage.get("nextResetTimestampUtc"))
    start = parse.parse_time(usage.get("currentPeriodStart"))
    if start is not None and resets is not None and resets > start:
        period = int((resets - start).total_seconds() * 1000)
    else:
        period = WEEK_MS
    return model.Progress(
        metric_id="grokBot",
        used=parse.clamp_percent(percent),
        limit=100,
        resets_at=resets.isoformat() if resets else None,
        period_ms=period,
    )


def cycle(usage: dict[str, Any]) -> tuple[str | None, int]:
    start = parse.number(usage.get("billingCycleStart"))
    end = parse.number(usage.get("billingCycleEnd"))
    resets: str | None = None
    if end is not None:
        resets = dt.datetime.fromtimestamp(end / 1000, dt.timezone.utc).isoformat()
    if start is not None and end is not None and end > start:
        return resets, int(end - start)
    return resets, MONTH_MS


def plan_label(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    return parse.title_cased(text) if text else None


def stripe_balance_cents(body: dict[str, Any] | None) -> float:
    if not body:
        return 0
    balance = parse.number(body.get("customerBalance"))
    if balance is None or balance >= 0:
        return 0
    return abs(balance)


def credits_metric(
    grants: dict[str, Any] | None, stripe_cents: float
) -> model.Values | None:
    has_grants = grants is not None and grants.get("hasCreditGrants") is True
    total = parse.number(grants.get("totalCents")) if grants else None
    used = parse.number(grants.get("usedCents")) if grants else None
    valid = has_grants and total is not None and total > 0
    combined = (total if valid and total is not None else 0) + stripe_cents
    if combined <= 0:
        return None
    remaining = max(0, combined - (used if valid and used is not None else 0))
    return model.Values(
        metric_id="credits",
        values=(model.ScalarValue(
            number=parse.cents_to_dollars(remaining), kind="dollars"),),
    )


def on_demand_spend(bucket: dict[str, Any], limit: float, remaining: float) -> float:
    for key in ("individualUsed", "pooledUsed", "totalSpend", "used"):
        found = parse.number(bucket.get(key))
        if found is not None and found > 0:
            return found
    inferred = max(0, limit - remaining)
    if inferred > 0:
        return inferred
    for key in ("individualUsed", "pooledUsed", "totalSpend", "used"):
        found = parse.number(bucket.get(key))
        if found is not None:
            return found
    return 0


def facts(usage: dict[str, Any]) -> dict[str, Any]:
    enabled = usage.get("enabled") is not False
    plan_usage = usage.get("planUsage")
    plan_usage = plan_usage if isinstance(plan_usage, dict) else None
    limit = parse.number(plan_usage.get("limit")) if plan_usage else None
    total_pct = parse.number(plan_usage.get("totalPercentUsed")) if plan_usage else None
    spend = usage.get("spendLimitUsage")
    spend = spend if isinstance(spend, dict) else {}
    limit_type = str(spend.get("limitType") or "").lower()
    pooled = parse.number(spend.get("pooledLimit")) or 0
    return {
        "enabled": enabled,
        "hasPlanUsage": plan_usage is not None,
        "limit": limit,
        "totalPct": total_pct,
        "isTeamByShape": limit_type == "team" or pooled > 0,
        "planUsage": plan_usage or {},
        "spend": spend,
    }


def map_usage(
    usage: dict[str, Any], plan_name: str | None,
    grants: dict[str, Any] | None, stripe_cents: float,
) -> tuple[dict[str, model.Metric], str | None]:
    info = facts(usage)
    if not info["enabled"] or not info["hasPlanUsage"]:
        raise model.CollectorError("empty", "No active Cursor subscription.")
    plan_usage = info["planUsage"]
    limit = info["limit"]
    total_pct = info["totalPct"]
    if limit is None and total_pct is None:
        raise model.CollectorError("empty", "Total usage limit missing from API response.")
    metrics: dict[str, model.Metric] = {}
    credits = credits_metric(grants, stripe_cents)
    if credits is not None:
        metrics["credits"] = credits
    used_cents = parse.number(plan_usage.get("totalSpend"))
    if used_cents is None:
        used_cents = (limit or 0) - (parse.number(plan_usage.get("remaining")) or 0)
    computed = used_cents / limit * 100 if limit else 0
    total = total_pct if total_pct is not None else computed
    resets, period = cycle(usage)
    normalized = (plan_name or "").strip().lower()
    is_team = normalized == "team" or info["isTeamByShape"]
    if is_team:
        if limit is None:
            raise model.CollectorError(
                "empty", "Cursor request-based usage data unavailable. Try again later."
            )
        metrics["usage"] = model.Progress(
            metric_id="usage", used=parse.cents_to_dollars(used_cents),
            limit=parse.cents_to_dollars(limit), format_kind="dollars",
            resets_at=resets, period_ms=period,
        )
    else:
        metrics["usage"] = model.Progress(
            metric_id="usage", used=total, limit=100,
            resets_at=resets, period_ms=period,
        )
    auto = parse.number(plan_usage.get("autoPercentUsed"))
    if auto is not None:
        metrics["auto"] = model.Progress(
            metric_id="auto", used=auto, limit=100, resets_at=resets, period_ms=period)
    api = parse.number(plan_usage.get("apiPercentUsed"))
    if api is not None:
        metrics["api"] = model.Progress(
            metric_id="api", used=api, limit=100, resets_at=resets, period_ms=period)
    spend = info["spend"]
    if spend:
        cap = parse.number(spend.get("individualLimit"))
        if cap is None:
            cap = parse.number(spend.get("pooledLimit")) or 0
        remaining = parse.number(spend.get("individualRemaining"))
        if remaining is None:
            remaining = parse.number(spend.get("pooledRemaining")) or 0
        spent = on_demand_spend(spend, cap, remaining)
        if cap > 0:
            metrics["onDemand"] = model.Progress(
                metric_id="onDemand", used=parse.cents_to_dollars(spent),
                limit=parse.cents_to_dollars(cap), format_kind="dollars")
        elif spent > 0:
            metrics["onDemand"] = model.Values(
                metric_id="onDemand",
                values=(model.ScalarValue(
                    number=parse.cents_to_dollars(spent), kind="dollars"),),
            )
    return metrics, plan_label(plan_name)


def map_usage_simple(
    usage: dict[str, Any], plan_name: str
) -> tuple[dict[str, model.Metric], str]:
    """Two-argument mapper for tests. Grants and Stripe default to none."""
    metrics, _ = map_usage(usage, plan_name or None, None, 0)
    return metrics, plan_name.strip()


def map_request_based(
    usage: dict[str, Any] | None, plan_name: str | None, message: str
) -> tuple[dict[str, model.Metric], str | None]:
    metrics: dict[str, model.Metric] = {}
    gpt4 = usage.get("gpt-4") if isinstance(usage, dict) else None
    if isinstance(gpt4, dict):
        limit = parse.number(gpt4.get("maxRequestUsage"))
        if limit is not None and limit > 0:
            used = parse.number(gpt4.get("numRequests")) or 0
            start = parse.parse_time((usage or {}).get("startOfMonth"))
            resets = start + dt.timedelta(milliseconds=MONTH_MS) if start else None
            metrics["requests"] = model.Progress(
                metric_id="requests", used=max(0, used), limit=limit,
                format_kind="count", suffix="requests",
                resets_at=resets.isoformat() if resets else None, period_ms=MONTH_MS)
    if not metrics:
        raise model.CollectorError("empty", message)
    return metrics, plan_label(plan_name)


def should_fallback(
    usage: dict[str, Any], plan_name: str | None, plan_missing: bool
) -> tuple[bool, str]:
    info = facts(usage)
    if not info["enabled"]:
        return False, ""
    normalized = (plan_name or "").strip().lower()
    unusable = not info["hasPlanUsage"] or (
        info["hasPlanUsage"] and info["limit"] is None
    )
    if unusable and normalized == "enterprise":
        return True, "Enterprise usage data unavailable. Try again later."
    if unusable and normalized == "team":
        return True, "Team request-based usage data unavailable. Try again later."
    if unusable and info["totalPct"] is None and not normalized and plan_missing:
        return True, "Cursor request-based usage data unavailable. Try again later."
    if info["isTeamByShape"] and info["hasPlanUsage"] and info["limit"] is None:
        return True, "Cursor request-based usage data unavailable. Try again later."
    return False, ""
