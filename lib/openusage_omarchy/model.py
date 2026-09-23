"""Typed snapshots. Collectors return these; they never write files."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

FormatKind = Literal["percent", "dollars", "count"]


def family_of(card_id: str) -> str:
    return card_id.partition(":")[0]


@dataclass(frozen=True)
class CardRef:
    card_id: str
    family: str
    label: str
    account_key: str = ""


@dataclass(frozen=True)
class ErrorInfo:
    category: str
    message: str

    def to_dict(self) -> dict:
        return {"category": self.category, "message": self.message}

    @classmethod
    def from_dict(cls, raw: dict) -> "ErrorInfo":
        return cls(category=str(raw.get("category", "")), message=str(raw.get("message", "")))


@dataclass(frozen=True)
class Progress:
    metric_id: str
    used: float
    limit: float
    format_kind: str = "percent"
    suffix: str = ""
    resets_at: str | None = None
    period_ms: int | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "type": "progress",
            "used": self.used,
            "limit": self.limit,
            "format": {"kind": self.format_kind},
        }
        if self.suffix:
            out["format"]["suffix"] = self.suffix
        if self.resets_at:
            out["resetsAt"] = self.resets_at
        if self.period_ms:
            out["periodMs"] = self.period_ms
        return out


@dataclass(frozen=True)
class Text:
    metric_id: str
    value: str
    subtitle: str = ""

    def to_dict(self) -> dict:
        out: dict = {"type": "text", "value": self.value}
        if self.subtitle:
            out["subtitle"] = self.subtitle
        return out


@dataclass(frozen=True)
class Badge:
    metric_id: str
    text: str

    def to_dict(self) -> dict:
        return {"type": "badge", "text": self.text}


@dataclass(frozen=True)
class ScalarValue:
    number: float
    kind: str = "count"
    label: str = ""
    estimated: bool = False

    def to_dict(self) -> dict:
        out: dict = {"number": self.number, "kind": self.kind}
        if self.label:
            out["label"] = self.label
        if self.estimated:
            out["estimated"] = True
        return out

    @classmethod
    def from_dict(cls, raw: dict) -> "ScalarValue":
        return cls(
            number=float(raw.get("number", 0)),
            kind=str(raw.get("kind", "count")),
            label=str(raw.get("label", "")),
            estimated=bool(raw.get("estimated", False)),
        )


@dataclass(frozen=True)
class Values:
    """Unbounded numeric row (upstream MetricLine.values). Numbers stay raw so
    /v1/limits can project scalars and /v1/usage can join the display string."""

    metric_id: str
    values: tuple[ScalarValue, ...] = ()
    expiries_at: tuple[str, ...] = ()
    unknown_models: tuple[str, ...] = ()
    breakdown: dict | None = None

    def to_dict(self) -> dict:
        out: dict = {
            "type": "values",
            "values": [item.to_dict() for item in self.values],
        }
        if self.expiries_at:
            out["expiriesAt"] = list(self.expiries_at)
        if self.unknown_models:
            out["unknownModels"] = list(self.unknown_models)
        if self.breakdown is not None:
            out["modelBreakdown"] = self.breakdown
        return out


@dataclass(frozen=True)
class ChartPoint:
    label: str
    value: float
    value_label: str = ""

    def to_dict(self) -> dict:
        out: dict = {"label": self.label, "value": self.value}
        if self.value_label:
            out["valueLabel"] = self.value_label
        return out


@dataclass(frozen=True)
class Chart:
    metric_id: str
    points: tuple[ChartPoint, ...] = ()
    note: str = ""

    def to_dict(self) -> dict:
        out: dict = {"type": "chart", "points": [p.to_dict() for p in self.points]}
        if self.note:
            out["note"] = self.note
        return out


Metric = Union[Progress, Text, Badge, Chart, Values]


def metric_from_dict(metric_id: str, raw: dict) -> Metric:
    kind = raw.get("type")
    if kind == "progress":
        fmt = raw.get("format") or {}
        return Progress(
            metric_id=metric_id,
            used=float(raw.get("used", 0)),
            limit=float(raw.get("limit", 0)),
            format_kind=str(fmt.get("kind", "percent")),
            suffix=str(fmt.get("suffix", "")),
            resets_at=raw.get("resetsAt"),
            period_ms=raw.get("periodMs"),
        )
    if kind == "text":
        return Text(
            metric_id=metric_id,
            value=str(raw.get("value", "")),
            subtitle=str(raw.get("subtitle", "")),
        )
    if kind == "badge":
        return Badge(metric_id=metric_id, text=str(raw.get("text", "")))
    if kind == "values":
        items = tuple(
            ScalarValue.from_dict(item)
            for item in raw.get("values", [])
            if isinstance(item, dict)
        )
        expiries = tuple(
            str(item) for item in raw.get("expiriesAt", []) if isinstance(item, str)
        )
        unknown = tuple(
            str(item) for item in raw.get("unknownModels", []) if isinstance(item, str)
        )
        breakdown = raw.get("modelBreakdown")
        return Values(metric_id=metric_id, values=items, expiries_at=expiries,
                      unknown_models=unknown,
                      breakdown=breakdown if isinstance(breakdown, dict) else None)
    if kind == "chart":
        points = tuple(
            ChartPoint(
                label=str(p.get("label", "")),
                value=float(p.get("value", 0)),
                value_label=str(p.get("valueLabel", "")),
            )
            for p in raw.get("points", [])
            if isinstance(p, dict)
        )
        return Chart(metric_id=metric_id, points=points, note=str(raw.get("note", "")))
    raise ValueError(f"unknown metric type: {kind!r}")


@dataclass(frozen=True)
class Snapshot:
    card: CardRef
    plan: str | None
    fetched_at: str
    metrics: dict[str, Metric] = field(default_factory=dict, compare=False)
    error: ErrorInfo | None = None

    def to_dict(self) -> dict:
        return {
            "cardId": self.card.card_id,
            "family": self.card.family,
            "label": self.card.label,
            "accountKey": self.card.account_key,
            "plan": self.plan,
            "fetchedAt": self.fetched_at,
            "error": self.error.to_dict() if self.error else None,
            "metrics": {key: metric.to_dict() for key, metric in self.metrics.items()},
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "Snapshot":
        metrics: dict[str, Metric] = {}
        for key, item in (raw.get("metrics") or {}).items():
            if isinstance(item, dict):
                metrics[str(key)] = metric_from_dict(str(key), item)
        error = raw.get("error")
        return cls(
            card=CardRef(
                card_id=str(raw.get("cardId", "")),
                family=str(raw.get("family", "")),
                label=str(raw.get("label", "")),
                account_key=str(raw.get("accountKey", "")),
            ),
            plan=raw.get("plan"),
            fetched_at=str(raw.get("fetchedAt", "")),
            metrics=metrics,
            error=ErrorInfo.from_dict(error) if isinstance(error, dict) else None,
        )


class CollectorError(Exception):
    def __init__(self, category: str, message: str) -> None:
        super().__init__(message)
        self.category = category
        self.message = message
