"""Cursor summary mapper. Team and enterprise REST fallbacks.

Combines the request allowance with structured percentages, user-scoped
on-demand spend, and exact billing-cycle bounds. Neither REST response is
the whole account snapshot by itself.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ... import model, parse
from . import mapper as _mapper

MONTH_MS = 30 * 24 * 60 * 60 * 1000


def _summary_cycle(
    summary: dict[str, Any] | None, request_usage: dict[str, Any] | None
) -> tuple[str | None, int]:
    start = parse.parse_time((summary or {}).get("billingCycleStart"))
    end = parse.parse_time((summary or {}).get("billingCycleEnd"))
    if start is not None and end is not None and end > start:
        return end.isoformat(), int((end - start).total_seconds() * 1000)
    req_start = parse.parse_time((request_usage or {}).get("startOfMonth"))
    resets = req_start + dt.timedelta(milliseconds=MONTH_MS) if req_start else None
    return (resets.isoformat() if resets else None), MONTH_MS


def _dollar_meter(bucket: Any) -> tuple[float, float] | None:
    if not isinstance(bucket, dict) or bucket.get("enabled") is False:
        return None
    limit = parse.number(bucket.get("limit"))
    if limit is None or limit <= 0:
        return None
    reported = parse.number(bucket.get("used"))
    inferred = max(0, limit - (parse.number(bucket.get("remaining")) or limit))
    used = reported if reported is not None and reported > 0 else inferred
    return max(0, used), limit


def map_summary(
    summary: dict[str, Any] | None, request_usage: dict[str, Any] | None,
    plan_name: str | None, message: str,
) -> tuple[dict[str, model.Metric], str | None]:
    metrics: dict[str, model.Metric] = {}
    resets, period = _summary_cycle(summary, request_usage)
    has_requests = False
    gpt4 = request_usage.get("gpt-4") if isinstance(request_usage, dict) else None
    if isinstance(gpt4, dict):
        limit = parse.number(gpt4.get("maxRequestUsage"))
        if limit is not None and limit > 0:
            used = parse.number(gpt4.get("numRequests"))
            if used is None:
                used = parse.number(gpt4.get("numRequestsTotal")) or 0
            for metric_id in ("usage", "requests"):
                metrics[metric_id] = model.Progress(
                    metric_id=metric_id, used=max(0, used), limit=limit,
                    format_kind="count", suffix="requests",
                    resets_at=resets, period_ms=period)
            has_requests = True
    individual = (summary or {}).get("individualUsage")
    individual = individual if isinstance(individual, dict) else {}
    team = (summary or {}).get("teamUsage")
    team = team if isinstance(team, dict) else {}
    if not has_requests:
        limit_type = str((summary or {}).get("limitType") or "").lower()
        if limit_type == "team":
            meter = _dollar_meter(team.get("pooled"))
            if meter is not None:
                metrics["usage"] = model.Progress(
                    metric_id="usage", used=parse.cents_to_dollars(meter[0]),
                    limit=parse.cents_to_dollars(meter[1]), format_kind="dollars",
                    resets_at=resets, period_ms=period)
        if "usage" not in metrics:
            plan = individual.get("plan")
            plan = plan if isinstance(plan, dict) else {}
            total_pct = parse.number(plan.get("totalPercentUsed"))
            if total_pct is not None:
                metrics["usage"] = model.Progress(
                    metric_id="usage", used=total_pct, limit=100,
                    resets_at=resets, period_ms=period)
        if "usage" not in metrics:
            meter = _dollar_meter(individual.get("overall")) or _dollar_meter(team.get("pooled"))
            if meter is not None:
                metrics["usage"] = model.Progress(
                    metric_id="usage", used=parse.cents_to_dollars(meter[0]),
                    limit=parse.cents_to_dollars(meter[1]), format_kind="dollars",
                    resets_at=resets, period_ms=period)
    plan = individual.get("plan")
    plan = plan if isinstance(plan, dict) else {}
    for key, metric_id in (("autoPercentUsed", "auto"), ("apiPercentUsed", "api")):
        pct = parse.number(plan.get(key))
        if pct is not None:
            metrics[metric_id] = model.Progress(
                metric_id=metric_id, used=pct, limit=100,
                resets_at=resets, period_ms=period)
    for bucket in (individual.get("onDemand"), team.get("onDemand")):
        if not isinstance(bucket, dict) or bucket.get("enabled") is False:
            continue
        meter = _dollar_meter(bucket)
        if meter is not None:
            metrics["onDemand"] = model.Progress(
                metric_id="onDemand", used=parse.cents_to_dollars(meter[0]),
                limit=parse.cents_to_dollars(meter[1]), format_kind="dollars",
                resets_at=resets, period_ms=period)
            break
        used_cents = parse.number(bucket.get("used")) or 0
        if used_cents > 0:
            metrics["onDemand"] = model.Values(
                metric_id="onDemand",
                values=(model.ScalarValue(
                    number=parse.cents_to_dollars(used_cents), kind="dollars"),),
            )
            break
    if not metrics:
        raise model.CollectorError("empty", message)
    label = _mapper.plan_label(plan_name) or _mapper.plan_label(
        str((summary or {}).get("membershipType") or "") or None
    )
    return metrics, label
