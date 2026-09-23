"""OpenCode local spend. Hosted SQLite rows with authoritative cost."""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from pathlib import Path
from typing import Any

from .. import parse as _parse
from .aggregate import Accumulator, LogUsageScan, day_key

HOSTED = ("opencode-go", "opencode")
MAX_TOKENS = 10 ** 15


def database_files(data_dir: Path) -> list[Path]:
    try:
        names = sorted(entry.name for entry in data_dir.iterdir())
    except OSError:
        return []
    if not data_dir.is_dir():
        return []
    return sorted(data_dir / name for name in names
                  if name.startswith("opencode") and name.endswith(".db"))


def _connect(path: Path) -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.execute("PRAGMA query_only = ON")
        return conn
    except sqlite3.Error:
        return None


def data_sql(cutoff_ms: int) -> str:
    filt = "(" + ",".join(f"'{item}'" for item in HOSTED) + ")"
    return (
        "SELECT json_group_array(json_array("
        " time_created, json_extract(data,'$.cost'),"
        " COALESCE(json_extract(data,'$.tokens.total'),0),"
        " json_extract(data,'$.modelID'), json_extract(data,'$.providerID')))"
        " FROM message"
        f" WHERE time_created >= {cutoff_ms}"
        " AND json_valid(data)"
        " AND json_extract(data,'$.role') = 'assistant'"
        f" AND json_extract(data,'$.providerID') IN {filt}"
        " AND json_type(data,'$.cost') IN ('integer','real');")


def parse_rows(payload: str) -> list[tuple[float, float, int, str]]:
    try:
        found = json.loads(payload)
    except ValueError:
        return []
    if not isinstance(found, list):
        return []
    out = []
    for entry in found:
        if not isinstance(entry, list) or len(entry) < 5:
            continue
        moment = _parse.number(entry[0])
        cost = _parse.number(entry[1])
        if moment is None or cost is None or cost < 0 or not isinstance(entry[4], str):
            continue
        tokens = int(min(max(_parse.number(entry[2]) or 0, 0), MAX_TOKENS))
        name = entry[3] if isinstance(entry[3], str) else ""
        out.append((moment, cost, tokens, name))
    return out


def scan(data_dir: Path, since_ts: float) -> LogUsageScan | None:
    paths = database_files(data_dir)
    if not paths:
        return None
    cutoff = int(since_ts * 1000)
    rows: list[tuple[float, float, int, str]] = []
    failures = 0
    for path in paths:
        conn = _connect(path)
        if conn is None:
            failures += 1
            continue
        try:
            try:
                found = conn.execute(data_sql(cutoff)).fetchone()
            except sqlite3.Error:
                failures += 1
                continue
            if found and found[0]:
                rows.extend(parse_rows(str(found[0])))
        finally:
            conn.close()
    if failures == len(paths):
        raise ValueError("database unreadable")
    acc = Accumulator()
    for moment_ms, cost, tokens, name in rows:
        moment = dt.datetime.fromtimestamp(moment_ms / 1000, dt.timezone.utc)
        if moment.timestamp() < since_ts:
            continue
        acc.add(day_key(moment), tokens, cost, name or "Unattributed")
    return acc.build()


def has_hosted_usage(data_dir: Path) -> bool:
    for path in database_files(data_dir):
        conn = _connect(path)
        if conn is None:
            continue
        try:
            filt = "(" + ",".join(f"'{item}'" for item in HOSTED) + ")"
            found = conn.execute(
                "SELECT 1 FROM message WHERE json_valid(data)"
                " AND json_extract(data,'$.role') = 'assistant'"
                f" AND json_extract(data,'$.providerID') IN {filt}"
                " AND json_type(data,'$.cost') IN ('integer','real') LIMIT 1;").fetchone()
            if found:
                return True
        except sqlite3.Error:
            continue
        finally:
            conn.close()
    return False
