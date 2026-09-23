"""First-run detection. Cheap local-only credential probes, never network.

Every collector answers from files, the keyring, or the environment already
on the machine. Ollama always answers False: its key cannot tell Cloud from
local-only use, so it never auto-enables (see catalog autoEnable).
"""

from __future__ import annotations

from .. import catalog
from ..providers import Env


def detect_all(collectors: list, env: Env,
               allowed: set[str] | None = None) -> dict[str, bool]:
    found: dict[str, bool] = {}
    for collector in collectors:
        provider = catalog.cached().provider(collector.family)
        if (provider is not None and not provider.auto_enable) or (
                allowed is not None and collector.family not in allowed):
            found[collector.family] = False
            continue
        try:
            found[collector.family] = bool(collector.has_credentials(env))
        except Exception:
            found[collector.family] = False
    return found
