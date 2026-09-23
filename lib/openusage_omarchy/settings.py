"""Settings resolver. Reads shell.json read-only. Never writes it.

Lookup order mirrors shell.qml updateEntryInline: the bar layout entries
first, then plugins[]. Defaults come only from manifest.json barWidget.defaults.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import PLUGIN_ID, catalog


def find_entry(shell: dict, plugin_id: str = PLUGIN_ID) -> dict:
    bar = shell.get("bar") or {}
    layout = bar.get("layout") or {}
    for section in ("left", "center", "right"):
        entries = layout.get(section) or []
        for entry in entries:
            if isinstance(entry, dict) and entry.get("id") == plugin_id:
                return entry
    for entry in shell.get("plugins") or []:
        if isinstance(entry, dict) and entry.get("id") == plugin_id:
            return entry
    return {}


class Settings:
    def __init__(self, shell_path: Path, manifest_path: Path | None = None) -> None:
        self._shell_path = shell_path
        self._manifest_path = manifest_path
        self._mtime: float | None = None
        self._entry: dict[str, Any] = {}
        self._defaults: dict[str, Any] | None = None

    def get(self, key: str, fallback: Any = None) -> Any:
        entry = self._resolve()
        if key in entry:
            return entry[key]
        if self._defaults is None:
            self._defaults = catalog.manifest_defaults(self._manifest_path)
        if key in self._defaults:
            return self._defaults[key]
        return fallback

    def changed(self) -> bool:
        try:
            return self._shell_path.stat().st_mtime != self._mtime
        except OSError:
            return self._mtime is not None

    def _resolve(self) -> dict[str, Any]:
        try:
            mtime = self._shell_path.stat().st_mtime
        except OSError:
            self._mtime = None
            self._entry = {}
            return {}
        if self._mtime != mtime:
            try:
                shell = json.loads(self._shell_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}
            self._entry = find_entry(shell) if isinstance(shell, dict) else {}
            self._mtime = mtime
        return self._entry
