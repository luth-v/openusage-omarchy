"""Logging with handler-level redaction. Call sites never redact by hand."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from . import redact

TAG_BITS = (
    "refresh",
    "cache",
    "http",
    "auth",
    "keychain",
    "menubar",
    "updates",
    "config",
    "subprocess",
    "localapi",
)

MAX_BYTES = 10 * 1024 * 1024


def _short_tag(name: str) -> str:
    tail = name.split("openusage_omarchy.", 1)[-1]
    head = tail.split(".", 1)[0]
    if head in ("providers", "engine", "daemon", "api"):
        rest = tail.split(".", 1)
        return rest[1] if len(rest) > 1 else head
    return head


class RedactingFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        if not hasattr(record, "tag"):
            # Child loggers skip ancestor filters, so ensure the tag here.
            record.tag = _short_tag(record.name)
        return redact.redact_text(super().format(record))


def get_logger(tag: str) -> logging.Logger:
    return logging.getLogger(f"openusage_omarchy.{tag}")


class _TagFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.tag = _short_tag(record.name)
        return True


def setup(level: str, path: Path | None) -> logging.Logger:
    """Attach a redacting rotating file handler. Level: error/warning/info/debug."""
    root = logging.getLogger("openusage_omarchy")
    root.setLevel(_to_level(level))
    root.filters = [f for f in root.filters if not isinstance(f, _TagFilter)]
    root.addFilter(_TagFilter())
    for handler in list(root.handlers):
        root.removeHandler(handler)
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        _rotate_oversize(path)
        handler = RotatingFileHandler(
            path, maxBytes=MAX_BYTES, backupCount=1, encoding="utf-8"
        )
        stem = path.stem  # "openusage-omarchy": archive is "<stem>.1.log"
        handler.namer = lambda default: str(
            Path(default).with_name(f"{stem}.1.log"))
        handler.setFormatter(
            RedactingFormatter("%(asctime)s [%(tag)s] %(levelname)s %(message)s")
        )
        root.addHandler(handler)
        root.propagate = False
        for target in (path, path.with_name(f"{stem}.1.log")):
            try:
                if target.is_file() and not target.is_symlink():
                    target.chmod(0o600)
            except OSError:
                pass
    return root


def set_level(level: str) -> None:
    """Apply a Log Level change at once. Unknown levels keep the old one."""
    if str(level).lower() not in ("error", "warning", "info", "debug"):
        return
    logging.getLogger("openusage_omarchy").setLevel(_to_level(level))


def _rotate_oversize(path: Path) -> None:
    """Rotate once at launch when a previous session left an oversize file."""
    try:
        if path.stat().st_size <= MAX_BYTES:
            return
    except OSError:
        return
    try:
        path.with_name(path.stem + ".1.log").unlink(missing_ok=True)
        path.rename(path.with_name(path.stem + ".1.log"))
    except OSError:
        pass


def _to_level(level: str) -> int:
    return {
        "error": logging.ERROR,
        "warning": logging.WARNING,
        "info": logging.INFO,
        "debug": logging.DEBUG,
    }.get(str(level).lower(), logging.INFO)
