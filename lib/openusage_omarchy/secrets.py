"""Plugin-owned API keys (OpenRouter, Z.ai). libsecret first, file, env last.

Read order: keyring (service ``openusage-omarchy``) wins over the 0600
fallback file, which wins over the environment. A saved key therefore always
overrides a stale exported one, as upstream does with its config file.

Values travel on stdin only: ``secret-tool store`` gets the key through its
standard input, never argv. Nothing here logs a value. Upstream's legacy key
files under ``~/.config/openusage/`` are never read: that path belongs to an
unrelated tool and is forbidden.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from . import atomic, log, paths

SERVICE = "openusage-omarchy"
PROVIDERS = ("openrouter", "zai")
ENV_NAMES = {
    "openrouter": ("OPENROUTER_API_KEY", "OPENROUTER_KEY"),
    "zai": ("ZAI_API_KEY", "GLM_API_KEY"),
}
TOOL_TIMEOUT = 10


class SecretsError(Exception):
    pass


def keys_path(dirs: paths.Paths) -> Path:
    return dirs.data_dir / "keys.json"


def _tool(args: list[str], stdin: bytes | None = None) -> tuple[int, str]:
    """Run secret-tool. Returns (exit code, stripped stdout). Never raises."""
    try:
        proc = subprocess.run(
            ["secret-tool", *args],
            input=stdin,
            capture_output=True,
            timeout=TOOL_TIMEOUT,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        log.get_logger("keychain").debug("secret-tool unavailable: %s", type(exc).__name__)
        return 127, ""
    try:
        text = proc.stdout.decode("utf-8", errors="replace").strip()
    except (ValueError, UnicodeError):
        text = ""
    return proc.returncode, text


def lookup(attributes: dict[str, str]) -> str | None:
    """Generic keyring read (own keys and foreign tool tokens). None on miss."""
    args = ["lookup"]
    for key, value in attributes.items():
        args += [key, value]
    code, text = _tool(args)
    if code != 0 or not text:
        return None
    return text


def _store_in_keyring(provider: str, value: str) -> bool:
    label = f"OpenUsage Omarchy {provider} API key"
    args = ["store", "--label=" + label, "service", SERVICE, "provider", provider]
    code, _ = _tool(args, stdin=value.encode("utf-8"))
    if code == 0:
        return True
    log.get_logger("keychain").warning(
        "secret-tool store failed for %s; using the fallback file", provider)
    return False


def _clear_in_keyring(provider: str) -> None:
    _tool(["clear", "service", SERVICE, "provider", provider])


def _read_keys_file(dirs: paths.Paths) -> dict[str, str]:
    raw = atomic.read_json(keys_path(dirs))
    if not isinstance(raw, dict):
        return {}
    return {
        str(key): str(value).strip()
        for key, value in raw.items()
        if isinstance(value, str) and str(value).strip()
    }


def _write_keys_file(dirs: paths.Paths, keys: dict[str, str]) -> None:
    try:
        paths.assert_writable(keys_path(dirs), dirs.home)
        paths.ensure_dir(keys_path(dirs).parent, 0o700)
        atomic.write_json_atomic(keys_path(dirs), keys, mode=0o600)
    except (OSError, ValueError) as exc:
        raise SecretsError(f"could not write the fallback key file: {exc}") from exc


def _from_env(provider: str) -> str | None:
    for name in ENV_NAMES.get(provider, ()):
        value = (os.environ.get(name) or "").strip()
        if value:
            return value
    return None


def _check_provider(provider: str) -> None:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown key provider: {provider}")


def get_key(provider: str, dirs: paths.Paths) -> str | None:
    """The saved or exported key, or None. Keyring first, env last."""
    _check_provider(provider)
    found = lookup({"service": SERVICE, "provider": provider})
    if found:
        return found
    stored = _read_keys_file(dirs).get(provider)
    if stored:
        return stored
    return _from_env(provider)


def key_source(provider: str, dirs: paths.Paths) -> str:
    """Presence only (never the value): keyring|file|env|none."""
    _check_provider(provider)
    if lookup({"service": SERVICE, "provider": provider}):
        return "keyring"
    if _read_keys_file(dirs).get(provider):
        return "file"
    if _from_env(provider):
        return "env"
    return "none"


def set_key(provider: str, value: str, dirs: paths.Paths) -> None:
    """Save a key: keyring when it works, else the 0600 fallback file."""
    _check_provider(provider)
    trimmed = value.strip()
    if not trimmed:
        raise SecretsError("empty API key")
    if _store_in_keyring(provider, trimmed):
        log.get_logger("keychain").info("saved %s key to the keyring", provider)
        return
    keys = _read_keys_file(dirs)
    keys[provider] = trimmed
    _write_keys_file(dirs, keys)
    log.get_logger("keychain").info("saved %s key to the fallback file", provider)


def delete_key(provider: str, dirs: paths.Paths) -> None:
    """Remove a saved key from the keyring and the fallback file."""
    _check_provider(provider)
    _clear_in_keyring(provider)
    keys = _read_keys_file(dirs)
    if provider in keys:
        del keys[provider]
        _write_keys_file(dirs, keys)
    log.get_logger("keychain").info("removed the saved %s key", provider)
