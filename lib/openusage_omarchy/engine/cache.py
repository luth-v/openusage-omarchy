"""Last-good snapshot cache. Stale-while-revalidate lives here.

One file per card under snapshots/, guarded by a per-card flock. A cache entry
counts as fresh only when fetched during this login session and younger than
the refresh interval. Holds no tokens: snapshots, identity hashes, offsets.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

from .. import REFRESH_INTERVAL_S, atomic, log, model

SCHEMA = "openusage-omarchy.snapshot.v1"


@dataclass
class Entry:
    snapshot: model.Snapshot
    session_id: str
    fetched_at: dt.datetime


def _parse_time(raw: str) -> dt.datetime | None:
    try:
        moment = dt.datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def snapshot_path(snapshots_dir: Path, card_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in ("-", "_", ":") else "_" for c in card_id)
    return snapshots_dir / f"{safe}.json"


def read(
    snapshots_dir: Path, card: model.CardRef, now: dt.datetime
) -> Entry | None:
    path = snapshot_path(snapshots_dir, card.card_id)
    with atomic.locked(path.with_name(path.name + ".lock"), exclusive=False):
        raw = atomic.read_json(path)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return None
    if raw.get("cardId") != card.card_id:
        return None
    try:
        snapshot = model.Snapshot.from_dict(raw.get("snapshot") or {})
    except (ValueError, TypeError, AttributeError):
        return None
    fetched = _parse_time(str(raw.get("fetchedAt", "")))
    if fetched is None:
        return None
    # Wrong-account guard: a card that changed identity must not show the
    # previous account's last-good data. Empty keys predate identity and pass.
    want = card.account_key or ""
    have = snapshot.card.account_key or ""
    if want and have and want != have:
        return None
    return Entry(
        snapshot=snapshot,
        session_id=str(raw.get("sessionId", "")),
        fetched_at=fetched,
    )


def write(
    snapshots_dir: Path,
    snapshot: model.Snapshot,
    session_id: str,
    now: dt.datetime,
) -> None:
    path = snapshot_path(snapshots_dir, snapshot.card.card_id)
    with atomic.locked(path.with_name(path.name + ".lock")):
        atomic.write_json_atomic(
            path,
            {
                "schema": SCHEMA,
                "cardId": snapshot.card.card_id,
                "sessionId": session_id,
                "fetchedAt": now.isoformat(),
                "snapshot": snapshot.to_dict(),
            },
        )
    log.get_logger("cache").debug("stored %s", snapshot.card.card_id)


def is_fresh(entry: Entry, session_id: str, now: dt.datetime) -> bool:
    if entry.session_id != session_id:
        return False
    return (now - entry.fetched_at).total_seconds() < REFRESH_INTERVAL_S
