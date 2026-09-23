"""Refresh engine. Parallel fetch, 120 s per-provider deadline, SWR cache.

A failed refresh never wipes data: last-good snapshots stay, with the error
attached. Late threads (past the deadline) can never publish: results are
accepted only for the live batch generation.
"""

from __future__ import annotations

import concurrent.futures
import datetime as dt
import itertools
import threading
import time
from dataclasses import dataclass, field

from .. import PROVIDER_DEADLINE_S, catalog, log, model
from ..providers import Env
from . import cache

_counter = itertools.count(1)
_lock = threading.Lock()


@dataclass
class CardResult:
    card: model.CardRef
    snapshot: model.Snapshot | None
    error: model.ErrorInfo | None
    from_cache: bool
    fetched_at: dt.datetime


@dataclass
class Batch:
    generation: int
    results: list[CardResult] = field(default_factory=list)
    started_at: dt.datetime | None = None
    ended_at: dt.datetime | None = None


def _fetch_one(
    collector: object,
    card: model.CardRef,
    env: Env,
    session_id: str,
    live: threading.Event,
    expires_at: float,
) -> CardResult:
    now = env.clock.now()
    start = time.monotonic()
    try:
        snapshot = catalog.check_snapshot(collector.fetch(card, env))  # type: ignore[attr-defined]
    except model.CollectorError as exc:
        return _fallback(card, env, now, model.ErrorInfo(exc.category, exc.message))
    except Exception as exc:  # never let one card kill the batch
        log.get_logger("refresh").warning("%s fetch failed: %s", card.card_id, type(exc).__name__)
        return _fallback(card, env, now, model.ErrorInfo("internal", "Refresh failed"))
    elapsed_ms = (time.monotonic() - start) * 1000
    if elapsed_ms >= 10000:
        log.get_logger("refresh").warning(
            "%s took %.0fms (over the 10s threshold)", card.card_id, elapsed_ms)
    if not live.is_set() or time.monotonic() >= expires_at:
        return _fallback(card, env, now, model.ErrorInfo("timeout", "Refresh timed out after 120s"))
    try:
        cache.write(env.paths.snapshots_dir, snapshot, session_id, now)
    except OSError as exc:
        log.get_logger("cache").warning("cache write failed for %s: %s", card.card_id, exc)
    return CardResult(card=card, snapshot=snapshot, error=None, from_cache=False, fetched_at=now)


def _fallback(
    card: model.CardRef, env: Env, now: dt.datetime, error: model.ErrorInfo
) -> CardResult:
    entry = cache.read(env.paths.snapshots_dir, card, now)
    if entry is not None:
        return CardResult(
            card=card,
            snapshot=entry.snapshot,
            error=error,
            from_cache=True,
            fetched_at=entry.fetched_at,
        )
    return CardResult(card=card, snapshot=None, error=error, from_cache=False, fetched_at=now)


def merge_batches(old: Batch, new: Batch) -> Batch:
    """Fold a family-scoped batch into the previous full one, keeping the
    previous order and appending newly seen cards at the end."""
    fresh = {item.card.card_id: item for item in new.results}
    merged = [fresh.pop(item.card.card_id, item) for item in old.results]
    merged.extend(fresh.values())
    return Batch(generation=new.generation, results=merged,
                 started_at=old.started_at, ended_at=new.ended_at)


def refresh(
    collectors: list,
    env: Env,
    session_id: str,
    force: bool = False,
    families: set[str] | None = None,
    enabled_ids: set[str] | None = None,
    deadline: float = PROVIDER_DEADLINE_S,
) -> Batch:
    logger = log.get_logger("refresh")
    with _lock:
        generation = next(_counter)
    started = env.clock.now()
    logger.info("refresh start (force=%s)", force)
    wanted: list[tuple[object, model.CardRef]] = []
    enabled_families = ({model.family_of(cid) for cid in enabled_ids}
                        if enabled_ids is not None else None)
    for collector in collectors:
        if families is not None and collector.family not in families:  # type: ignore[attr-defined]
            continue
        if enabled_families is not None and collector.family not in enabled_families:
            continue
        try:
            cards = collector.cards(env)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.warning("%s cards failed: %s", collector.family, type(exc).__name__)  # type: ignore[attr-defined]
            continue
        for card in cards:
            if enabled_ids is None or card.card_id in enabled_ids:
                wanted.append((collector, card))
    batch = Batch(generation=generation, started_at=started)
    pending: list[tuple[object, model.CardRef]] = []
    for collector, card in wanted:
        if not force:
            entry = cache.read(env.paths.snapshots_dir, card, started)
            if entry is not None and cache.is_fresh(entry, session_id, started):
                batch.results.append(
                    CardResult(
                        card=card,
                        snapshot=entry.snapshot,
                        error=None,
                        from_cache=True,
                        fetched_at=entry.fetched_at,
                    )
                )
                continue
        pending.append((collector, card))
    if pending:
        live = threading.Event()
        live.set()
        pool = concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, len(pending)), thread_name_prefix="openusage-fetch"
        )
        expires_at = time.monotonic() + deadline
        yielded: set[concurrent.futures.Future] = set()
        try:
            futures = {
                pool.submit(_fetch_one, collector, card, env, session_id, live,
                            expires_at): (
                    collector,
                    card,
                )
                for collector, card in pending
            }
            try:
                for future in concurrent.futures.as_completed(
                        futures, timeout=max(0.0, expires_at - time.monotonic())):
                    yielded.add(future)
                    batch.results.append(future.result())
            except concurrent.futures.TimeoutError:
                pass
            missing = [info for fut, info in futures.items() if fut not in yielded]
            if missing:
                live.clear()
                for _collector, card in missing:
                    logger.warning("%s timed out after 120s", card.card_id)
                    batch.results.append(
                        _fallback(
                            card,
                            env,
                            env.clock.now(),
                            model.ErrorInfo("timeout", "Refresh timed out after 120s"),
                        )
                    )
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
    batch.ended_at = env.clock.now()
    ok = sum(1 for item in batch.results if item.error is None)
    logger.info("refresh end: %d/%d ok", ok, len(batch.results))
    return batch
