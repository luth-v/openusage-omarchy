"""Codex local spend. Rollout logs plus priority-tier pricing."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any

from ... import parse as _parse
from ...spend import codex_pricing as _pricing
from ...spend import jsonl as _jsonl
from ...spend.aggregate import Accumulator, LogUsageScan, day_key
from ...spend.pricing import ModelPricing
from ...spend.rates import ModelRates, TokenBreakdown
from ...spend.scan_cache import Store

SCHEMA = 4
RESERVE_MODEL = "gpt-5.6-luna"
AUTO_FALLBACKS = [
    ("2026-07-09", "gpt-5.6-luna"), ("2026-04-23", "gpt-5.5"),
    ("2026-03-05", "gpt-5.4"), ("2026-02-05", "gpt-5.3-codex"),
    ("2025-12-11", "gpt-5.2-codex"), ("2025-11-13", "gpt-5.1-codex"),
    ("2025-09-15", "gpt-5-codex"), ("2025-08-07", "gpt-5"),
]


def codex_homes(home: Path) -> list[Path]:
    raw = (os.environ.get("CODEX_HOME") or "").strip()
    if raw:
        return [Path(part.strip()).expanduser() for part in raw.split(",") if part.strip()]
    return [home / ".codex"]


def session_files(homes: list[Path]) -> list[_jsonl.DiscoveredFile]:
    out: list[_jsonl.DiscoveredFile] = []
    seen_dirs: set[str] = set()
    for home in homes:
        sources = []
        for name in ("sessions", "archived_sessions"):
            target = home / name
            if target.is_dir():
                sources.append(target)
        if not sources:
            sources = [home]
        seen_rel: set[str] = set()
        for source in sources:
            try:
                resolved = source.resolve()
            except OSError:
                continue
            if str(resolved) in seen_dirs:
                continue
            seen_dirs.add(str(resolved))
            for found in _jsonl.jsonl_files(resolved):
                rel = found.path[len(str(resolved)):]
                if rel in seen_rel:
                    continue
                seen_rel.add(rel)
                out.append(found)
    return out


def auto_fallback(stamp: str) -> str:
    day = stamp[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        return "gpt-5"
    for released, name in AUTO_FALLBACKS:
        if day >= released:
            return name
    return "gpt-5"


def _raw_usage(payload: dict) -> dict[str, int]:
    def _int(*names: str) -> int:
        for name in names:
            moment = _parse.number(payload.get(name))
            if moment is not None:
                return int(moment)
        return 0

    inp = _int("input_tokens", "prompt_tokens", "input")
    cached = _int("cached_input_tokens", "cache_read_input_tokens", "cached_tokens")
    output = _int("output_tokens", "completion_tokens", "output")
    reasoning = _int("reasoning_output_tokens", "reasoning_tokens")
    reported = _int("total_tokens")
    recomputed = inp + output + reasoning
    total = reported if (reported > 0 or recomputed == 0) else recomputed
    return {"input": inp, "cached": cached, "output": output,
            "reasoning": reasoning, "total": total}


def _non_null(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def is_child_meta(payload: dict) -> bool:
    if _non_null(payload.get("forked_from_id")):
        return True
    if _non_null(payload.get("parent_thread_id")):
        return True
    if payload.get("thread_source") == "subagent":
        return True
    source = payload.get("source")
    return isinstance(source, dict) and _non_null(source.get("subagent"))


def _model_name(payload: dict) -> str | None:
    meta = payload.get("metadata")
    for value in (payload.get("model"), payload.get("model_name"),
                  meta.get("model") if isinstance(meta, dict) else None):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _tier(payload: dict | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    settings = payload.get("thread_settings")
    for value in ((settings.get("service_tier") if isinstance(settings, dict) else None),
                  payload.get("service_tier")):
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


class FileParser:
    """Per-file rollout state: model, tier, totals, replay gate."""

    def __init__(self) -> None:
        self.previous: dict[str, int] | None = None
        self.model: str | None = None
        self.fast = False
        self.saw_meta = False
        self.gate: tuple[str, float] | None = None

    def parse(self, records: list[bytes]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for raw in records:
            if b'"type":"turn_context"' not in raw and b'"type":"session_meta"' not in raw \
                    and b'"type":"task_started"' not in raw and b'"type":"token_count"' not in raw \
                    and b'thread_settings_applied' not in raw:
                continue
            try:
                found = json.loads(raw.decode("utf-8"))
            except (ValueError, UnicodeError):
                continue
            if not isinstance(found, dict):
                continue
            kind = found.get("type")
            payload = found.get("payload")
            if kind == "turn_context":
                if isinstance(payload, dict):
                    name = _model_name(payload)
                    if name:
                        self.model = name
                continue
            if kind == "session_meta" and not self.saw_meta:
                self.saw_meta = True
                if isinstance(payload, dict) and is_child_meta(payload):
                    stamp = found.get("timestamp")
                    moment = _parse.parse_time(stamp) if isinstance(stamp, str) else None
                    if moment is not None:
                        import math
                        self.gate = ("at", math.floor(moment.timestamp()))
                    else:
                        self.gate = ("self", 0)
                continue
            if isinstance(payload, dict) and payload.get("type") == "thread_settings_applied":
                tier = _tier(payload)
                if tier is not None:
                    self.fast = tier in ("fast", "priority")
                continue
            if kind != "event_msg" or not isinstance(payload, dict):
                continue
            if payload.get("type") == "task_started":
                started = _parse.number(payload.get("started_at"))
                if self.gate is not None and started is not None:
                    mode, bound = self.gate
                    if mode == "at" and started >= bound:
                        self.gate = None
                    elif mode == "self":
                        stamp = found.get("timestamp")
                        moment = _parse.parse_time(stamp) if isinstance(stamp, str) else None
                        if moment is not None:
                            import math
                            if started >= math.floor(moment.timestamp()):
                                self.gate = None
                continue
            if payload.get("type") != "token_count":
                continue
            stamp = found.get("timestamp")
            moment = _parse.parse_time(stamp) if isinstance(stamp, str) else None
            if moment is None:
                continue
            info = payload.get("info")
            info = info if isinstance(info, dict) else {}
            totals_raw = info.get("total_token_usage")
            totals = _raw_usage(totals_raw) if isinstance(totals_raw, dict) else None
            if self.gate is not None:
                if totals is not None:
                    self.previous = totals
                continue
            if totals is not None and self.previous is not None and totals == self.previous:
                continue
            last_raw = info.get("last_token_usage")
            if isinstance(last_raw, dict):
                usage = _raw_usage(last_raw)
            elif totals is not None:
                prev = self.previous or {"input": 0, "cached": 0, "output": 0,
                                        "reasoning": 0, "total": 0}
                usage = {key: max(0, totals[key] - prev[key]) for key in totals}
            else:
                continue
            if totals is not None:
                self.previous = totals
            if not any(usage[key] > 0 for key in ("input", "cached", "output", "reasoning")):
                continue
            parsed = _model_name(payload) or (info and _model_name(info))
            if parsed:
                self.model = parsed
            name = parsed or self.model or "gpt-5"
            if self.model is None:
                self.model = name
            pricing_model = None
            if name == "codex-auto-review" and isinstance(stamp, str):
                pricing_model = auto_fallback(stamp)
            elif name == "gpt-reserve":
                pricing_model = RESERVE_MODEL
            events.append({
                "ts": moment.timestamp(),
                "model": name, "pricing": pricing_model,
                "input": usage["input"], "cached": min(usage["cached"], usage["input"]),
                "output": usage["output"], "reasoning": usage["reasoning"],
                "total": usage["total"], "fast": self.fast,
            })
        return events


def parse_records(records: list[bytes]) -> list[dict[str, Any]]:
    return FileParser().parse(records)


def aggregate(events: list[dict[str, Any]], since_ts: float,
              pricing: ModelPricing, fallback: str | None = None) -> LogUsageScan:
    rates_fallback: ModelRates | None = None
    if fallback:
        rates_fallback = pricing.fallback_rates(fallback, "codex")
    seen: set[tuple] = set()
    acc = Accumulator()
    for event in events:
        if float(event.get("ts", 0)) < since_ts:
            continue
        key = (event.get("ts"), event.get("model"), event.get("pricing"),
               event.get("input"), event.get("cached"), event.get("output"),
               event.get("reasoning"), event.get("total"))
        if key in seen:
            continue
        seen.add(key)
        raw = event.get("model")
        name = raw.strip() if isinstance(raw, str) else ""
        if not name:
            continue
        moment = dt.datetime.fromtimestamp(float(event["ts"]), dt.timezone.utc)
        day = day_key(moment)
        pricing_model = event.get("pricing") or name
        rates, base, fast_alias, has_base = _pricing.resolve_rates(pricing, str(pricing_model))
        fast_tier = has_base if fast_alias else bool(event.get("fast"))
        used_fallback = None
        if rates is None and int(event.get("total", 0)) > 0:
            acc.add_unknown(day, name)
        if rates is None and fallback and rates_fallback is not None:
            rates, base = rates_fallback, fallback
            fast_tier = fast_alias or bool(event.get("fast"))
            used_fallback = fallback
        if rates is None:
            continue
        tokens = TokenBreakdown(
            input=max(0, int(event.get("input", 0)) - int(event.get("cached", 0))),
            cache_read=int(event.get("cached", 0)),
            output=int(event.get("output", 0)))
        cost = _pricing.cost_rates(rates, tokens, base, fast_tier)
        acc.add(day, int(event.get("total", 0)), cost, name, used_fallback)
    return acc.build()


def scan(home: Path, cache_base: Path, since_ts: float, pricing: ModelPricing,
         fallback: str | None = None) -> LogUsageScan | None:
    homes = codex_homes(home)
    identity = "\n".join(sorted(str(item) for item in homes)) or "no-codex-home"
    store = Store(cache_base, "codex", SCHEMA)
    files = session_files(homes)
    if not files:
        store.scan([], since_ts, identity, parse_records)
        return None
    # Stateful parse per file: reuse the generic record cache with a
    # fresh parser per file by keying parse through FileParser.
    from ...spend import jsonl as _jsonl_mod
    items: list[dict[str, Any]] = []
    live: set[str] = set()
    for found in files:
        if found.mtime < since_ts:
            continue
        live.add(found.path)
        cached = store.load_record(identity, found.path, found.size, found.mtime)
        if cached is not None:
            items.extend(cached)
            continue
        records, _ = _jsonl_mod.read_records(found.path)
        if records is None:
            continue
        parsed = FileParser().parse(records)
        store.save_record(identity, found.path, found.size, found.mtime, parsed)
        items.extend(parsed)
    store.prune(identity, live)
    return aggregate(items, since_ts, pricing, fallback)
