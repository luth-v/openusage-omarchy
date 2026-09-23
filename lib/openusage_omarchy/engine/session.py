"""Login-session id. Keyed to $XDG_RUNTIME_DIR, not to the daemon PID.

The runtime dir clears at logout, so a shell hot-reload keeps the session id
and does not re-hit all provider APIs. Upstream's "fresh only if fetched this
session" uses this id.
"""

from __future__ import annotations

import secrets
from pathlib import Path
from .. import paths


def get_session_id(path: Path) -> str:
    paths.ensure_runtime_dir(path.parent)
    try:
        text = path.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    if text and len(text) <= 128 and text.replace("-", "").replace("_", "").isalnum():
        return text
    fresh = secrets.token_hex(16)
    try:
        path.write_text(fresh + "\n", encoding="utf-8")
    except OSError:
        return fresh
    return fresh
