"""Last-good snapshot cache. Stale-while-revalidate lives here.

One file per card under snapshots/, guarded by a per-card flock. A cache entry
counts as fresh only when fetched during this login session and younger than
the refresh interval. Holds no tokens: snapshots, identity hashes, offsets.

A rate-limited card also gets a backoff file next to its snapshot, so a
restarted daemon keeps honouring the wait instead of asking again at once.
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


@dataclass
class Backoff:
    until: dt.datetime
    strikes: int
    message: str


def _backoff_path(snapshots_dir: Path, card_id: str) -> Path:
    path = snapshot_path(snapshots_dir, card_id)
    return path.with_name(path.stem + ".backoff.json")


def read_backoff(snapshots_dir: Path, card_id: str) -> Backoff | None:
    raw = atomic.read_json(_backoff_path(snapshots_dir, card_id))
    if not isinstance(raw, dict):
        return None
    until = _parse_time(str(raw.get("until", "")))
    if until is None:
        return None
    try:
        strikes = max(1, int(raw.get("strikes", 1)))
    except (TypeError, ValueError):
        strikes = 1
    return Backoff(until=until, strikes=strikes,
                   message=str(raw.get("message", "")))


def write_backoff(snapshots_dir: Path, card_id: str, backoff: Backoff) -> None:
    atomic.write_json_atomic(_backoff_path(snapshots_dir, card_id), {
        "until": backoff.until.isoformat(),
        "strikes": backoff.strikes,
        "message": backoff.message,
    })


def clear_backoff(snapshots_dir: Path, card_id: str) -> None:
    _backoff_path(snapshots_dir, card_id).unlink(missing_ok=True)
