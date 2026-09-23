"""OpenCode databases as a Codex spend source. OAuth rows only.

Reads the v1 message plus v2 session_message tables. A database counts
only while its own OpenCode credential for openai is OAuth. Zero-cost
rows with openai provider are Codex subscription traffic; a positive
recorded cost is API-key traffic and stays out.
"""

from __future__ import annotations

import datetime as dt
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import log, parse as _parse
from . import codex_pricing as _codex
from .aggregate import Accumulator, LogUsageScan, day_key
from .pricing import ModelPricing
from .rates import TokenBreakdown

MAX_TOKENS = 10 ** 15


@dataclass(frozen=True)
class Row:
    ident: str | None
    moment: dt.datetime
    model: str
    tokens: TokenBreakdown
    total: int


def database_files(data_dir: Path) -> list[Path]:
    try:
        names = sorted(entry.name for entry in data_dir.iterdir())
    except OSError:
        return []
    if not data_dir.is_dir():
        return []
    out = []
    for name in names:
        if name.startswith("opencode") and name.endswith(".db"):
            out.append(data_dir / name)
    return sorted(out)


def _connect(path: Path) -> sqlite3.Connection | None:
    try:
        conn = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)
        conn.execute("PRAGMA query_only = ON")
        return conn
    except sqlite3.Error:
        return None


def message_tables(conn: sqlite3.Connection) -> set[str]:
    try:
        row = conn.execute(
            "SELECT group_concat(name) FROM sqlite_master "
            "WHERE type='table' AND name IN ('message','session_message')").fetchone()
    except sqlite3.Error:
        return set()
    if not row or not row[0]:
        return set()
    return {item.strip() for item in str(row[0]).split(",") if item.strip()}


def _is_oauth(entry: Any) -> bool:
    if not isinstance(entry, dict) or entry.get("type") != "oauth":
        return False
    for name in ("access", "refresh"):
        text = entry.get(name)
        if isinstance(text, str) and text.strip():
            return True
    return False


def openai_credential(conn: sqlite3.Connection, auth_json: dict | None
                      ) -> tuple[bool, float | None]:
    """(isOAuth, sinceMs|None) for one database."""
    try:
        row = conn.execute(
            "SELECT json_array(json(value), time_created) FROM credential "
            "WHERE integration_id = 'openai' AND (active IS NULL OR active = 1) "
            "ORDER BY active DESC, time_updated DESC, id DESC LIMIT 1").fetchone()
    except sqlite3.Error as exc:
        if "no such table" not in str(exc).lower():
            raise
        entry = auth_json.get("openai") if isinstance(auth_json, dict) else None
        return (_is_oauth(entry), None)
    if not row or not row[0]:
        return False, None
    try:
        values = json.loads(row[0])
    except ValueError:
        raise ValueError("credential row is malformed")
    if not isinstance(values, list) or len(values) < 2:
        raise ValueError("credential row is malformed")
    entry = values[0]
    if isinstance(entry, str):
        try:
            entry = json.loads(entry)
        except ValueError:
            raise ValueError("credential row is malformed")
    if not isinstance(entry, dict):
        raise ValueError("credential row is malformed")
    since = None
    if values[1] is not None:
        moment = _parse.number(values[1])
        if moment is None or not 0 <= moment <= 1e15:
            raise ValueError("credential row is malformed")
        since = float(moment)
    return _is_oauth(entry), since


_DATA_PROJECTION = """
SELECT json_group_array(json_array(
         COALESCE(json_extract(data,'$.time.completed'),time_created),
         json_extract(data,'$.cost'),
         COALESCE(json_extract(data,'$.tokens.total'),0),
         COALESCE(json_extract(data,'$.model.id'), json_extract(data,'$.modelID')),
         COALESCE(json_extract(data,'$.tokens.input'),0),
         COALESCE(json_extract(data,'$.tokens.cache.read'),0),
         COALESCE(json_extract(data,'$.tokens.cache.write'),0),
         COALESCE(json_extract(data,'$.tokens.output'),0),
         COALESCE(json_extract(data,'$.tokens.reasoning'),0),
         id))
FROM
""".strip()

_COMPLETED = ("(json_type(data,'$.time.completed') IN ('integer','real') "
              "OR json_type(data,'$.finish') = 'text')")


def _rows_sql(table: str, role: str, cutoff: int, extra: str = "") -> str:
    return (
        f"  SELECT time_created, id, data FROM {table}"
        f"  WHERE time_created >= {cutoff}"
        "    AND json_valid(data)"
        "    AND COALESCE(json_extract(data,'$.model.providerID'),"
        " json_extract(data,'$.providerID')) = 'openai'"
        "    AND json_type(data,'$.cost') IN ('integer','real')"
        "    AND json_extract(data,'$.cost') = 0"
        f"    AND {role}{extra}")


def data_sql(cutoff_ms: int, tables: set[str], oauth_since_ms: float | None = None) -> str:
    creation = cutoff_ms - 7 * 86400000
    bodies = []
    if "message" in tables:
        bodies.append(_rows_sql("message", f"json_extract(data,'$.role') = 'assistant' AND {_COMPLETED}",
                                creation))
    if "session_message" in tables:
        extra = ""
        if oauth_since_ms is not None:
            extra = (f"\n            AND COALESCE(json_extract(data,'$.time.completed'),"
                     f"time_created) >= {int(oauth_since_ms)}")
        bodies.append(_rows_sql(
            "session_message",
            f"((type = 'assistant' AND {_COMPLETED}) OR "
            "(type = 'compaction' AND json_extract(data,'$.status') = 'completed'))",
            creation, extra))
    source = "(\n" + "\n          UNION ALL\n".join(bodies) + "\n        )"
    return (f"{_DATA_PROJECTION}\n{source}\nWHERE COALESCE("
            f"json_extract(data,'$.time.completed'),time_created) >= {cutoff_ms};")


def _clamped(value: Any) -> int:
    return int(min(max(_parse.number(value) or 0, 0), MAX_TOKENS))


def parse_rows(payload: str) -> list[Row]:
    try:
        found = json.loads(payload)
    except ValueError:
        return []
    if not isinstance(found, list):
        return []
    out: list[Row] = []
    for values in found:
        if not isinstance(values, list) or len(values) < 10:
            continue
        moment = _parse.number(values[0])
        if moment is None or _parse.number(values[1]) != 0:
            continue
        tokens = TokenBreakdown(
            input=_clamped(values[4]), cache_read=_clamped(values[5]),
            cache_write_5m=_clamped(values[6]),
            output=_clamped(values[7]) + _clamped(values[8]))
        total = tokens.total_tokens or _clamped(values[2])
        ident = values[9] if isinstance(values[9], str) and values[9].strip() else None
        name = values[3] if isinstance(values[3], str) else ""
        out.append(Row(
            ident=ident.strip() if ident else None,
            moment=dt.datetime.fromtimestamp(moment / 1000, dt.timezone.utc),
            model=name.strip(), tokens=tokens, total=total))
    return out


def deduplicated(rows: list[Row]) -> list[Row]:
    plain: list[Row] = []
    by_id: dict[str, Row] = {}
    for row in rows:
        if row.ident is None:
            plain.append(row)
            continue
        prior = by_id.get(row.ident)
        if prior is None or row.moment > prior.moment or (
                row.moment == prior.moment and row.total > prior.total):
            by_id[row.ident] = row
    return plain + list(by_id.values())


def scan(data_dir: Path, auth_json: dict | None, since_ts: float,
         pricing: ModelPricing) -> LogUsageScan | None:
    paths = database_files(data_dir)
    if not paths:
        return None
    cutoff = int(since_ts * 1000)
    rows: list[Row] = []
    any_oauth = False
    read_any = False
    failures = 0
    for path in paths:
        conn = _connect(path)
        if conn is None:
            failures += 1
            continue
        try:
            try:
                oauth, oauth_since = openai_credential(conn, auth_json)
            except (ValueError, sqlite3.Error) as exc:
                log.get_logger("plugin.opencode").warning(
                    "Codex usage credential check failed for %s: %s", path, exc)
                failures += 1
                continue
            if not oauth:
                continue
            any_oauth = True
            tables = message_tables(conn)
            if not tables:
                continue
            try:
                found = conn.execute(
                    data_sql(cutoff, tables, oauth_since)).fetchone()
            except sqlite3.Error as exc:
                log.get_logger("plugin.opencode").warning(
                    "Codex usage query failed for %s: %s", path, exc)
                failures += 1
                continue
            read_any = True
            if found and found[0]:
                rows.extend(parse_rows(str(found[0])))
        finally:
            conn.close()
    if not any_oauth or (not read_any and failures):
        return None
    acc = Accumulator()
    prepared: dict[str, _codex.Prepared | None] = {}
    for row in deduplicated(rows):
        if row.moment.timestamp() < since_ts or not row.model:
            continue
        if row.model not in prepared:
            prepared[row.model] = _codex.prepare(pricing, row.model)
        item = prepared[row.model]
        day = day_key(row.moment)
        if item is None:
            if row.total > 0:
                acc.add_unknown(day, row.model)
            continue
        acc.add(day, row.total, _codex.cost_prepared(item, row.tokens), row.model)
    return acc.build()
