"""state.json publisher. The daemon is its sole writer. Atomic, 0600."""

from __future__ import annotations

import datetime as dt

from .. import STATE_SCHEMA, atomic, catalog, log, model, paths
from ..engine.refresh import Batch


def _stale(fetched_at: str, now: dt.datetime) -> bool:
    try:
        moment = dt.datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return True
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return (now - moment).total_seconds() >= 300


def _empty_period() -> dict:
    return {"cost": None, "tokens": 0, "byProvider": {}, "byModel": {}}



def _spend_values(metric: model.Metric) -> tuple[float | None, int, dict | None]:
    if not isinstance(metric, model.Values):
        return None, 0, None
    cost: float | None = None
    tokens = 0
    for item in metric.values:
        if item.kind == "dollars" and cost is None:
            cost = item.number
        elif item.kind == "dollars" and cost is not None:
            cost += item.number
        if item.kind == "count" and item.label == "tokens":
            tokens += int(item.number)
    if cost is None and tokens <= 0:
        return None, 0, None
    return cost, tokens, metric.breakdown


def _period(snapshots: dict[str, model.Snapshot], metric_id: str) -> dict:
    by_provider: dict[str, dict] = {}
    by_model: dict[str, dict] = {}
    total_cost: float | None = None
    total_tokens = 0
    for card_id, snap in snapshots.items():
        if snap.card.family not in catalog.cached().spend_families():
            continue
        metric = snap.metrics.get(metric_id)
        cost, tokens, breakdown = _spend_values(metric) if metric else (None, 0, None)
        if cost is None and tokens <= 0:
            continue
        by_provider[card_id] = {"cost": cost, "tokens": tokens}
        total_tokens += tokens
        if cost is not None:
            total_cost = (total_cost or 0) + cost
        if isinstance(breakdown, dict):
            for entry in breakdown.get("models") or []:
                if not isinstance(entry, dict):
                    continue
                name = str(entry.get("model") or "").strip()
                if not name:
                    continue
                slot = by_model.setdefault(name, {"cost": None, "tokens": 0})
                slot["tokens"] += int(entry.get("totalTokens") or 0)
                item_cost = entry.get("costUSD")
                if isinstance(item_cost, (int, float)):
                    slot["cost"] = (slot["cost"] or 0) + float(item_cost)
    # Round merged model costs to cents once, as tiles do per period.
    for slot in by_model.values():
        if slot["cost"] is not None:
            slot["cost"] = round(slot["cost"] * 100) / 100
    if total_cost is not None:
        total_cost = round(total_cost * 100) / 100
    return {"cost": total_cost, "tokens": total_tokens,
            "byProvider": by_provider, "byModel": by_model}


def _trend(snapshots: dict[str, model.Snapshot], now: dt.datetime) -> dict:
    local = now.astimezone() if now.tzinfo else now
    start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    out: dict[str, list[dict]] = {}
    for card_id, snap in snapshots.items():
        if snap.card.family not in catalog.cached().spend_families():
            continue
        metric = snap.metrics.get("trend")
        if not isinstance(metric, model.Chart) or not metric.points:
            continue
        count = len(metric.points)
        days = []
        for index, point in enumerate(metric.points):
            # Oldest first; map index back to calendar day.
            offset = count - 1 - index
            day = start - dt.timedelta(days=offset)
            key = f"{day.year:04d}-{day.month:02d}-{day.day:02d}"
            days.append({"day": key, "tokens": int(point.value), "cost": None})
        out[card_id] = days
    return out


def build(
    table: catalog.Catalog,
    batch: Batch | None,
    detected: dict[str, bool],
    session_id: str,
    version: str,
    now: dt.datetime,
    in_flight: list[str],
    next_at: dt.datetime | None,
    secrets: dict[str, str] | None = None,
    pricing: tuple[str, str | None] | None = None,
    last_claims: dict[str, dict] | None = None,
    codex_options: list[dict] | None = None,
    update: dict | None = None,
    api_listening: bool = False,
    claude_accounts: list[dict] | None = None,
) -> dict:
    by_card: dict[str, tuple[model.Snapshot | None, model.ErrorInfo | None]] = {}
    # Labels come from the current card list, not the last-good snapshot, so
    # a renamed Account shows its new label while its data is still stale.
    labels: dict[str, str] = {}
    last_ended: str | None = None
    if batch is not None:
        for item in batch.results:
            by_card[item.card.card_id] = (item.snapshot, item.error)
            labels[item.card.card_id] = item.card.label
        if batch.ended_at is not None:
            last_ended = batch.ended_at.isoformat()
    cards = []
    extra_ids = sorted(card_id for card_id in by_card if ":" in card_id)

    def _row(
        card_id: str, provider_id: str, display: str,
        snapshot: model.Snapshot | None, error: model.ErrorInfo | None,
        last_claims: dict[str, dict],
    ) -> dict:
        fetched = snapshot.fetched_at if snapshot else None
        return {
            "cardId": card_id,
            "family": provider_id,
            "label": labels.get(card_id) or (snapshot.card.label if snapshot else display),
            "detected": bool(detected.get(provider_id, False)),
            "plan": snapshot.plan if snapshot else None,
            "fetchedAt": fetched,
            "stale": _stale(fetched, now) if fetched else True,
            "error": error.to_dict() if error else None,
            "lastClaim": last_claims.get(card_id),
            "metrics": (
                {key: item.to_dict() for key, item in snapshot.metrics.items()}
                if snapshot
                else {}
            ),
        }

    claims = last_claims or {}
    for provider in table.providers:
        snapshot, error = by_card.get(provider.provider_id, (None, None))
        cards.append(
            _row(
                provider.provider_id, provider.provider_id,
                provider.display_name, snapshot, error, claims,
            )
        )
        for card_id in extra_ids:
            snapshot, error = by_card[card_id]
            provider_id = snapshot.card.family if snapshot else model.family_of(card_id)
            if provider_id != provider.provider_id:
                continue
            label = snapshot.card.label if snapshot else provider.display_name
            cards.append(_row(card_id, provider.provider_id, label,
                              snapshot, error, claims))
    snapshots = {card_id: snap for card_id, (snap, _)
                 in by_card.items() if snap is not None}
    source, fetched = pricing or ("bundled", None)
    return {
        "schema": STATE_SCHEMA,
        "generatedAt": now.isoformat(),
        "daemon": {"version": version, "sessionId": session_id,
                   "apiListening": api_listening},
        "refresh": {
            "inFlight": sorted(in_flight),
            "nextAt": next_at.isoformat() if next_at else None,
            "lastBatchEndedAt": last_ended,
        },
        "cards": cards,
        "spend": {
            "periods": {
                "today": _period(snapshots, "today"),
                "yesterday": _period(snapshots, "yesterday"),
                "last30": _period(snapshots, "last30"),
            },
            "trend": _trend(snapshots, now),
        },
        "pricing": {"source": source, "fetchedAt": fetched,
                    "codexFallbackOptions": list(codex_options or [])},
        # Discovered Claude config dirs for Settings; never emails (ADR 0006).
        "claudeAccounts": list(claude_accounts or []),
        "update": dict(update) if update is not None else {
            "latest": None,
            "channel": "stable",
            "checkedAt": None,
            "snoozed": None,
            "installable": False,
        },
        "secrets": (
            {item.provider_id: secrets.get(item.provider_id, "none")
             for item in table.providers}
            if secrets is not None else
            {item.provider_id: "none" for item in table.providers}
        ),
    }


def publish(dirs: paths.Paths, state: dict) -> None:
    paths.assert_writable(dirs.state_file, dirs.home)
    atomic.write_json_atomic(dirs.state_file, state)
    log.get_logger("refresh").debug("published state.json")
