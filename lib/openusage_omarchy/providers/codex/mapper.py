"""Codex usage mapper. Pure: usage JSON plus credits to metrics."""

from __future__ import annotations

import datetime as dt
from typing import Any

from ... import http as _http, model, parse

SESSION_MS = 5 * 60 * 60 * 1000
WEEK_MS = 7 * 24 * 60 * 60 * 1000
CREDIT_USD_RATE = 0.04


def _period_ms(window: dict) -> int | None:
    seconds = parse.number(window.get("limit_window_seconds"))
    return int(seconds * 1000) if seconds is not None else None


def _reset_at(window: dict, now: dt.datetime) -> dt.datetime | None:
    at = parse.number(window.get("reset_at"))
    if at is not None:
        try:
            return dt.datetime.fromtimestamp(at, dt.timezone.utc)
        except (OverflowError, OSError, ValueError):
            pass
    after = parse.number(window.get("reset_after_seconds"))
    if after is not None:
        return now + dt.timedelta(seconds=after)
    return None


def _kind_of(window: dict) -> str | None:
    period = _period_ms(window)
    if period == SESSION_MS:
        return "session"
    if period == WEEK_MS:
        return "weekly"
    return None


def _window_line(
    label: str, metric_id: str, used: float | None, window: dict,
    default_ms: int, now: dt.datetime,
) -> model.Progress | None:
    if used is None:
        return None
    resets = _reset_at(window, now)
    return model.Progress(
        metric_id=metric_id,
        used=used,
        limit=100,
        resets_at=resets.isoformat() if resets else None,
        period_ms=_period_ms(window) or default_ms,
    )


def classified_lines(
    rate_limit: Any,
    labels: tuple[str, str],
    ids: tuple[str, str],
    header: tuple[float | None, float | None],
    now: dt.datetime,
) -> list[model.Progress]:
    table = rate_limit if isinstance(rate_limit, dict) else {}
    slots: list[tuple[dict, float | None, str]] = []
    for key, fallback, head in (
        ("primary_window", "session", header[0]),
        ("secondary_window", "weekly", header[1]),
    ):
        raw = table.get(key)
        window = raw if isinstance(raw, dict) else ({} if head is not None else None)
        if window is None:
            continue
        used = parse.number(window.get("used_percent"))
        if used is None:
            used = head
        slots.append((window, used, fallback))
    out: list[model.Progress] = []
    for kind, label, metric_id, default in (
        ("session", labels[0], ids[0], SESSION_MS),
        ("weekly", labels[1], ids[1], WEEK_MS),
    ):
        picked: tuple[dict, float | None] | None = None
        for window, used, _fallback in slots:
            if _kind_of(window) == kind:
                picked = (window, used)
                break
        if picked is None:
            for window, used, fallback in slots:
                if _kind_of(window) is None and fallback == kind:
                    picked = (window, used)
                    break
        if picked is None:
            continue
        line = _window_line(label, metric_id, picked[1], picked[0], default, now)
        if line is not None:
            out.append(line)
    return out


def _is_spark(entry: dict) -> bool:
    for key in ("limit_name", "metered_feature"):
        text = str(entry.get(key) or "").lower()
        if "spark" in text:
            return True
    return False


def spark_lines(body: dict, now: dt.datetime) -> list[model.Progress]:
    raw = body.get("additional_rate_limits")
    if not isinstance(raw, list):
        return []
    for entry in raw:
        if not isinstance(entry, dict) or not _is_spark(entry):
            continue
        rate_limit = entry.get("rate_limit")
        if not isinstance(rate_limit, dict):
            continue
        return classified_lines(
            rate_limit, ("Spark", "Spark Weekly"), ("spark", "sparkWeekly"),
            (None, None), now,
        )
    return []


def _expiry(value: Any) -> dt.datetime | None:
    moment = parse.parse_time(value)
    if moment is not None:
        return moment
    seconds = parse.number(value)
    if seconds is None:
        return None
    try:
        return dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def reset_credits(
    body: dict, dedicated: bytes | None, dedicated_status: int | None
) -> model.Values | None:
    source: dict | None = None
    if dedicated is not None and dedicated_status is not None:
        if 200 <= dedicated_status < 300:
            payload = _http.parse_json_object(dedicated)
            if isinstance(payload, dict) and parse.number(payload.get("available_count")) is not None:
                source = payload
    if source is None:
        embedded = body.get("rate_limit_reset_credits")
        source = embedded if isinstance(embedded, dict) else None
    if source is None:
        return None
    count = parse.number(source.get("available_count"))
    if count is None or count < 0:
        return None
    expiries: list[str] = []
    credits = source.get("credits")
    if isinstance(credits, list):
        moments: list[dt.datetime] = []
        for credit in credits:
            if not isinstance(credit, dict):
                continue
            status = credit.get("status")
            if isinstance(status, str) and status != "available":
                continue
            moment = _expiry(credit.get("expires_at"))
            if moment is not None:
                moments.append(moment)
        expiries = [item.isoformat() for item in sorted(moments)]
    return model.Values(
        metric_id="rateLimitResets",
        values=(model.ScalarValue(number=float(int(count // 1)), kind="count", label="available"),),
        expiries_at=tuple(expiries),
    )


def credit_values(remaining: float) -> tuple[model.ScalarValue, ...]:
    credits = max(0, int(remaining // 1))
    dollars = float(credits) * CREDIT_USD_RATE
    return (
        model.ScalarValue(number=dollars, kind="dollars"),
        model.ScalarValue(number=float(credits), kind="count", label="credits"),
    )


def _credits_remaining(body: dict, headers: dict[str, str] | None) -> float | None:
    credits = body.get("credits")
    if isinstance(credits, dict):
        balance = parse.number(credits.get("balance"))
        if balance is not None:
            return balance
        if credits.get("has_credits") is False:
            return 0.0
    if headers:
        for key, value in headers.items():
            if key.lower() == "x-codex-credits-balance":
                return parse.number(value)
    return None


def format_plan(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    low = raw.lower()
    if low == "prolite":
        return "Pro 5x"
    if low == "pro":
        return "Pro 20x"
    if low == "self_serve_business_prolite":
        return "Business Premium"
    return parse.title_cased(raw)


def map_usage(
    body: bytes,
    headers: dict[str, str] | None,
    dedicated: bytes | None,
    dedicated_status: int | None,
    now: dt.datetime,
) -> tuple[dict[str, model.Metric], str | None]:
    payload = _http.parse_json_object(body)
    if payload is None:
        raise ValueError("invalid response")
    metrics: dict[str, model.Metric] = {}
    primary = secondary = None
    if headers:
        for key, value in headers.items():
            low = key.lower()
            if low == "x-codex-primary-used-percent":
                primary = parse.number(value)
            elif low == "x-codex-secondary-used-percent":
                secondary = parse.number(value)
    for line in classified_lines(
        payload.get("rate_limit"), ("Session", "Weekly"), ("session", "weekly"),
        (primary, secondary), now,
    ):
        metrics[line.metric_id] = line
    for line in spark_lines(payload, now):
        metrics[line.metric_id] = line
    resets = reset_credits(payload, dedicated, dedicated_status)
    if resets is not None:
        metrics["rateLimitResets"] = resets
    remaining = _credits_remaining(payload, headers)
    if remaining is not None:
        metrics["credits"] = model.Values(
            metric_id="credits", values=credit_values(remaining)
        )
    return metrics, format_plan(payload.get("plan_type"))
