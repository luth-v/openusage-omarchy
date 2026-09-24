"""Claude account discovery. Config dirs, Swap slots, Desktop orgs.

Card ids are opaque: the bare family id for the first Account (the
``~/.claude`` login when present), else ``family:<hash8>`` from the
lowercased identity key. Labels never carry the email (ADR 0006).
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ... import log, model
from ...providers import Env

family = "claude"
SETTING = "claudeAccounts"


@dataclass(frozen=True)
class SwapAccount:
    root: str
    slot: str
    email: str
    identity_key: str
    organization_id: str
    organization_name: str = ""

    @property
    def session_dir(self) -> str:
        slug = "".join(
            c if c.isalnum() or c in "._-" else "_" for c in self.email
        )
        return f"{self.root}/sessions/{self.slot}-{slug}"

    def label(self) -> str:
        return self.organization_name or f"Slot {self.slot}"


@dataclass(frozen=True)
class ConfigDir:
    """One Claude config dir. ``path`` is the realpath, ``key`` its ~ form."""

    path: str
    key: str
    identity_key: str
    organization_id: str = ""
    organization_name: str = ""
    user_label: str = ""
    hidden: bool = False

    @property
    def suffix(self) -> str:
        """``~/.claude`` -> "Default", ``~/.claude-work`` -> "work", else ""."""
        if self.key == "~/.claude":
            return "Default"
        name = Path(self.path).name
        for prefix in (".claude-", "claude-"):
            if name.startswith(prefix) and len(name) > len(prefix):
                return name[len(prefix):]
        return ""

    def label(self) -> str:
        return (self.user_label or self.suffix or self.organization_name
                or (f"Organization {self.organization_id[:8]}"
                    if self.organization_id else "Default"))


@dataclass(frozen=True)
class AccountCard:
    card_id: str
    identity_key: str
    organization_id: str
    display: str
    swap: SwapAccount | None = None
    desktop_only: bool = False
    dirs: tuple[str, ...] = ()


def card_id_for(identity_key: str, bare_taken: bool) -> str:
    if not bare_taken:
        return family
    digest = hashlib.sha256(identity_key.lower().encode("utf-8")).hexdigest()[:8]
    return f"{family}:{digest}"


def _valid_uuid(text: Any) -> str:
    try:
        return str(uuid.UUID(str(text))).lower()
    except (ValueError, TypeError, AttributeError):
        return ""


def _org_name(raw: Any) -> str:
    # Personal orgs are named "<email>'s Organization"; drop those (ADR 0006).
    name = str(raw or "").strip()
    return "" if "@" in name else name


def discover_swap(env: Env) -> list[SwapAccount]:
    root = env.paths.home / ".claude-swap-backup"
    try:
        raw = json.loads((root / "sequence.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict) or not isinstance(raw.get("accounts"), dict):
        log.get_logger("config").error("Claude Swap account list is malformed")
        return []
    accounts = raw["accounts"]
    found: list[SwapAccount] = []
    for slot in sorted(accounts, key=str):
        if not slot or not str(slot).isascii() or not str(slot).isdigit():
            continue
        entry = accounts[slot]
        if not isinstance(entry, dict):
            continue
        email = str(entry.get("email") or "")
        if not email or "/" in email or "\\" in email or "\0" in email:
            continue
        user = _valid_uuid(entry.get("uuid"))
        org = _valid_uuid(entry.get("organizationUuid"))
        if not user or not org:
            log.get_logger("config").warning("Claude Swap slot has no usable identity")
            continue
        name = _org_name(entry.get("organizationName"))
        found.append(
            SwapAccount(
                root=str(root),
                slot=str(slot),
                email=email,
                identity_key=f"{user}|{org}",
                organization_id=org,
                organization_name=name,
            )
        )
    return found


def _read_identity(path: Path) -> tuple[str, str, str]:
    """(identity_key, org_id, org_name) from oauthAccount, else empties."""
    try:
        parsed = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "", "", ""
    account = parsed.get("oauthAccount") if isinstance(parsed, dict) else None
    if not isinstance(account, dict):
        return "", "", ""
    user = str(account.get("accountUuid") or "").strip().lower()
    if not user:
        return "", "", ""
    org = str(account.get("organizationUuid") or "").strip().lower()
    return (f"{user}|{org}" if org else user), org, _org_name(account.get("organizationName"))


def identity_file(env: Env, directory: Path) -> Path:
    """Claude Code keeps the default login's state beside the home, not in
    ``~/.claude``; a ``CLAUDE_CONFIG_DIR`` login keeps it inside the dir."""
    if directory == env.paths.home / ".claude":
        return env.paths.home / ".claude.json"
    return directory / ".claude.json"


def default_identity(env: Env) -> tuple[str, str, str]:
    """(identity_key, label, anchor) for the default home, else empties."""
    override = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if override and "," in override:
        return "", "", ""
    anchor = Path(override).expanduser() if override else env.paths.home / ".claude"
    key, org, name = _read_identity(identity_file(env, anchor))
    if not key:
        return "", "", ""
    return key, name or (f"Organization {org[:8]}" if org else ""), str(anchor)


def _tilde(path: Path, home: Path) -> str:
    try:
        rest = path.relative_to(home)
    except ValueError:
        return str(path)
    return "~" if str(rest) == "." else f"~/{rest}"


def _expand(value: str, home: Path) -> Path:
    text = value.strip()
    if text == "~" or text.startswith("~/"):
        return home / text[1:].lstrip("/")
    return Path(text).expanduser()


def _real(path: Path) -> str:
    try:
        return os.path.realpath(path)
    except (OSError, ValueError):
        return str(path)


def account_settings(env: Env) -> dict[str, dict[str, Any]]:
    """Settings ``claudeAccounts`` keyed by realpath: {label, hidden}."""
    raw = env.settings.get(SETTING, {}) if env.settings is not None else {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for key, entry in raw.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(entry, dict):
            continue
        label = entry.get("label")
        out[_real(_expand(key, env.paths.home))] = {
            "label": label.strip() if isinstance(label, str) else "",
            "hidden": entry.get("hidden") is True,
        }
    return out


def _candidate_dirs(env: Env) -> list[Path]:
    home = env.paths.home
    found = [home / ".claude"]
    try:
        names = sorted(item.name for item in home.iterdir()
                       if item.name.startswith(".claude-") and item.is_dir())
    except OSError:
        names = []
    found.extend(home / name for name in names if name != ".claude-swap-backup")
    raw = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    for part in raw.split(",") if raw else []:
        if part.strip():
            found.append(_expand(part, home))
    return found


def discover_config_dirs(env: Env, include_hidden: bool = False) -> list[ConfigDir]:
    """Claude config dirs holding a login or an identity file (ADR 0006).

    Existence checks only; tokens are not read here. Dirs dedupe by
    realpath, so a symlinked or repeated ``CLAUDE_CONFIG_DIR`` is one dir.
    """
    home = env.paths.home
    prefs = account_settings(env)
    out: list[ConfigDir] = []
    seen: set[str] = set()
    for directory in _candidate_dirs(env):
        real = _real(directory)
        if real in seen:
            continue
        ident_path = identity_file(env, directory)
        if not ((directory / ".credentials.json").is_file() or ident_path.is_file()):
            continue
        seen.add(real)
        key, org, name = _read_identity(ident_path)
        if not key:
            if not (directory / ".credentials.json").is_file():
                continue
            # A login without an identity file still is its own Account.
            key = f"dir:{real}"
        pref = prefs.get(real, {})
        item = ConfigDir(
            path=real, key=_tilde(directory, home), identity_key=key,
            organization_id=org, organization_name=name,
            user_label=str(pref.get("label") or ""),
            hidden=bool(pref.get("hidden")),
        )
        if item.hidden and not include_hidden:
            continue
        out.append(item)
    return out


def settings_rows(env: Env) -> list[dict[str, Any]]:
    """Discovered dirs for the Settings surface. No email, no tokens."""
    rows = []
    for item in discover_config_dirs(env, include_hidden=True):
        rows.append({"dir": item.key, "label": item.user_label,
                     "placeholder": item.suffix or item.organization_name or "Default",
                     "hidden": item.hidden})
    return rows


def _desktop_root(env: Env) -> Path:
    override = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
    base = Path(override).expanduser() if override else env.paths.home / ".config"
    return base / "Claude"


def discover_desktop_orgs(env: Env) -> list[tuple[str, str, str]]:
    """(identity_key, org_id, label) from local Desktop material.

    Linux has no Claude Desktop AES decryption in stdlib, so this lists org
    memberships only; the cards authenticate through CLI or Swap logins.
    """
    root = _desktop_root(env)
    config_path = root / "config.json"
    try:
        text = config_path.read_text(encoding="utf-8")
    except OSError:
        return []
    try:
        parsed = json.loads(text)
    except ValueError:
        return []
    if not isinstance(parsed, dict):
        return []
    user = str(parsed.get("lastKnownAccountUuid") or "").strip().lower()
    if not _valid_uuid(user):
        return []
    orgs: set[str] = set()
    for leaf in ("claude-code-sessions", "local-agent-mode-sessions"):
        parent = root / leaf / user
        try:
            names = [item.name for item in parent.iterdir() if item.is_dir()]
        except OSError:
            continue
        for name in names:
            org = _valid_uuid(name)
            if org:
                orgs.add(org)
    for key in parsed:
        tail = str(key).split(":")[-1]
        org = _valid_uuid(tail)
        if org:
            orgs.add(org)
    try:
        history = json.loads((root / "plan-usage-history.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        history = None
    if isinstance(history, dict) and isinstance(history.get("samples"), list):
        for sample in history["samples"]:
            if isinstance(sample, dict):
                org = _valid_uuid(sample.get("org"))
                if org:
                    orgs.add(org)
    out: list[tuple[str, str, str]] = []
    for org in sorted(orgs):
        out.append((f"{user}|{org}", org, f"Organization {org[:8]}"))
    return out


def assemble(env: Env) -> list[AccountCard]:
    dirs = discover_config_dirs(env)
    swaps = discover_swap(env)
    desktops = discover_desktop_orgs(env)
    if not dirs and not swaps and not desktops:
        return []
    cards: list[AccountCard] = []
    labels: list[str] = []

    def _find(key: str) -> int:
        for index, card in enumerate(cards):
            if card.identity_key == key:
                return index
        return -1

    def _add(key: str, org: str, label: str, **extra: Any) -> None:
        cards.append(AccountCard(
            card_id=card_id_for(key, bool(cards)), identity_key=key,
            organization_id=org, display="", **extra))
        labels.append(label)

    # ~/.claude is discovered first, so its Account keeps the bare id. The
    # same identity in several dirs is one Account; a user label on any of
    # its dirs wins, else the first dir's own label.
    groups: dict[str, list[ConfigDir]] = {}
    for item in dirs:
        groups.setdefault(item.identity_key, []).append(item)
    for key, members in groups.items():
        named = [item.user_label for item in members if item.user_label]
        _add(key, members[0].organization_id,
             named[0] if named else members[0].label(),
             dirs=tuple(item.path for item in members))
    for key, org, label in desktops:
        if _find(key) < 0:
            _add(key, org, label, desktop_only=True)
    for item in swaps:
        index = _find(item.identity_key)
        if index < 0:
            _add(item.identity_key, item.organization_id, item.label(), swap=item)
            continue
        card = cards[index]
        if not card.dirs:
            labels[index] = item.label()
        cards[index] = AccountCard(
            card_id=card.card_id, identity_key=card.identity_key,
            organization_id=card.organization_id, display="", swap=item,
            dirs=card.dirs)
    # Single-card installs keep the bare family id and plain display name.
    if len(cards) == 1:
        only = cards[0]
        return [AccountCard(
            card_id=family, identity_key=only.identity_key,
            organization_id=only.organization_id, display="Claude",
            swap=only.swap, desktop_only=only.desktop_only, dirs=only.dirs)]
    return [AccountCard(
        card_id=card.card_id, identity_key=card.identity_key,
        organization_id=card.organization_id, display=f"Claude — {label}",
        swap=card.swap, desktop_only=card.desktop_only,
        dirs=card.dirs) for card, label in zip(cards, labels)]


def spend_roots(env: Env, cards: list[AccountCard]) -> dict[str, list[Path]]:
    """Log roots per card id; each config dir belongs to exactly one card.

    When at most one card owns config dirs, the bare card keeps the legacy
    root set (``logs.config_roots``: XDG ``~/.config/claude``, ``~/.claude``
    or ``CLAUDE_CONFIG_DIR``) plus its own dirs, as before ADR 0006. With
    several owners each scans its dirs only; the XDG root goes to the
    ``~/.claude`` Account. Hidden dirs never count. Cards without dirs of
    their own get no Spend, so Total Spend never double-counts.
    """
    from . import logs as _logs

    home = env.paths.home
    hidden = hidden_dirs(env)
    owners = [card for card in cards if card.dirs]
    default = _real(home / ".claude")

    def _unique(paths: list[Path]) -> list[Path]:
        seen: set[str] = set()
        kept: list[Path] = []
        for path in paths:
            real = _real(path)
            if real in seen or real in hidden:
                continue
            seen.add(real)
            kept.append(path)
        return kept

    if not cards:
        return {family: _unique(_logs.config_roots(home))}
    out: dict[str, list[Path]] = {}
    for card in cards:
        roots = [Path(item) for item in card.dirs]
        if card.card_id == family and len(owners) <= 1:
            roots = _logs.config_roots(home) + roots
        elif default in card.dirs:
            xdg = (os.environ.get("XDG_CONFIG_HOME") or "").strip()
            base = _expand(xdg, home) if xdg else home / ".config"
            roots.append(base / "claude")
        out[card.card_id] = _unique(
            [root for root in roots if (root / "projects").is_dir()])
    return out


def hidden_dirs(env: Env) -> set[str]:
    return {item.path for item in discover_config_dirs(env, include_hidden=True)
            if item.hidden}


def to_ref(card: AccountCard) -> model.CardRef:
    hashed = hashlib.sha256(card.identity_key.lower().encode("utf-8")).hexdigest()
    return model.CardRef(
        card_id=card.card_id,
        family=family,
        label=card.display,
        account_key=hashed,
    )
