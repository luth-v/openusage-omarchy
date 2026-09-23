"""Legacy /v1/usage projection. UI-oriented snapshots, dashboard order.

Values rows serialize as the original ``text`` shape (one combined value
string) so existing local integrations keep working; per-model hover details
stay UI-only. Display names never carry emails (G2): bare cards use the
family display name, extra account cards use "<Family> <n>".
"""

from __future__ import annotations

from .. import catalog, model
from . import limits


def _compact(number: float) -> str:
    value = float(number)
    for divisor, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(value) >= divisor:
            short = value / divisor
            text = f"{short:.1f}".rstrip("0").rstrip(".")
            return f"{text}{suffix}"
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}".rstrip("0").rstrip(".")


def _dollars(number: float) -> str:
    return f"${float(number):,.2f}"


def legacy_value_string(values: tuple[model.ScalarValue, ...]) -> str:
    """Combined display string: dollars in full, counts compact, joined."""
    parts = []
    for item in values:
        if item.kind == "dollars":
            parts.append(_dollars(item.number))
        else:
            text = _compact(item.number)
            parts.append(f"{text} {item.label}" if item.label else text)
    return " · ".join(parts)


def _label(table: catalog.Catalog, family: str, metric_id: str) -> str:
    provider = table.provider(family)
    entry = provider.metric(metric_id) if provider else None
    if entry is not None:
        return entry.metric_label or entry.label
    return metric_id


def _line(table: catalog.Catalog, family: str, metric_id: str,
          metric: model.Metric) -> dict:
    label = _label(table, family, metric_id)
    if isinstance(metric, model.Progress):
        fmt: dict = {"kind": metric.format_kind}
        if metric.suffix:
            fmt["suffix"] = metric.suffix
        out: dict = {
            "type": "progress",
            "label": label,
            "used": metric.used,
            "limit": metric.limit,
            "format": fmt,
            "color": None,
        }
        if metric.resets_at:
            out["resetsAt"] = metric.resets_at
        if metric.period_ms:
            out["periodDurationMs"] = metric.period_ms
        return out
    if isinstance(metric, model.Text):
        return {
            "type": "text",
            "label": label,
            "value": metric.value,
            "color": None,
            "subtitle": metric.subtitle or None,
        }
    if isinstance(metric, model.Values):
        out = {
            "type": "text",
            "label": label,
            "value": legacy_value_string(metric.values),
            "color": None,
            "subtitle": None,
        }
        if metric.expiries_at:
            out["resetsAt"] = sorted(metric.expiries_at)[0]
        return out
    if isinstance(metric, model.Badge):
        return {
            "type": "badge",
            "label": label,
            "text": metric.text,
            "color": None,
            "subtitle": None,
        }
    if isinstance(metric, model.Chart):
        out = {
            "type": "barChart",
            "label": label,
            "points": [point.to_dict() for point in metric.points],
            "color": None,
        }
        if metric.note:
            out["note"] = metric.note
        return out
    raise ValueError(f"unknown metric type: {type(metric).__name__}")


def _ordered_ids(table: catalog.Catalog, family: str,
                 metrics: dict[str, model.Metric]) -> list[str]:
    provider = table.provider(family)
    order = [item.metric_id for item in provider.metrics] if provider else []
    known = [key for key in order if key in metrics]
    known += sorted(key for key in metrics if key not in set(order))
    return known


def project(snapshots: dict[str, model.Snapshot],
            table: catalog.Catalog) -> list[dict]:
    """Snapshots in catalog order to legacy wire snapshots."""
    names = limits.display_names(list(snapshots), table)
    families = table.families()
    ordered = sorted(
        snapshots,
        key=lambda cid: (families.index(model.family_of(cid))
                         if model.family_of(cid) in families else len(families),
                         cid if ":" in cid else ""),
    )
    out = []
    for card_id in ordered:
        snapshot = snapshots[card_id]
        family = snapshot.card.family
        out.append({
            "providerId": card_id,
            "displayName": names.get(card_id, family),
            "plan": snapshot.plan,
            "lines": [_line(table, family, key, snapshot.metrics[key])
                      for key in _ordered_ids(table, family, snapshot.metrics)],
            "fetchedAt": snapshot.fetched_at,
        })
    return out
