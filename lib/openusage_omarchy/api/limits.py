"""Machine-facing limits envelope. The exact shape of GET /v1/limits.

Progress rows carry their live unit (percent, usd, or the count suffix).
Values rows project scalars by kind and label, as upstream WireResource.
"""

from __future__ import annotations

import datetime as dt

from .. import LIMITS_SCHEMA, REFRESH_INTERVAL_S, catalog, model

# (family, resource) -> (kind, unit, value_kind, value_label).
# Progress-backed resources are absent here; their unit comes from the row.
VALUES: dict[tuple[str, str], tuple[str, str, str, str | None]] = {
    ("claude", "extraUsage"): ("consumption", "usd", "dollars", None),
    ("claude", "rateLimitResets"): ("balance", "resets", "count", "available"),
    ("codex", "credits"): ("balance", "credits", "count", "credits"),
    ("codex", "creditValue"): ("balance", "usd", "dollars", None),
    ("codex", "rateLimitResets"): ("balance", "resets", "count", "available"),
    ("cursor", "onDemand"): ("consumption", "usd", "dollars", None),
    ("cursor", "credits"): ("balance", "usd", "dollars", None),
    ("openrouter", "balance"): ("balance", "usd", "dollars", None),
    ("copilot", "extraUsage"): ("consumption", "count", "count", None),
    ("copilot", "premiumCredits"): ("consumption", "credits", "count", None),
    ("copilot", "orgCredits"): ("balance", "credits", "count", "credits"),
    ("copilot", "orgSpend"): ("balance", "usd", "dollars", None),
    ("devin", "extraUsageBalance"): ("balance", "usd", "dollars", None),
}

# Balance resources served from progress rows (kept for later providers).
BALANCE: set[tuple[str, str]] = set()


def match_cards(wanted: str, cards: list[model.CardRef]) -> list[model.CardRef]:
    """Exact card id names one card; a family id names every card of it."""
    exact = [card for card in cards if card.card_id == wanted]
    if exact:
        return exact
    return [card for card in cards if card.family == wanted]


def display_names(card_ids: list[str], table: catalog.Catalog) -> dict[str, str]:
    """API display names without PII (G2): bare cards use the family name,
    extra account cards use "<Family> <n>". Snapshot labels may hold emails
    and are never used here."""
    by_family: dict[str, list[str]] = {}
    for card_id in sorted(set(card_ids)):
        family = model.family_of(card_id)
        by_family.setdefault(family, []).append(card_id)
    out: dict[str, str] = {}
    for family, ids in by_family.items():
        provider = table.provider(family)
        shown = provider.display_name if provider else family
        ordered = sorted(ids, key=lambda item: (item != family, item))
        for index, card_id in enumerate(ordered):
            out[card_id] = shown if index == 0 else f"{shown} {index + 1}"
    return out


def _parse_time(raw: str) -> dt.datetime | None:
    try:
        moment = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def _progress_resource(metric: model.Progress, kind: str = "consumption") -> dict:
    unit = {"percent": "percent", "dollars": "usd"}.get(
        metric.format_kind, metric.suffix or "count"
    )
    used = max(0.0, metric.used)
    limit = max(0.0, metric.limit)
    if kind == "balance":
        out: dict = {"kind": "balance", "unit": unit, "available": used}
    else:
        out = {
            "kind": "consumption",
            "unit": unit,
            "used": used,
            "limit": limit,
            "remaining": max(0.0, limit - used),
        }
        if limit > 0:
            out["utilization"] = used / limit
    if metric.resets_at:
        out["resetsAt"] = metric.resets_at
    if metric.period_ms:
        out["windowSeconds"] = metric.period_ms / 1000
    return out


def _values_resource(
    metric: model.Values, kind: str, unit: str, value_kind: str,
    value_label: str | None,
) -> dict | None:
    picked = None
    for item in metric.values:
        if item.kind != value_kind:
            continue
        if value_label is not None and item.label != value_label:
            continue
        picked = item
        break
    if picked is None:
        return None
    if kind == "balance":
        out: dict = {"kind": "balance", "unit": unit, "available": picked.number}
    else:
        out = {"kind": "consumption", "unit": unit, "used": picked.number}
    if metric.expiries_at:
        out["expiresAt"] = sorted(metric.expiries_at)
    if picked.estimated:
        out["estimated"] = True
    return out


def project(
    snapshots: dict[str, model.Snapshot],
    errors: dict[str, model.ErrorInfo],
    table: catalog.Catalog,
    generated_at: dt.datetime,
) -> dict:
    providers: dict[str, dict] = {}
    names = display_names(list(snapshots), table)
    for card_id, snapshot in snapshots.items():
        family = table.provider(snapshot.card.family)
        if family is None:
            continue
        fetched = _parse_time(snapshot.fetched_at) or generated_at
        expiry = fetched + dt.timedelta(seconds=REFRESH_INTERVAL_S)
        resources: dict[str, dict] = {}
        for metric_id, metric in snapshot.metrics.items():
            entry = family.metric(metric_id)
            if entry is None or not entry.api_resources:
                continue
            for key in entry.api_resources:
                spec = VALUES.get((family.provider_id, key))
                if isinstance(metric, model.Progress):
                    kind = spec[0] if spec else "consumption"
                    resources[key] = _progress_resource(metric, kind)
                elif isinstance(metric, model.Values):
                    if spec is None:
                        continue
                    kind, unit, value_kind, value_label = spec
                    resource = _values_resource(
                        metric, kind, unit, value_kind, value_label)
                    if resource is not None:
                        resources[key] = resource
        providers[card_id] = {
            "displayName": names.get(card_id, family.display_name),
            "plan": snapshot.plan,
            "fetchedAt": fetched.isoformat(),
            "expiresAt": expiry.isoformat(),
            "stale": generated_at >= expiry,
            "resources": resources,
        }
    return {
        "schema": LIMITS_SCHEMA,
        "generatedAt": generated_at.isoformat(),
        "providers": providers,
        "errors": [
            {"providerId": card_id, "message": err.message}
            for card_id, err in errors.items()
        ],
    }
