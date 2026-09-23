"""Credential write-back with compare-and-swap. The one rotation helper.

Rules: re-read under lock, compare the generation token (mtime, size, hash),
replace atomically keeping mode and owner, never create a missing file, and
log ``rotated (source=...)`` only. No token values anywhere.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable

from . import atomic, paths


def _generation(path: Path, raw: bytes, stat: "os.stat_result") -> str:
    digest = hashlib.sha256(raw).hexdigest()
    return f"{stat.st_mtime_ns}:{stat.st_size}:{digest}"


def cas_update_json(
    path: Path,
    transform: Callable[[Any], Any | None],
    source: str,
    logger: logging.Logger | None = None,
) -> bool:
    """Apply transform to the JSON file when its generation is unchanged.

    Returns True on write, False when the file changed underneath us (the
    caller keeps the live token for this session only). Never creates path.
    """
    runtime_dir = paths.ensure_runtime_dir(paths.Paths.from_env().runtime_dir)
    lock_dir = paths.ensure_dir(runtime_dir / "locks")
    lock_path = lock_dir / hashlib.sha256(str(path.resolve()).encode()).hexdigest()
    with atomic.locked(lock_path):
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return False
        try:
            stat = path.stat()
            payload = json.loads(raw.decode("utf-8"))
        except (OSError, ValueError):
            return False
        before = _generation(path, raw, stat)
        updated = transform(payload)
        if updated is None:
            return False
        try:
            current = path.read_bytes()
            now = path.stat()
        except OSError:
            return False
        if _generation(path, current, now) != before:
            return False
        text = (json.dumps(updated, indent=2, sort_keys=True) + "\n").encode()
        atomic.write_bytes_atomic(path, text, stat.st_mode & 0o777,
                                  (stat.st_uid, stat.st_gid))
    if logger is not None:
        logger.info("rotated (source=%s)", source)
    return True
