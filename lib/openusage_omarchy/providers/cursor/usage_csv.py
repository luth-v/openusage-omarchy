"""Cursor usage CSV. Export parse plus spend aggregation."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from ... import parse as _parse
from ...spend.aggregate import (
    DailyModelUsageEntry, DailyUsageEntry, DailyUsageSeries, LogUsageScan,
    ModelUsageEntry, ModelUsageSeries, ModelUsageVariant, day_key,
)
from ...spend.pricing import ModelPricing
from ...spend.rates import TokenBreakdown

REQUIRED = ("Date", "Model", "Input (w/ Cache Write)", "Input (w/o Cache Write)",
            "Cache Read", "Output Tokens")
EXPORT_URL = "https://cursor.com/api/dashboard/export-usage-events-csv"


class CsvError(Exception):
    pass


def _split_rows(text: str) -> list[list[str]] | None:
    rows: list[list[str]] = []
    field: list[str] = []
    current = ""
    quoted = False
    closed = False
    index = 0
    chars = text
    length = len(chars)
    row: list[str] = []

    def _emit() -> None:
        if not all(item == "" for item in row):
            rows.append(list(row))

    while index < length:
        char = chars[index]
        if quoted:
            if char == '"':
                nxt = chars[index + 1] if index + 1 < length else ""
                if nxt == '"':
                    current += '"'
                    index += 2
                    continue
                quoted = False
                closed = True
                index += 1
                continue
            current += char
            index += 1
            continue
        if closed:
            if char == ",":
                row.append(current)
                current = ""
                closed = False
            elif char in ("\r", "\n"):
                row.append(current)
                _emit()
                row = []
                current = ""
                closed = False
                if char == "\r" and index + 1 < length and chars[index + 1] == "\n":
                    index += 1
            else:
                return None
            index += 1
            continue
        if char == '"':
            if current:
                return None
            quoted = True
        elif char == ",":
            row.append(current)
            current = ""
        elif char in ("\r", "\n"):
            row.append(current)
            _emit()
            row = []
            current = ""
            if char == "\r" and index + 1 < length and chars[index + 1] == "\n":
                index += 1
        else:
            current += char
        index += 1
    if quoted:
        return None
    if current or row or closed:
        row.append(current)
        _emit()
    _ = field
    return rows


def _parse_date(raw: str) -> dt.datetime | None:
    text = raw.strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S",
                "%Y-%m-%d %H:%M:%S"):
        candidate = text
        if fmt.endswith("%z") and candidate.endswith("Z"):
            candidate = candidate[:-1] + "+0000"
            fmt_clean = fmt
        elif candidate.endswith("Z") and "%z" not in fmt:
            continue
        else:
            fmt_clean = fmt
        try:
            moment = dt.datetime.strptime(candidate, fmt_clean)
            return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)
        except ValueError:
            continue
    # ISO with colon offset.
    try:
        moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        return moment if moment.tzinfo else moment.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def _parse_int(raw: str | None) -> int | None:
    if raw is None:
        return None
    text = raw.strip()
    if not text:
        return 0
    groups = text.split(",")
    if len(groups) > 1:
        if not 1 <= len(groups[0]) <= 3 or not groups[0].isdigit():
            return None
        for group in groups[1:]:
            if len(group) != 3 or not group.isdigit():
                return None
        text = "".join(groups)
    elif not text.isdigit():
        return None
    try:
        return int(text)
    except ValueError:
        return None


@dataclass(frozen=True)
class CsvRow:
    moment: dt.datetime
    model: str
    tokens: TokenBreakdown
    cost: float | None


def parse_csv(text: str, pricing: ModelPricing) -> tuple[list[CsvRow], int]:
    rows = _split_rows(text)
    if rows is None:
        raise CsvError("malformed CSV")
    if not rows:
        raise CsvError("missing columns: " + ", ".join(REQUIRED))
    header = [item.strip().lstrip("\ufeff") for item in rows[0]]
    if len(set(header)) != len(header):
        raise CsvError("malformed CSV")
    missing = [name for name in REQUIRED if name not in header]
    if missing:
        raise CsvError("missing columns: " + ", ".join(missing))
    index = {name: header.index(name) for name in header}
    out: list[CsvRow] = []
    rejected = 0
    accepted = 0
    for record in rows[1:]:
        if len(record) != len(header):
            rejected += 1
            continue
        moment = _parse_date(record[index["Date"]])
        name = record[index["Model"]].strip()
        cache_write = _parse_int(record[index["Input (w/ Cache Write)"]])
        plain = _parse_int(record[index["Input (w/o Cache Write)"]])
        read = _parse_int(record[index["Cache Read"]])
        output = _parse_int(record[index["Output Tokens"]])
        if moment is None or not name or None in (cache_write, plain, read, output):
            rejected += 1
            continue
        assert cache_write is not None and plain is not None
        assert read is not None and output is not None
        total = cache_write + plain + read + output
        if accepted + total > 2 ** 63 - 1:
            rejected += 1
            continue
        accepted += total
        tokens = TokenBreakdown(input=plain, cache_write_5m=cache_write,
                                cache_read=read, output=output)
        cost = pricing.estimated_cost(name, tokens, long_rates=False)
        out.append(CsvRow(moment=moment, model=name, tokens=tokens, cost=cost))
    return out, rejected


def to_scan(rows: list[CsvRow]) -> LogUsageScan:
    from ...spend.aggregate import Accumulator
    costs: dict[str, float] = {}
    tokens: dict[str, int] = {}
    models: dict[str, dict[str, dict]] = {}
    unknown: dict[str, set[str]] = {}
    for row in rows:
        day = day_key(row.moment)
        name = row.model.strip()
        if row.cost is None:
            if row.tokens.total_tokens > 0 and name:
                unknown.setdefault(day, set()).add(name)
            continue
        costs[day] = costs.get(day, 0.0) + row.cost
        tokens[day] = tokens.get(day, 0) + row.tokens.total_tokens
        # Family groups by canonical key minus -fast; raw slug stays a variant.
        slot = models.setdefault(day, {})
        # The caller passes pricing for family; here keep raw name and let
        # aggregate_to_scan regroup. This path keeps raw names.
        entry = slot.setdefault(name or "Unattributed", {"tokens": 0, "cost": 0.0, "variants": {}})
        entry["tokens"] += row.tokens.total_tokens
        entry["cost"] += row.cost
        variant = entry["variants"].setdefault(name, [0, 0.0])
        variant[0] += row.tokens.total_tokens
        variant[1] += row.cost
    _ = Accumulator
    daily = tuple(
        DailyUsageEntry(date=day, total_tokens=tokens[day],
                        cost_usd=round(costs[day] * 100) / 100)
        for day in sorted(tokens, reverse=True))
    model_days = []
    for day in sorted(models, reverse=True):
        items = []
        for name, info in models[day].items():
            variants = tuple(
                ModelUsageVariant(model=slug, total_tokens=vals[0], cost_usd=vals[1])
                for slug, vals in info["variants"].items())
            trivial = len(variants) == 1 and variants[0].model == name
            items.append(ModelUsageEntry(
                model=name, total_tokens=info["tokens"], cost_usd=info["cost"],
                variants=None if trivial else variants))
        model_days.append(DailyModelUsageEntry(date=day, models=tuple(items)))
    return LogUsageScan(
        series=DailyUsageSeries(daily=daily),
        model_usage=ModelUsageSeries(daily=tuple(model_days)),
        unknown_by_day={day: frozenset(names) for day, names in unknown.items()},
        fallback_by_day=None)


def to_scan_with_pricing(rows: list[CsvRow], pricing: ModelPricing) -> LogUsageScan:
    """CSV rows grouped by pricing family, with effort slugs as variants."""
    costs: dict[str, float] = {}
    tokens: dict[str, int] = {}
    models: dict[str, dict[str, dict]] = {}
    unknown: dict[str, set[str]] = {}
    for row in rows:
        day = day_key(row.moment)
        name = row.model.strip()
        if row.cost is None:
            if row.tokens.total_tokens > 0 and name:
                unknown.setdefault(day, set()).add(name)
            continue
        costs[day] = costs.get(day, 0.0) + row.cost
        tokens[day] = tokens.get(day, 0) + row.tokens.total_tokens
        display = name or "Unattributed"
        family = display if not name else pricing.family_name(name, ["-fast"])
        slot = models.setdefault(day, {})
        entry = slot.setdefault(family, {"tokens": 0, "cost": 0.0, "variants": {}})
        entry["tokens"] += row.tokens.total_tokens
        entry["cost"] += row.cost
        variant = entry["variants"].setdefault(display, [0, 0.0])
        variant[0] += row.tokens.total_tokens
        variant[1] += row.cost
    daily = tuple(
        DailyUsageEntry(date=day, total_tokens=tokens[day],
                        cost_usd=round(costs[day] * 100) / 100)
        for day in sorted(tokens, reverse=True))
    model_days = []
    for day in sorted(models, reverse=True):
        items = []
        for name, info in models[day].items():
            variants = tuple(
                ModelUsageVariant(model=slug, total_tokens=vals[0], cost_usd=vals[1])
                for slug, vals in info["variants"].items())
            trivial = len(variants) == 1 and variants[0].model == name
            items.append(ModelUsageEntry(
                model=name, total_tokens=info["tokens"], cost_usd=info["cost"],
                variants=None if trivial else variants))
        model_days.append(DailyModelUsageEntry(date=day, models=tuple(items)))
    return LogUsageScan(
        series=DailyUsageSeries(daily=daily),
        model_usage=ModelUsageSeries(daily=tuple(model_days)),
        unknown_by_day={day: frozenset(names) for day, names in unknown.items()},
        fallback_by_day=None)


def csv_url(start_ms: int, end_ms: int) -> str:
    from urllib.parse import urlencode
    query = urlencode({"startDate": start_ms, "endDate": end_ms, "strategy": "tokens"})
    return f"{EXPORT_URL}?{query}"
