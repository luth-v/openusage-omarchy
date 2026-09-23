"""Copilot usage mapper. Pure: response body to meters plus plan."""

from __future__ import annotations

from typing import Any

from ... import model, parse

MONTH_MS = 30 * 24 * 60 * 60 * 1000


def plan_label(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    text = value.strip().replace("-", " ")
    if not text:
        return None
    return parse.title_cased(text, lower_tail=True)


def reset_date(body: dict[str, Any]) -> str | None:
    for key in ("quota_reset_date", "limited_user_reset_date"):
        moment = parse.parse_time(body.get(key))
        if moment is not None:
            return moment.isoformat()
    return None


def snapshot_line(
    metric_id: str, raw: Any, resets_at: str | None
) -> model.Progress | None:
    """A quota_snapshots bucket to a percent meter, or None to suppress."""
    if not isinstance(raw, dict):
        return None
    entitlement = parse.number(raw.get("entitlement"))
    remaining = parse.number(raw.get("remaining"))
    if parse.parse_bool(raw.get("unlimited")) is True:
        return None
    if entitlement == -1 or remaining == -1:
        return None
    if entitlement == 0:
        return None
    percent_left = parse.number(raw.get("percent_remaining"))
    if percent_left is not None:
        used = parse.clamp_percent(100.0 - percent_left)
    elif entitlement is not None and entitlement > 0 and remaining is not None:
        used = parse.clamp_percent(100.0 - (remaining / entitlement) * 100.0)
    else:
        return None
    return model.Progress(
        metric_id=metric_id, used=used, limit=100,
        resets_at=resets_at, period_ms=MONTH_MS,
    )


def personal_credits(raw: Any) -> model.Values | None:
    """Own credits_used on an org-managed placeholder: an unbounded count."""
    if not isinstance(raw, dict):
        return None
    used = parse.number(raw.get("credits_used"))
    if used is None or used <= 0:
        return None
    return model.Values(
        metric_id="premium",
        values=(model.ScalarValue(number=used, kind="count"),),
    )


def overage_line(raw: Any) -> model.Values | None:
    """Extra Usage, only once overage spend is enabled (else N/A)."""
    if not isinstance(raw, dict):
        return None
    if parse.parse_bool(raw.get("overage_permitted")) is not True:
        return None
    overage = max(0.0, parse.number(raw.get("overage_count")) or 0.0)
    return model.Values(
        metric_id="extra",
        values=(model.ScalarValue(number=overage, kind="count"),),
    )


def limited_line(
    metric_id: str, remaining: Any, total: Any, resets_at: str | None
) -> model.Progress | None:
    """Legacy free-tier shape: remaining count against a monthly total."""
    limit = parse.number(total)
    left = parse.number(remaining)
    if limit is None or limit <= 0 or left is None:
        return None
    used = max(0.0, limit - left)
    return model.Progress(
        metric_id=metric_id, used=parse.clamp_percent((used / limit) * 100.0),
        limit=100, resets_at=resets_at, period_ms=MONTH_MS,
    )


def map_body(body: dict[str, Any]) -> tuple[str | None, dict[str, model.Metric], bool]:
    """(plan, metrics, is_org_managed_seat). Raises ValueError when empty."""
    plan = plan_label(body.get("copilot_plan"))
    resets_at = reset_date(body)
    snapshots = body.get("quota_snapshots")
    snapshots = snapshots if isinstance(snapshots, dict) else {}
    premium = snapshots.get("premium_interactions")
    out: dict[str, model.Metric] = {}
    credits = snapshot_line("premium", premium, resets_at)
    if credits is not None:
        out["premium"] = credits
        overage = overage_line(premium)
        if overage is not None:
            out["extra"] = overage
    chat = snapshot_line("chat", snapshots.get("chat"), resets_at)
    if chat is not None:
        out["chat"] = chat
    completions = snapshot_line("completions", snapshots.get("completions"), resets_at)
    if completions is not None:
        out["completions"] = completions
    if not out:
        limited = body.get("limited_user_quotas")
        monthly = body.get("monthly_quotas")
        limited = limited if isinstance(limited, dict) else {}
        monthly = monthly if isinstance(monthly, dict) else {}
        chat = limited_line("chat", limited.get("chat"), monthly.get("chat"), resets_at)
        if chat is not None:
            out["chat"] = chat
        completions = limited_line(
            "completions", limited.get("completions"),
            monthly.get("completions"), resets_at)
        if completions is not None:
            out["completions"] = completions
    if out:
        return plan, out, False
    if parse.parse_bool(body.get("token_based_billing")) is not True:
        raise ValueError("quota unavailable")
    personal = personal_credits(premium)
    return plan, {"premium": personal} if personal else {}, True
