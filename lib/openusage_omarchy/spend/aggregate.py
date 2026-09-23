"""Daily usage history. Accumulator plus scan merge, as upstream."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field


def day_key(moment: dt.datetime) -> str:
    local = moment.astimezone() if moment.tzinfo else moment
    return f"{local.year:04d}-{local.month:02d}-{local.day:02d}"


@dataclass(frozen=True)
class DailyUsageEntry:
    date: str
    total_tokens: int
    cost_usd: float | None = None


@dataclass(frozen=True)
class DailyUsageSeries:
    daily: tuple[DailyUsageEntry, ...] = ()


@dataclass(frozen=True)
class ModelUsageVariant:
    model: str
    total_tokens: int
    cost_usd: float | None = None


@dataclass(frozen=True)
class ModelUsageEntry:
    model: str
    total_tokens: int
    cost_usd: float | None = None
    variants: tuple[ModelUsageVariant, ...] | None = None


@dataclass(frozen=True)
class DailyModelUsageEntry:
    date: str
    models: tuple[ModelUsageEntry, ...] = ()


@dataclass(frozen=True)
class ModelUsageSeries:
    daily: tuple[DailyModelUsageEntry, ...] = ()


@dataclass(frozen=True)
class LogUsageScan:
    series: DailyUsageSeries
    model_usage: ModelUsageSeries | None = None
    unknown_by_day: dict[str, frozenset[str]] = field(default_factory=dict)
    fallback_by_day: dict[str, frozenset[str]] | None = None


class Accumulator:
    """Priced per-day usage plus per-model breakdown."""

    def __init__(self) -> None:
        self._tokens: dict[str, int] = {}
        self._cost: dict[str, float] = {}
        self._unknown: dict[str, set[str]] = {}
        self._models: dict[str, dict[str, list]] = {}
        self._fallback: dict[str, set[str]] = {}

    def add(self, day: str, tokens: int, cost: float, model: str,
            fallback: str | None = None) -> None:
        self._tokens[day] = self._tokens.get(day, 0) + tokens
        self._cost[day] = self._cost.get(day, 0.0) + cost
        slot = self._models.setdefault(day, {}).setdefault(model, [0, 0.0])
        slot[0] += tokens
        slot[1] += cost
        if fallback:
            self._fallback.setdefault(day, set()).add(fallback)

    def add_unknown(self, day: str, model: str) -> None:
        self._unknown.setdefault(day, set()).add(model)

    def build(self) -> LogUsageScan:
        daily = tuple(
            DailyUsageEntry(date=day, total_tokens=self._tokens.get(day, 0),
                            cost_usd=self._cost.get(day, 0.0))
            for day in sorted(self._tokens, reverse=True))
        model_days = []
        for day in sorted(self._models, reverse=True):
            models = tuple(
                ModelUsageEntry(model=name, total_tokens=vals[0], cost_usd=vals[1])
                for name, vals in self._models[day].items())
            model_days.append(DailyModelUsageEntry(date=day, models=models))
        unknown = {day: frozenset(names) for day, names in self._unknown.items()}
        fallback = ({day: frozenset(names) for day, names in self._fallback.items()}
                    if self._fallback else None)
        series = DailyUsageSeries(daily=daily)
        usage = ModelUsageSeries(daily=tuple(model_days)) if model_days else None
        # Keep model usage even when empty days exist, so merge stays lossless.
        if not model_days:
            usage = ModelUsageSeries(daily=())
        return LogUsageScan(series=series, model_usage=usage,
                            unknown_by_day=unknown, fallback_by_day=fallback)

    @staticmethod
    def merged(scans: list[LogUsageScan | None]) -> LogUsageScan | None:
        present = [scan for scan in scans if scan is not None]
        if not present:
            return None
        out = Accumulator()
        for scan in present:
            for day, names in (scan.fallback_by_day or {}).items():
                out._fallback.setdefault(day, set()).update(names)
            for entry in (scan.model_usage.daily if scan.model_usage else ()):
                for model in entry.models:
                    if model.cost_usd is None:
                        continue
                    out.add(entry.date, model.total_tokens, model.cost_usd, model.model)
            for day, names in scan.unknown_by_day.items():
                for name in names:
                    out.add_unknown(day, name)
        # Preserve days that carried only unknown models: they still warn.
        if not out._tokens and not any(scan.series.daily for scan in present):
            pass
        return out.build()
