"""Antigravity local spend. Conversation databases, token accounting."""

from __future__ import annotations

import datetime as dt
import sqlite3
from pathlib import Path

from .. import log
from . import antigravity_proto as _proto
from .aggregate import Accumulator, LogUsageScan, day_key
from .pricing import ModelPricing
from .rates import TokenBreakdown

MAX_BLOB = 1024 * 1024
BATCH = 8
UNKNOWN = "Unknown Antigravity Model"


def gemini_home(home: Path) -> Path:
    return home / ".gemini"


def conversations_dirs(home: Path) -> list[Path]:
    base = gemini_home(home)
    try:
        names = sorted(entry.name for entry in base.iterdir())
    except FileNotFoundError:
        return []
    except OSError as exc:
        raise exc
    return [base / name / "conversations" for name in names if name.startswith("antigravity")]


def database_files(directories: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for directory in directories:
        try:
            names = sorted(entry.name for entry in directory.iterdir())
        except FileNotFoundError:
            continue
        except OSError:
            continue
        for name in names:
            if not name.endswith(".db"):
                continue
            path = directory / name
            try:
                key = str(path.resolve())
            except OSError:
                key = str(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(path)
    return out


def _connect(path: Path) -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.execute("PRAGMA query_only = ON")
        return conn
    except sqlite3.Error:
        return None


def _has_step_meta(conn: sqlite3.Connection) -> bool:
    try:
        found = conn.execute(
            "SELECT 1 FROM pragma_table_info('steps') WHERE name = 'metadata'").fetchone()
        return found is not None
    except sqlite3.Error:
        return False


def _read_events(conn: sqlite3.Connection, since_ts: float,
                 include_steps: bool) -> tuple[list[_proto.GenerationEvent], bool]:
    events: list[_proto.GenerationEvent] = []
    oversized = False
    last = -1
    while True:
        try:
            rows = conn.execute(
                "SELECT idx, data FROM gen_metadata "
                "WHERE idx > ? AND data IS NOT NULL ORDER BY idx LIMIT ?",
                (last, BATCH)).fetchall()
        except sqlite3.Error:
            break
        if not rows:
            break
        for idx, data in rows:
            if idx <= last:
                raise ValueError("Antigravity indices not increasing")
            last = idx
            if not isinstance(data, (bytes, bytearray)) or len(data) > MAX_BLOB:
                oversized = True
                continue
            step: bytes | None = None
            if include_steps:
                try:
                    found = conn.execute(
                        "SELECT metadata FROM steps WHERE idx = ?", (idx,)).fetchone()
                except sqlite3.Error:
                    found = None
                if found and isinstance(found[0], (bytes, bytearray)) and len(found[0]) <= MAX_BLOB:
                    step = bytes(found[0])
                elif found and found[0] is not None:
                    oversized = True
            event = _proto.generation_event(bytes(data), step)
            if event is None or event.timestamp_s < since_ts:
                continue
            events.append(event)
        if len(rows) < BATCH:
            break
    return events, oversized


def model_candidates(model_id: str | None, label: str | None) -> list[str]:
    clean = model_id[:-7] if model_id and model_id.endswith("-tiered") else model_id
    placeholder = clean.endswith("-default") if clean else False
    ordered = [label, clean] if placeholder else [clean, label]
    return [item for item in ordered if item]


def scan(home: Path, since_ts: float, pricing: ModelPricing) -> LogUsageScan | None:
    try:
        directories = conversations_dirs(home)
    except OSError as exc:
        log.get_logger("plugin.antigravity").warning("usage query failed: %s", exc)
        return None
    paths = database_files(directories)
    # Filter by mtime so old stores stay cheap.
    live = []
    for path in paths:
        try:
            stamp = path.stat().st_mtime
            wal = path.with_name(path.name + "-wal")
            if wal.exists():
                stamp = max(stamp, wal.stat().st_mtime)
        except OSError:
            continue
        if stamp >= since_ts:
            live.append(path)
    acc = Accumulator()
    for path in live:
        conn = _connect(path)
        if conn is None:
            log.get_logger("plugin.antigravity").warning(
                "usage query failed for %s", path)
            continue
        try:
            include = _has_step_meta(conn)
            try:
                events, oversized = _read_events(conn, since_ts, include)
            except ValueError as exc:
                log.get_logger("plugin.antigravity").warning(
                    "usage query failed for %s: %s", path, exc)
                continue
            if oversized:
                log.get_logger("plugin.antigravity").warning(
                    "skipped oversized generation records in %s", path)
            for event in events:
                moment = dt.datetime.fromtimestamp(event.timestamp_s, dt.timezone.utc)
                if moment.timestamp() < since_ts:
                    continue
                total = event.input_tokens + event.cache_read + event.output_tokens
                if total <= 0:
                    continue
                tokens = TokenBreakdown(
                    input=event.input_tokens, cache_read=event.cache_read,
                    output=event.output_tokens)
                names = model_candidates(event.model_id, event.label)
                priced = False
                for name in names:
                    cost = pricing.estimated_cost(name, tokens)
                    if cost is not None:
                        family = pricing.family_name(name, ["-preview"])
                        acc.add(day_key(moment), total, cost, family)
                        priced = True
                        break
                if not priced:
                    acc.add_unknown(day_key(moment), names[0] if names else UNKNOWN)
        finally:
            conn.close()
    result = acc.build()
    if not result.series.daily and not result.unknown_by_day:
        return None
    return result
