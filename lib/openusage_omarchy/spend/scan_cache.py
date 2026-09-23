"""Persistent JSONL parse cache. Totals and cost inputs only.

One directory per parser namespace plus identity fingerprint, with a
manifest.json and one record file per source path. Records hold parsed
items (timestamp, model, token buckets, carried cost) plus size and
mtime. No prompt text, no conversation content, no tokens.

Format is JSON (upstream uses plist). Flock orders daemon and CLI
writers. Identities older than 35 days are pruned.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import time
from pathlib import Path
from typing import Any

from .. import atomic, log

FORMAT_VERSION = 1
STALE_DAYS = 35


def fingerprint(value: str) -> str:
    """Stable FNV-1a hex, as upstream stableFingerprint."""
    code = 14695981039346656037
    for byte in value.encode("utf-8"):
        code ^= byte
        code = (code * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return f"{code:016x}"


def identity_dir(base: Path, namespace: str, identity: str) -> Path:
    return base / f"{namespace}-{fingerprint(identity)}"


def manifest_path(base: Path, namespace: str, identity: str) -> Path:
    return identity_dir(base, namespace, identity) / "manifest.json"


def records_dir(base: Path, namespace: str, identity: str) -> Path:
    return identity_dir(base, namespace, identity) / "files"


def record_name(path: str) -> str:
    return f"{fingerprint(path)}.json"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class Store:
    """File-backed parse cache for one parser namespace."""

    def __init__(self, base: Path, namespace: str, schema: int) -> None:
        self.base = base
        self.namespace = namespace
        self.schema = schema
        self._mem: dict[str, dict[str, dict[str, Any]]] = {}
        self._log = log.get_logger("cache")

    def _manifest(self, identity: str) -> dict[str, Any]:
        path = manifest_path(self.base, self.namespace, identity)
        with atomic.locked(path.with_name(path.name + ".lock"), exclusive=False):
            raw = atomic.read_json(path)
        if not isinstance(raw, dict):
            return {}
        if raw.get("formatVersion") != FORMAT_VERSION:
            return {}
        if raw.get("schemaVersion") != self.schema:
            return {}
        if raw.get("identity") != identity:
            return {}
        files = raw.get("files")
        return files if isinstance(files, dict) else {}

    def _write_manifest(self, identity: str, files: dict[str, Any]) -> None:
        path = manifest_path(self.base, self.namespace, identity)
        with atomic.locked(path.with_name(path.name + ".lock")):
            current = atomic.read_json(path)
            merged: dict[str, Any] = {}
            if isinstance(current, dict):
                if (current.get("formatVersion") == FORMAT_VERSION
                        and current.get("schemaVersion") == self.schema
                        and current.get("identity") == identity
                        and isinstance(current.get("files"), dict)):
                    merged = dict(current["files"])
            merged.update(files)
            # Drop removals marked None by the caller.
            merged = {k: v for k, v in merged.items() if v is not None}
            atomic.write_json_atomic(path, {
                "formatVersion": FORMAT_VERSION,
                "schemaVersion": self.schema,
                "identity": identity,
                "generatedAt": _utcnow().isoformat(),
                "files": merged,
            })

    def load_record(
        self, identity: str, source: str, size: int, mtime: float,
    ) -> list[dict[str, Any]] | None:
        """Cached items when size and mtime match, else None."""
        mem = self._mem.get(identity, {}).get(source)
        if mem is not None:
            if mem.get("size") == size and mem.get("mtime") == mtime:
                items = mem.get("items")
                return list(items) if isinstance(items, list) else []
            return None
        manifest = self._manifest(identity)
        entry = manifest.get(source)
        if not isinstance(entry, dict):
            return None
        if entry.get("size") != size or entry.get("mtime") != mtime:
            return None
        name = entry.get("record")
        if not isinstance(name, str):
            return None
        path = records_dir(self.base, self.namespace, identity) / name
        raw = atomic.read_json(path)
        if not isinstance(raw, dict):
            return None
        if raw.get("path") != source:
            return None
        items = raw.get("items")
        if not isinstance(items, list):
            return None
        cleaned = [item for item in items if isinstance(item, dict)]
        self._mem.setdefault(identity, {})[source] = {
            "size": size, "mtime": mtime, "items": cleaned,
        }
        return list(cleaned)

    def save_record(
        self, identity: str, source: str, size: int, mtime: float,
        items: list[dict[str, Any]],
    ) -> None:
        self._mem.setdefault(identity, {})[source] = {
            "size": size, "mtime": mtime, "items": list(items),
        }
        name = record_name(source)
        directory = records_dir(self.base, self.namespace, identity)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            atomic.write_json_atomic(directory / name, {
                "path": source, "size": size, "mtime": mtime,
                "items": items,
            })
        except OSError as exc:
            self._log.warning("scan cache write failed: %s", exc)
            return
        try:
            self._write_manifest(identity, {source: {
                "size": size, "mtime": mtime, "record": name,
            }})
        except OSError as exc:
            self._log.warning("scan cache manifest failed: %s", exc)

    def prune(self, identity: str, live: set[str]) -> None:
        """Drop manifest entries for files no longer seen."""
        manifest = self._manifest(identity)
        removals = {path: None for path in manifest if path not in live}
        if removals:
            try:
                self._write_manifest(identity, removals)
            except OSError:
                pass
        mem = self._mem.get(identity)
        if mem is not None:
            for path in list(mem):
                if path not in live:
                    mem.pop(path, None)

    def prune_stale_identities(self) -> None:
        """Remove identity dirs untouched for 35 days."""
        try:
            entries = list(self.base.iterdir())
        except OSError:
            return
        cutoff = time.time() - STALE_DAYS * 86400
        for entry in entries:
            if not entry.is_dir() or not entry.name.startswith(self.namespace + "-"):
                continue
            manifest = entry / "manifest.json"
            try:
                stamp = manifest.stat().st_mtime if manifest.exists() else entry.stat().st_mtime
            except OSError:
                continue
            if stamp < cutoff:
                import shutil
                try:
                    shutil.rmtree(entry)
                except OSError:
                    pass

    def scan(
        self,
        files: list,
        since_ts: float,
        identity: str,
        parse_records: Any,
    ) -> list[dict[str, Any]] | None:
        """Incremental scan over discovered files.

        files carry .path/.size/.mtime. parse_records(records) returns a
        list of item dicts or None when the file is unreadable. Returns
        None only when cancelled (never here); empty list means no rows.
        """
        from . import jsonl as _jsonl

        items: list[dict[str, Any]] = []
        live: set[str] = set()
        for found in files:
            if found.mtime < since_ts:
                continue
            live.add(found.path)
            cached = self.load_record(identity, found.path, found.size, found.mtime)
            if cached is not None:
                items.extend(cached)
                continue
            records, oversized = _jsonl.read_records(found.path)
            if oversized:
                self._log.warning(
                    "skipped %d oversized log records in %s; spend may be incomplete",
                    oversized, found.path)
            if records is None:
                continue
            try:
                parsed = parse_records(records)
            except (ValueError, TypeError):
                continue
            if parsed is None:
                continue
            cleaned = [item for item in parsed if isinstance(item, dict)]
            self.save_record(identity, found.path, found.size, found.mtime, cleaned)
            items.extend(cleaned)
        self.prune(identity, live)
        return items
