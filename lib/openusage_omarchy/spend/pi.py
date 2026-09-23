"""Pi usage attribution. Pi drives other providers, so its cost folds back."""

from __future__ import annotations

import datetime as dt
import json
import os
from pathlib import Path
from typing import Any, Callable

from .. import parse as _parse
from . import jsonl as _jsonl
from .aggregate import Accumulator, LogUsageScan
from .pricing import ModelPricing
from .rates import TokenBreakdown
from .scan_cache import Store

PROVIDER_TO_CARD = {
    "anthropic": "claude",
    "claude-agent-sdk": "claude",
    "openai-codex": "codex",
    "cursor": "cursor",
    "zai": "zai",
    "zhipu": "zai",
    "google-antigravity": "antigravity",
    "github-copilot": "copilot",
}


def sessions_dir(home: Path) -> Path:
    override = (os.environ.get("PI_CODING_AGENT_SESSION_DIR") or "").strip()
    if override:
        return Path(override).expanduser()
    config = (os.environ.get("PI_CODING_AGENT_DIR") or "").strip()
    if config:
        return Path(config).expanduser() / "sessions"
    return home / ".pi" / "agent" / "sessions"


def card_for(provider: str) -> str | None:
    return PROVIDER_TO_CARD.get(provider)


def parse_line(raw: bytes) -> dict[str, Any] | None:
    try:
        found = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        return None
    if not isinstance(found, dict) or found.get("type") != "message":
        return None
    moment = _parse.parse_time(found.get("timestamp"))
    if moment is None:
        return None
    message = found.get("message")
    if not isinstance(message, dict) or message.get("role") != "assistant":
        return None
    provider = message.get("provider")
    card = card_for(str(provider or ""))
    if card is None:
        return None
    usage = message.get("usage")
    if not isinstance(usage, dict):
        return None
    cache_write = int(_parse.number(usage.get("cacheWrite")) or 0)
    cache_1h = int(_parse.number(usage.get("cacheWrite1h")) or 0)
    tokens = TokenBreakdown(
        input=int(_parse.number(usage.get("input")) or 0),
        cache_write_5m=max(cache_write - cache_1h, 0),
        cache_write_1h=cache_1h,
        cache_read=int(_parse.number(usage.get("cacheRead")) or 0),
        output=int(_parse.number(usage.get("output")) or 0),
    )
    cost_block = usage.get("cost")
    carried = _parse.number(cost_block.get("total")) if isinstance(cost_block, dict) else None
    model_name = str(message.get("model") or "").strip()
    ident = found.get("id")
    return {
        "id": str(ident) if isinstance(ident, str) and ident else None,
        "ts": moment.timestamp(),
        "card": card,
        "model": model_name,
        "carried": carried,
        "input": tokens.input,
        "cache5m": tokens.cache_write_5m,
        "cache1h": tokens.cache_write_1h,
        "read": tokens.cache_read,
        "output": tokens.output,
        "total": int(_parse.number(usage.get("totalTokens")) or 0),
    }


def parse_records(records: list[bytes]) -> list[dict[str, Any]]:
    out = []
    for raw in records:
        if b'"usage":{' not in raw:
            continue
        entry = parse_line(raw)
        if entry is not None:
            out.append(entry)
    return out


def dedup(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out = []
    for entry in entries:
        ident = entry.get("id")
        if isinstance(ident, str) and ident:
            if ident in seen:
                continue
            seen.add(ident)
        out.append(entry)
    return out


def aggregate(entries: list[dict[str, Any]], card_id: str, since_ts: float,
              pricing: ModelPricing,
              estimate: Callable[[str, TokenBreakdown], float | None] | None = None
              ) -> LogUsageScan:
    calc = estimate or (lambda name, tokens: pricing.estimated_cost(name, tokens))
    acc = Accumulator()
    for entry in entries:
        if entry.get("card") != card_id or float(entry.get("ts", 0)) < since_ts:
            continue
        moment = dt.datetime.fromtimestamp(float(entry["ts"]), dt.timezone.utc)
        from .aggregate import day_key as _day
        day = _day(moment)
        name = str(entry.get("model") or "").strip()
        display = name or "Unattributed"
        tokens = TokenBreakdown(
            input=int(entry.get("input", 0)), cache_write_5m=int(entry.get("cache5m", 0)),
            cache_write_1h=int(entry.get("cache1h", 0)),
            cache_read=int(entry.get("read", 0)), output=int(entry.get("output", 0)))
        carried = entry.get("carried")
        cost: float | None = None
        if isinstance(carried, (int, float)) and carried > 0:
            cost = float(carried)
        elif name:
            cost = calc(name, tokens)
        if cost is None:
            if name and int(entry.get("total", 0)) > 0:
                acc.add_unknown(day, name)
            continue
        acc.add(day, int(entry.get("total", 0)), cost, display)
    return acc.build()


def scan(home: Path, cache_base: Path, card_id: str, since_ts: float,
         pricing: ModelPricing,
         estimate: Callable[[str, TokenBreakdown], float | None] | None = None
         ) -> LogUsageScan | None:
    directory = sessions_dir(home)
    try:
        identity = str(directory.resolve())
    except OSError:
        identity = str(directory)
    files = _jsonl.jsonl_files(directory)
    store = Store(cache_base, "pi", 1)
    if not files:
        store.scan([], since_ts, identity, parse_records)
        return None
    entries = store.scan(files, since_ts, identity, parse_records)
    if entries is None:
        return None
    return aggregate(dedup(entries), card_id, since_ts, pricing, estimate)
