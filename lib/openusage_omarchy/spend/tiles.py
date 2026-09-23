"""Spend tiles and trend. Ports upstream SpendTileMapper."""

from __future__ import annotations

import datetime as dt
import re

from .. import model
from .aggregate import (
    DailyUsageSeries, LogUsageScan, ModelUsageEntry, ModelUsageSeries,
    ModelUsageVariant, day_key,
)

OTHER = "Other"
UNATTRIBUTED = "Unattributed"
NAMED_CAP = 5
MIN_SHARE = 0.05


def _parse_day(raw: str) -> str | None:
    value = raw.strip()
    if not value:
        return None
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value
    try:
        moment = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return day_key(moment)
    except ValueError:
        pass
    match = re.match(r"^(\d{4}-\d{2}-\d{2})", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"\d{8}", value):
        return f"{value[:4]}-{value[4:6]}-{value[6:]}"
    try:
        moment = dt.datetime.strptime(value, "%b %d, %Y")
        return f"{moment.year:04d}-{moment.month:02d}-{moment.day:02d}"
    except ValueError:
        return None


def _has_usage(tokens: int, cost: float | None) -> bool:
    return tokens > 0 or (cost or 0) > 0


def _spend_values(tokens: int, cost: float | None,
                  estimated: bool) -> tuple[model.ScalarValue, ...]:
    out = []
    if cost is not None:
        out.append(model.ScalarValue(number=cost, kind="dollars", estimated=estimated))
    out.append(model.ScalarValue(number=float(tokens), kind="count", label="tokens"))
    return tuple(out)


def _round_cents(value: float) -> float:
    return round(value * 100) / 100


def _fallback_title(value: str) -> str:
    parts = []
    for chunk in value.split("-"):
        low = chunk.lower()
        if low == "gpt":
            parts.append("GPT")
        elif low in ("o1", "o3", "o4"):
            parts.append(chunk)
        elif chunk:
            parts.append(chunk[:1].upper() + chunk[1:])
    return " ".join(parts)


def source_note(base: str, by_day: dict[str, frozenset[str]] | None,
                days: set[str]) -> str:
    if not by_day:
        return base
    names: set[str] = set()
    for day in days:
        names.update(by_day.get(day, frozenset()))
    if not names:
        return base
    joined = ", ".join(_fallback_title(name) for name in sorted(names))
    return f"{base} · Fallback estimates: {joined}"


def _best_spelling(votes: dict[str, int]) -> str | None:
    best: str | None = None
    best_key = None
    for spelling, weight in votes.items():
        key = (-weight, not (spelling == spelling.lower()), spelling)
        if best_key is None or key < best_key:
            best_key = key
            best = spelling
    return best


def _fold_list(entries: list[ModelUsageEntry]) -> list[ModelUsageEntry]:
    priced = all(item.cost_usd is not None for item in entries)
    cost_total = sum(item.cost_usd or 0 for item in entries)
    token_total = sum(item.total_tokens for item in entries)

    def _share(entry: ModelUsageEntry) -> float:
        if priced and cost_total > 0:
            return (entry.cost_usd or 0) / cost_total
        return (entry.total_tokens / token_total) if token_total else 0

    visible: list[ModelUsageEntry] = []
    other_tokens = 0
    other_cost = 0.0
    other_seen = False
    other_variants: dict[str, list] = {}
    named = 0
    for entry in entries:
        unattributed = entry.model.lower() == UNATTRIBUTED.lower()
        if unattributed or _share(entry) < MIN_SHARE:
            other_tokens += entry.total_tokens
            if entry.cost_usd is not None:
                other_cost += entry.cost_usd
                other_seen = True
            slot = other_variants.setdefault(entry.model.lower(), [entry.model, 0, 0.0, False])
            slot[1] += entry.total_tokens
            if entry.cost_usd is not None:
                slot[2] += entry.cost_usd
                slot[3] = True
        elif entry.cost_usd is None:
            visible.append(entry)
            named += 1
        elif named < NAMED_CAP:
            visible.append(entry)
            named += 1
        else:
            other_tokens += entry.total_tokens
            other_cost += entry.cost_usd or 0
            other_seen = other_seen or entry.cost_usd is not None
            slot = other_variants.setdefault(entry.model.lower(), [entry.model, 0, 0.0, False])
            slot[1] += entry.total_tokens
            if entry.cost_usd is not None:
                slot[2] += entry.cost_usd
                slot[3] = True
    if other_tokens > 0 or other_cost > 0:
        variants = tuple(
            ModelUsageVariant(model=vals[0], total_tokens=vals[1],
                              cost_usd=_round_cents(vals[2]) if vals[3] else None)
            for _, vals in sorted(other_variants.items()))
        visible.append(ModelUsageEntry(
            model=OTHER, total_tokens=other_tokens,
            cost_usd=_round_cents(other_cost) if other_seen else None,
            variants=variants or None))
    return visible


def _breakdown(usage: ModelUsageSeries | None, days: set[str], tokens: int,
               cost: float | None, note: str | None,
               fallback: dict[str, frozenset[str]] | None) -> dict | None:
    if usage is None or note is None or not days:
        return None
    # Merge by folded name with spelling vote and variant lines.
    groups: dict[str, dict] = {}
    for day in usage.daily:
        key = _parse_day(day.date)
        if key is None or key not in days:
            continue
        for item in day.models:
            if item.total_tokens <= 0 and (item.cost_usd or 0) <= 0:
                continue
            name = item.model.strip() or UNATTRIBUTED
            slot = groups.setdefault(name.lower(), {
                "votes": {}, "tokens": 0, "cost": 0.0, "seen": False, "variants": {}})
            slot["votes"][name] = slot["votes"].get(name, 0) + max(item.total_tokens, 1)
            slot["tokens"] += item.total_tokens
            if item.cost_usd is not None:
                slot["cost"] += item.cost_usd
                slot["seen"] = True
            lines = item.variants or (ModelUsageVariant(
                model=name, total_tokens=item.total_tokens, cost_usd=item.cost_usd),)
            for variant in lines:
                keyed = slot["variants"].setdefault(
                    variant.model.lower(), {"votes": {}, "tokens": 0, "cost": 0.0, "seen": False})
                keyed["votes"][variant.model] = keyed["votes"].get(variant.model, 0) + max(
                    variant.total_tokens, 1)
                keyed["tokens"] += variant.total_tokens
                if variant.cost_usd is not None:
                    keyed["cost"] += variant.cost_usd
                    keyed["seen"] = True
    entries: list[ModelUsageEntry] = []
    for folded, slot in groups.items():
        display = _best_spelling(slot["votes"]) or folded
        variants = []
        for _, info in slot["variants"].items():
            spelling = _best_spelling(info["votes"]) or display
            variants.append(ModelUsageVariant(
                model=spelling, total_tokens=info["tokens"],
                cost_usd=_round_cents(info["cost"]) if info["seen"] else None))
        variants.sort(key=lambda v: (-(v.cost_usd or 0), -v.total_tokens, v.model.lower()))
        trivial = len(variants) == 1 and variants[0].model.lower() == display.lower()
        entries.append(ModelUsageEntry(
            model=display, total_tokens=slot["tokens"],
            cost_usd=_round_cents(slot["cost"]) if slot["seen"] else None,
            variants=None if trivial else tuple(variants)))
    entries.sort(key=lambda e: (-(e.cost_usd or 0), -e.total_tokens, e.model.lower()))
    folded = _fold_list(entries)
    if not folded:
        return None
    return {
        "totalTokens": tokens,
        "totalCostUSD": cost,
        "models": [
            {"model": item.model, "totalTokens": item.total_tokens,
             "costUSD": item.cost_usd,
             **({"variants": [
                 {"model": v.model, "totalTokens": v.total_tokens, "costUSD": v.cost_usd}
                 for v in item.variants]} if item.variants else {})}
            for item in folded],
        "sourceNote": source_note(note, fallback, days),
    }


def append_token_usage(scan: DailyUsageSeries,
                       metrics: dict[str, model.Metric],
                       now: dt.datetime,
                       estimated: bool = True,
                       unknown_by_day: dict[str, frozenset[str]] | None = None,
                       model_usage: ModelUsageSeries | None = None,
                       model_note: str | None = None,
                       fallback_by_day: dict[str, frozenset[str]] | None = None,
                       ids: tuple[str, str, str] = ("today", "yesterday", "last30"),
                       labels: tuple[str, str, str] = ("Today", "Yesterday", "Last 30 Days")) -> None:
    unknown_by_day = unknown_by_day or {}
    today = day_key(now)
    yesterday = day_key(now - dt.timedelta(days=1))
    by_day: dict[str, tuple[int, float | None]] = {}
    for entry in scan.daily:
        key = _parse_day(entry.date)
        if key is None:
            continue
        tokens, cost = by_day.get(key, (0, 0.0))
        merged_cost = (cost or 0) + (entry.cost_usd or 0)
        by_day[key] = (tokens + entry.total_tokens,
                       merged_cost if (cost is not None or entry.cost_usd is not None) else None)
    # Today and Yesterday keep raw daily cost; Last30 snaps to cents once.
    for day, metric_id in ((today, ids[0]), (yesterday, ids[1])):
        if day not in by_day:
            continue
        tokens, cost = by_day[day]
        if not _has_usage(tokens, cost):
            continue
        unknown = sorted(unknown_by_day.get(day, frozenset()))
        metrics[metric_id] = model.Values(
            metric_id=metric_id,
            values=_spend_values(tokens, cost, estimated),
            unknown_models=tuple(unknown),
            breakdown=_breakdown(model_usage, {day}, tokens, cost,
                                 model_note, fallback_by_day))
    total_tokens = sum(tokens for tokens, _ in by_day.values())
    costs = [cost for _, cost in by_day.values() if cost is not None]
    total_cost = round(sum(costs) * 100) / 100 if costs else None
    if _has_usage(total_tokens, total_cost):
        union: set[str] = set()
        for names in unknown_by_day.values():
            union.update(names)
        metrics[ids[2]] = model.Values(
            metric_id=ids[2],
            values=_spend_values(total_tokens, total_cost, estimated),
            unknown_models=tuple(sorted(union)),
            breakdown=_breakdown(model_usage, set(by_day), total_tokens,
                                 total_cost, model_note, fallback_by_day))


def _format_count(value: float) -> str:
    sign = "-" if value < 0 else ""
    rest = abs(value)
    for bound, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if rest >= bound:
            text = f"{rest / bound:.1f}".rstrip("0").rstrip(".")
            return f"{sign}{text}{suffix}"
    if rest == int(rest):
        return f"{sign}{int(rest)}"
    return f"{sign}{rest:.1f}".rstrip("0").rstrip(".")


_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def append_trend(scan: DailyUsageSeries, metrics: dict[str, model.Metric],
                 now: dt.datetime, note: str,
                 fallback_by_day: dict[str, frozenset[str]] | None = None,
                 metric_id: str = "trend") -> None:
    tokens_by_day: dict[str, float] = {}
    for entry in scan.daily:
        key = _parse_day(entry.date)
        if key is None or entry.total_tokens < 0:
            continue
        tokens_by_day[key] = tokens_by_day.get(key, 0) + entry.total_tokens
    if not any(value > 0 for value in tokens_by_day.values()):
        return
    local = now.astimezone() if now.tzinfo else now
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    points: list[model.ChartPoint] = []
    for offset in range(30, -1, -1):
        day = start - dt.timedelta(days=offset)
        key = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
        tokens = tokens_by_day.get(key, 0)
        label = f"{_MONTHS[day.month - 1]} {day.day}"
        points.append(model.ChartPoint(
            label=label, value=tokens,
            value_label=f"{_format_count(tokens)} tokens"))
    days = set(tokens_by_day) & {
        f"{(start - dt.timedelta(days=offset)).year:04d}-"
        f"{(start - dt.timedelta(days=offset)).month:02d}-"
        f"{(start - dt.timedelta(days=offset)).day:02d}"
        for offset in range(31)}
    metrics[metric_id] = model.Chart(
        metric_id=metric_id, points=tuple(points),
        note=source_note(note, fallback_by_day, days))
