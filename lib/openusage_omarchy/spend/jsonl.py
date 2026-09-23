"""JSONL discovery and incremental parse helpers.

Ports upstream JSONLScanning plus the bounded streaming reader. The
persistent parse cache lives in scan_cache.py; this module holds file
discovery, the scan-window bound, and the 1 MB record guard.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path

READ_CHUNK = 64 * 1024
MAX_RECORD = 1024 * 1024
PREVIOUS_DAYS = 30


@dataclass(frozen=True)
class DiscoveredFile:
    path: str
    size: int
    mtime: float


def since_date(days_back: int, now: dt.datetime) -> dt.datetime:
    """Start of the day days_back days ago, in now's zone."""
    day = now - dt.timedelta(days=days_back)
    try:
        return day.replace(hour=0, minute=0, second=0, microsecond=0)
    except (ValueError, OverflowError):
        return day


def jsonl_files(under: Path) -> list[DiscoveredFile]:
    """Every *.jsonl regular file under dir, path-sorted."""
    try:
        target = under.resolve()
    except OSError:
        return []
    if not target.is_dir():
        return []
    out: list[DiscoveredFile] = []
    try:
        stack = [target]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir())
            except OSError:
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        real = entry.resolve()
                        if real.is_dir():
                            stack.append(real)
                            continue
                        if real.is_file() and real.suffix == ".jsonl":
                            stat = real.stat()
                            out.append(DiscoveredFile(
                                path=str(entry), size=stat.st_size,
                                mtime=stat.st_mtime))
                        continue
                    if entry.is_dir():
                        stack.append(entry)
                    elif entry.is_file() and entry.suffix == ".jsonl":
                        stat = entry.stat()
                        out.append(DiscoveredFile(
                            path=str(entry), size=stat.st_size,
                            mtime=stat.st_mtime))
                except OSError:
                    continue
    except OSError:
        return []
    out.sort(key=lambda item: item.path)
    return out


def read_records(path: str) -> tuple[list[bytes] | None, int]:
    """Read one file as newline records. None means unreadable.

    Records over 1 MB are skipped and counted, as upstream. The file is
    read in 64 KB chunks so a large rollout never loads at once.
    """
    oversized = 0
    records: list[bytes] = []
    pending = bytearray()
    discarding = False
    try:
        handle = open(path, "rb")
    except OSError:
        return None, 0
    try:
        while True:
            try:
                chunk = handle.read(READ_CHUNK)
            except OSError:
                return None, oversized
            if not chunk:
                break
            start = 0
            while start < len(chunk):
                end = chunk.find(b"\n", start)
                if end < 0:
                    fragment = chunk[start:]
                    if not discarding:
                        if len(pending) + len(fragment) > MAX_RECORD:
                            oversized += 1
                            discarding = True
                            pending.clear()
                        else:
                            pending += fragment
                    start = len(chunk)
                else:
                    fragment = chunk[start:end]
                    if discarding:
                        discarding = False
                    else:
                        if len(pending) + len(fragment) > MAX_RECORD:
                            oversized += 1
                            pending.clear()
                        else:
                            pending += fragment
                            records.append(bytes(pending))
                            pending.clear()
                    start = end + 1
        if pending and not discarding:
            records.append(bytes(pending))
    finally:
        try:
            handle.close()
        except OSError:
            pass
    return records, oversized
