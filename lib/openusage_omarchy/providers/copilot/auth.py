"""Copilot credentials. Editor config, gh file, then the gh keyring entry.

Linux port: the file sources are unchanged (same paths). The macOS Keychain
read becomes a libsecret lookup for the go-keyring item gh writes when it
uses the system keyring instead of the file. The lookup is best-effort:
unknown attribute layouts simply yield no token.
"""

from __future__ import annotations

import json
from pathlib import Path

from ... import parse, secrets
from ...providers import Env

GH_SERVICE = "gh:github.com"


def editor_paths(env: Env) -> list[Path]:
    base = env.paths.config_dir.parent / "github-copilot"
    return [base / "apps.json", base / "hosts.json"]


def gh_hosts_path(env: Env) -> Path:
    return env.paths.config_dir.parent / "gh" / "hosts.yml"


def oauth_token_from_editor_json(text: str) -> str | None:
    """github.com oauth_token only; Enterprise hosts must not leak across."""
    try:
        found = json.loads(text)
    except ValueError:
        return None
    if not isinstance(found, dict):
        return None
    for key, value in found.items():
        if key != "github.com" and not str(key).startswith("github.com:"):
            continue
        if not isinstance(value, dict):
            continue
        token = str(value.get("oauth_token") or "").strip()
        if token:
            return token
    return None


def yaml_value(text: str, key: str, host: str = "github.com") -> str | None:
    """An indented key inside one host block of gh hosts.yml."""
    prefix = key + ":"
    header = host + ":"
    in_host = False
    for line in text.splitlines():
        if not line:
            continue
        if line[0] not in (" ", "\t"):
            in_host = line.strip().startswith(header)
            continue
        if not in_host:
            continue
        stripped = line.strip()
        if not stripped.startswith(prefix):
            continue
        value = stripped[len(prefix):].strip().strip("\"'")
        return value or None
    return None


def load_from_editor_config(env: Env) -> str | None:
    for path in editor_paths(env):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        token = oauth_token_from_editor_json(text)
        if token:
            return token
    return None


def _gh_hosts_text(env: Env) -> str | None:
    try:
        return gh_hosts_path(env).read_text(encoding="utf-8")
    except OSError:
        return None


def load_from_gh_config(env: Env) -> str | None:
    text = _gh_hosts_text(env)
    if text is None:
        return None
    return yaml_value(text, "oauth_token")


def load_from_gh_keyring(env: Env) -> str | None:
    combos: list[dict[str, str]] = []
    text = _gh_hosts_text(env)
    user = yaml_value(text, "user") if text else None
    if user:
        combos.append({"service": GH_SERVICE, "account": user})
        combos.append({"service": GH_SERVICE, "username": user})
    combos.append({"service": GH_SERVICE})
    for attributes in combos:
        raw = secrets.lookup(attributes)
        if raw is None:
            continue
        token = parse.unwrap_go_keyring(raw)
        if token:
            return token
    return None


def load_token(env: Env) -> str | None:
    return (
        load_from_editor_config(env)
        or load_from_gh_config(env)
        or load_from_gh_keyring(env)
    )
