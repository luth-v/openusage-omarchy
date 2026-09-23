"""Grok local spend. Session updates.jsonl transcripts."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any

from .. import parse as _parse
from . import jsonl as _jsonl
from .aggregate import Accumulator, LogUsageScan, day_key
from .pricing import ModelPricing
from .rates import TokenBreakdown
from .scan_cache import Store

SCHEMA = 1
MAX_TOKENS = 10 ** 12


def sessions_dir(home: Path) -> Path:
    override = (os.environ.get("GROK_HOME") or "").strip()
    base = Path(override).expanduser() if override else home / ".grok"
    return base / "sessions"


def _bounded(value: Any) -> int:
    number = _parse.number(value)
    if number is None or number <= 0:
        return 0
    if number > MAX_TOKENS:
        return MAX_TOKENS
    return int(number)


def _moment(found: dict, params: dict | None) -> dt.datetime | None:
    for meta in (params.get("_meta") if isinstance(params, dict) else None,
                 found.get("_meta")):
        if isinstance(meta, dict):
            moment = _parse.number(meta.get("agentTimestampMs"))
            if moment is not None and moment > 0:
                return dt.datetime.fromtimestamp(moment / 1000, dt.timezone.utc)
    seconds = _parse.number(found.get("timestamp"))
    if seconds is not None and seconds > 0:
        return dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
    stamp = found.get("timestamp")
    return _parse.parse_time(stamp) if isinstance(stamp, str) else None


def _turn_entries(found: dict) -> list[dict[str, Any]]:
    params = found.get("params") if isinstance(found.get("params"), dict) else {}
    update = params.get("update") if isinstance(params, dict) else None
    if not isinstance(update, dict):
        update = found.get("update")
    if not isinstance(update, dict) or update.get("sessionUpdate") != "turn_completed":
        return []
    usage = update.get("usage")
    if not isinstance(usage, dict):
        return []
    per_model = usage.get("modelUsage")
    if not isinstance(per_model, dict):
        return []
    moment = _moment(found, params if isinstance(params, dict) else None)
    if moment is None:
        return []
    meta = (params.get("_meta") if isinstance(params, dict) else None) or found.get("_meta")
    event = meta.get("eventId") if isinstance(meta, dict) else None
    event_id = event.strip() if isinstance(event, str) and event.strip() else None
    top_ticks = _parse.number(usage.get("costUsdTicks"))
    out = []
    for raw_name in sorted(per_model):
        name = str(raw_name).strip()
        values = per_model[raw_name]
        if not name or not isinstance(values, dict):
            continue
        inp_raw = _parse.number(values.get("inputTokens"))
        if inp_raw is None or inp_raw < 0:
            continue
        inp = _bounded(values.get("inputTokens"))
        read = min(_bounded(values.get("cachedReadTokens")), inp)
        write = min(_bounded(values.get("cacheCreationTokens")), inp - read)
        output = _bounded(values.get("outputTokens"))
        ticks = _parse.number(values.get("costUsdTicks"))
        if ticks is None and len(per_model) == 1:
            ticks = top_ticks
        carried = ticks / 10_000_000_000 if ticks is not None and ticks >= 0 else None
        tokens = TokenBreakdown(input=inp - read - write, cache_write_5m=write,
                                cache_read=read, output=output)
        out.append({
            "event": event_id, "ts": moment.timestamp(), "model": name,
            "input": tokens.input, "write5m": tokens.cache_write_5m,
            "read": tokens.cache_read, "output": tokens.output,
            "carried": carried,
        })
    return out


def parse_records(records: list[bytes]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in records:
        if b"turn_completed" not in raw:
            continue
        try:
            found = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            continue
        if isinstance(found, dict):
            out.extend(_turn_entries(found))
    return out


def dedup(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for entry in entries:
        event = entry.get("event")
        if isinstance(event, str) and event:
            key = event + "\0" + str(entry.get("model"))
            if key in seen:
                continue
            seen.add(key)
        out.append(entry)
    return out


def aggregate(entries: list[dict[str, Any]], since_ts: float,
              pricing: ModelPricing) -> LogUsageScan:
    acc = Accumulator()
    for entry in entries:
        if float(entry.get("ts", 0)) < since_ts:
            continue
        moment = dt.datetime.fromtimestamp(float(entry["ts"]), dt.timezone.utc)
        day = day_key(moment)
        name = str(entry.get("model") or "")
        tokens = TokenBreakdown(
            input=int(entry.get("input", 0)), cache_write_5m=int(entry.get("write5m", 0)),
            cache_read=int(entry.get("read", 0)), output=int(entry.get("output", 0)))
        carried = entry.get("carried")
        cost = float(carried) if isinstance(carried, (int, float)) else None
        if cost is None:
            cost = pricing.estimated_cost(name, tokens)
        if cost is None:
            if tokens.total_tokens > 0:
                acc.add_unknown(day, name)
            continue
        acc.add(day, tokens.total_tokens, cost, name)
    return acc.build()


def scan(home: Path, cache_base: Path, since_ts: float,
         pricing: ModelPricing) -> LogUsageScan | None:
    directory = sessions_dir(home)
    try:
        identity = str(directory.resolve())
    except OSError:
        identity = str(directory)
    files = [item for item in _jsonl.jsonl_files(directory)
             if Path(item.path).name == "updates.jsonl"]
    store = Store(cache_base, "grok", SCHEMA)
    if not files:
        store.scan([], since_ts, identity, parse_records)
        return None
    entries = store.scan(files, since_ts, identity, parse_records)
    if entries is None:
        return None
    return aggregate(dedup(entries), since_ts, pricing)
