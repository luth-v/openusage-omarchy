"""Atomic file writes and advisory locks. The sole file writer helpers."""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


@contextmanager
def locked(path: Path, exclusive: bool = True) -> Iterator[int]:
    """Hold an flock on path (created when missing). Yields the fd."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield fd
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def write_json_atomic(path: Path, payload: Any, mode: int = 0o600) -> None:
    """Write JSON via temp file plus atomic rename. Never leaves partial files."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=path.name + ".", suffix=".tmp"
    )
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, separators=(",", ":"), sort_keys=True))
            handle.write("\n")
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def write_bytes_atomic(path: Path, data: bytes, mode: int = 0o600,
                       owner: tuple[int, int] | None = None) -> None:
    """Write bytes from a private temp file, then preserve requested metadata."""
    fd, name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".",
                                suffix=".tmp")
    tmp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if owner is not None:
            try:
                os.chown(tmp, *owner)
            except (OSError, PermissionError):
                pass
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def read_json(path: Path) -> Any | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
