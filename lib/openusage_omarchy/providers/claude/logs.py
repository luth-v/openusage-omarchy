"""Claude local spend. Scans Claude Code session logs, as ccusage."""

from __future__ import annotations

import datetime as dt
import json
import os
import re
from pathlib import Path
from typing import Any

from ... import log, parse as _parse
from ...spend import jsonl as _jsonl
from ...spend.aggregate import Accumulator, LogUsageScan, day_key
from ...spend.pricing import ModelPricing
from ...spend.rates import TokenBreakdown
from ...spend.scan_cache import Store

SCHEMA = 2


def _expand(value: str, home: Path) -> Path:
    text = value.strip()
    if text.startswith("~"):
        return home / text[1:].lstrip("/")
    return Path(text).expanduser()


def config_roots(home: Path) -> list[Path]:
    raw = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    found: list[Path] = []
    seen: set[str] = set()
    def _add(url: Path) -> None:
        if not (url / "projects").is_dir():
            return
        key = str(url)
        if key in seen:
            return
        seen.add(key)
        found.append(url)
    if raw:
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            url = _expand(part, home)
            if url.name == "projects" and url.is_dir():
                url = url.parent
            _add(url)
        if not found:
            log.get_logger("plugin.claude").warning(
                "CLAUDE_CONFIG_DIR has no Claude data dir with projects/")
    else:
        xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
        base = _expand(xdg, home) if xdg else home / ".config"
        _add(base / "claude")
        _add(home / ".claude")
    return found


def usage_files(roots: list[Path]) -> list[_jsonl.DiscoveredFile]:
    out: list[_jsonl.DiscoveredFile] = []
    for root in roots:
        out.extend(_jsonl.jsonl_files(root / "projects"))
    out.sort(key=lambda item: item.path)
    return out


def _is_semver(value: str) -> bool:
    parts = value.split(".")
    if len(parts) < 3:
        return False
    try:
        int(parts[0])
        int(parts[1])
        int(re.match(r"\d+", parts[2]).group(0) if re.match(r"\d+", parts[2]) else "x")
        return True
    except (ValueError, AttributeError):
        return False


def _has_null(found: dict, message: dict, usage: dict) -> bool:
    for container, names in (
            (found, ("cwd", "costUSD", "version", "sessionId", "requestId", "isApiErrorMessage")),
            (message, ("id", "model")),
            (usage, ("speed", "cache_read_input_tokens", "cache_creation_input_tokens"))):
        for name in names:
            if container.get(name) is None and name in container:
                # JSON null decodes to None; missing keys are fine.
                return True
    return False


def _tokens(usage: dict) -> tuple[TokenBreakdown, bool] | None:
    inp = _parse.number(usage.get("input_tokens"))
    out = _parse.number(usage.get("output_tokens"))
    if inp is None or out is None:
        return None
    speed = usage.get("speed")
    if speed is not None and speed not in ("fast", "standard"):
        return None
    write_5m = write_1h = 0
    creation = usage.get("cache_creation")
    if isinstance(creation, dict):
        write_5m = int(_parse.number(creation.get("ephemeral_5m_input_tokens")) or 0)
        write_1h = int(_parse.number(creation.get("ephemeral_1h_input_tokens")) or 0)
    else:
        write_5m = int(_parse.number(usage.get("cache_creation_input_tokens")) or 0)
    return TokenBreakdown(
        input=int(inp), cache_write_5m=write_5m, cache_write_1h=write_1h,
        cache_read=int(_parse.number(usage.get("cache_read_input_tokens")) or 0),
        output=int(out), is_fast=speed == "fast"), speed is not None


def _valid(found: dict, message: dict) -> bool:
    version = found.get("version")
    if isinstance(version, str) and not _is_semver(version):
        return False
    for value in (found.get("sessionId"), found.get("requestId"),
                  message.get("id"), message.get("model")):
        if isinstance(value, str) and not value:
            return False
    return True


def parse_entries(raw: bytes) -> list[dict[str, Any]]:
    try:
        found = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        return []
    if not isinstance(found, dict):
        return []
    moment = _parse.parse_time(found.get("timestamp"))
    message = found.get("message")
    if moment is None or not isinstance(message, dict):
        return []
    usage = message.get("usage")
    if not isinstance(usage, dict) or _has_null(found, message, usage):
        return []
    parsed = _tokens(usage)
    if parsed is None or not _valid(found, message):
        return []
    tokens, has_speed = parsed
    model_name = message.get("model")
    if model_name == "<synthetic>":
        model_name = None
    parent = {
        "ts": moment.timestamp(),
        "input": tokens.input, "write5m": tokens.cache_write_5m,
        "write1h": tokens.cache_write_1h, "read": tokens.cache_read,
        "output": tokens.output, "fast": tokens.is_fast,
        "message": message.get("id") if isinstance(message.get("id"), str) else None,
        "request": found.get("requestId") if isinstance(found.get("requestId"), str) else None,
        "sidechain": found.get("isSidechain") is True,
        "hasSpeed": has_speed,
        "cost": _parse.number(found.get("costUSD")),
        "model": model_name if isinstance(model_name, str) else None,
    }
    out = [parent]
    iterations = usage.get("iterations")
    if not isinstance(iterations, list):
        return out
    advisor = 0
    for item in iterations:
        if not isinstance(item, dict) or item.get("type") != "advisor_message":
            continue
        name = item.get("model")
        if not isinstance(name, str) or not name:
            continue
        advisor_tokens = _tokens(item)
        if advisor_tokens is None:
            continue
        tokens, has_speed = advisor_tokens
        base = parent["message"]
        out.append({
            "ts": parent["ts"],
            "input": tokens.input, "write5m": tokens.cache_write_5m,
            "write1h": tokens.cache_write_1h, "read": tokens.cache_read,
            "output": tokens.output, "fast": tokens.is_fast,
            "message": f"{base}:advisor:{advisor}" if base else None,
            "request": parent["request"], "sidechain": parent["sidechain"],
            "hasSpeed": has_speed, "cost": None, "model": name,
        })
        advisor += 1
    return out


def parse_records(records: list[bytes]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for raw in records:
        if b'"usage":{' not in raw:
            continue
        out.extend(parse_entries(raw))
    return out


def _total(entry: dict[str, Any]) -> int:
    return int(entry.get("input", 0)) + int(entry.get("write5m", 0)) + int(
        entry.get("write1h", 0)) + int(entry.get("read", 0)) + int(entry.get("output", 0))


def _replace(candidate: dict[str, Any], existing: dict[str, Any]) -> bool:
    if bool(candidate.get("sidechain")) != bool(existing.get("sidechain")):
        return bool(existing.get("sidechain"))
    mine, theirs = _total(candidate), _total(existing)
    if mine != theirs:
        return mine > theirs
    return bool(candidate.get("hasSpeed")) and not bool(existing.get("hasSpeed"))


def dedup(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    kept: list[dict[str, Any]] = []
    exact: dict[tuple, int] = {}
    by_message: dict[str, list[int]] = {}
    for entry in entries:
        ident = entry.get("message")
        if not isinstance(ident, str):
            kept.append(entry)
            continue
        key = (ident, entry.get("request"))
        hit = exact.get(key)
        if hit is None:
            for index in by_message.get(ident, []):
                if bool(entry.get("sidechain")) or bool(kept[index].get("sidechain")):
                    hit = index
                    break
        if hit is not None:
            if _replace(entry, kept[hit]):
                old = kept[hit]
                old_id = old.get("message")
                if isinstance(old_id, str):
                    exact.pop((old_id, old.get("request")), None)
                kept[hit] = entry
                exact[key] = hit
            continue
        index = len(kept)
        kept.append(entry)
        exact[key] = index
        by_message.setdefault(ident, []).append(index)
    return kept


def aggregate(entries: list[dict[str, Any]], since_ts: float,
              pricing: ModelPricing) -> LogUsageScan:
    acc = Accumulator()
    for entry in entries:
        if float(entry.get("ts", 0)) < since_ts:
            continue
        moment = dt.datetime.fromtimestamp(float(entry["ts"]), dt.timezone.utc)
        day = day_key(moment)
        raw_model = entry.get("model")
        name = raw_model.strip() if isinstance(raw_model, str) else ""
        display = name or "Unattributed"
        tokens = TokenBreakdown(
            input=int(entry.get("input", 0)), cache_write_5m=int(entry.get("write5m", 0)),
            cache_write_1h=int(entry.get("write1h", 0)),
            cache_read=int(entry.get("read", 0)), output=int(entry.get("output", 0)),
            is_fast=bool(entry.get("fast")))
        carried = entry.get("cost")
        cost: float | None = None
        if isinstance(carried, (int, float)):
            cost = float(carried)
        elif name:
            cost = pricing.estimated_cost(name, tokens)
        if cost is None:
            if name and _total(entry) > 0:
                acc.add_unknown(day, name)
            continue
        acc.add(day, tokens.total_tokens, cost, display)
    return acc.build()


def scan(home: Path, cache_base: Path, since_ts: float,
         pricing: ModelPricing,
         roots: list[Path] | None = None) -> LogUsageScan | None:
    """One Account's Spend. ``roots`` defaults to ``config_roots``; the cache
    identity carries the roots, so per-Account scans never share a cache."""
    if roots is None:
        roots = config_roots(home)
    store = Store(cache_base, "claude", SCHEMA)
    identity = "home=" + str(home) + "\nroots=" + "\n".join(sorted(str(item) for item in roots))
    if not roots:
        store.scan([], since_ts, identity, parse_records)
        return None
    files = usage_files(roots)
    if not files:
        store.scan([], since_ts, identity, parse_records)
        return None
    entries = store.scan(files, since_ts, identity, parse_records)
    if entries is None:
        return None
    return aggregate(dedup(entries), since_ts, pricing)
