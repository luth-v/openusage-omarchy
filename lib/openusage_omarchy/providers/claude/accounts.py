"""Claude account discovery. Swap slots, default identity, Desktop orgs.

Card ids are opaque: the bare family id for the default login, else
``family:<hash8>`` from the lowercased identity key. Labels may carry the
email locally; the loopback API never serves it (G2).
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

    def display(self, fallback_org: str = "") -> str:
        org = self.organization_name or fallback_org or f"Organization {self.organization_id[:8]}"
        return f"Claude: {org} ({self.email})"


@dataclass(frozen=True)
class AccountCard:
    card_id: str
    identity_key: str
    organization_id: str
    display: str
    swap: SwapAccount | None = None
    desktop_only: bool = False


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
        name = str(entry.get("organizationName") or "").strip()
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


def default_identity(env: Env) -> tuple[str, str, str]:
    """(identity_key, label, anchor) for the default home, else empties."""
    override = (os.environ.get("CLAUDE_CONFIG_DIR") or "").strip()
    if override and "," in override:
        return "", "", ""
    anchor = Path(override).expanduser() if override else env.paths.home / ".claude"
    default_home = env.paths.home / ".claude"
    if override:
        identity_path = anchor / ".claude.json"
    else:
        identity_path = env.paths.home / ".claude.json"
    _ = default_home
    try:
        text = identity_path.read_text(encoding="utf-8")
    except OSError:
        return "", "", ""
    try:
        parsed = json.loads(text)
    except ValueError:
        return "", "", ""
    account = parsed.get("oauthAccount") if isinstance(parsed, dict) else None
    if not isinstance(account, dict):
        return "", "", ""
    user = str(account.get("accountUuid") or "").strip().lower()
    if not user:
        return "", "", ""
    org = str(account.get("organizationUuid") or "").strip().lower()
    key = f"{user}|{org}" if org else user
    email = str(account.get("emailAddress") or "").strip()
    name = str(account.get("organizationName") or "").strip()
    label = f"{email} ({name})" if email and name else (name or email)
    return key, label, str(anchor)


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
    swaps = discover_swap(env)
    default_key, default_label, _anchor = default_identity(env)
    desktops = discover_desktop_orgs(env)
    if not swaps and not default_key and not desktops:
        return []
    cards: list[AccountCard] = []
    seen: set[str] = set()
    bare_taken = False

    def _add(key: str, org: str, display: str, swap: SwapAccount | None = None) -> None:
        nonlocal bare_taken
        if key in seen:
            return
        seen.add(key)
        cards.append(
            AccountCard(
                card_id=card_id_for(key, bare_taken),
                identity_key=key,
                organization_id=org,
                display=display,
                swap=swap,
            )
        )
        bare_taken = True

    if default_key:
        org = default_key.split("|")[-1] if "|" in default_key else ""
        _add(default_key, org, "Claude" if len(swaps) + len(desktops) == 0 else f"Claude — {default_label or 'Default'}")
    for item in desktops:
        if item[0] == default_key:
            continue
        _add(item[0], item[1], f"Claude — {item[2]}")
    for item in swaps:
        for index, card in enumerate(cards):
            if card.identity_key == item.identity_key:
                cards[index] = AccountCard(
                    card_id=card.card_id,
                    identity_key=card.identity_key,
                    organization_id=card.organization_id,
                    display=item.display(),
                    swap=item,
                )
                seen.add(item.identity_key)
                break
        else:
            _add(item.identity_key, item.organization_id, item.display(), item)
    # Single-card installs keep the bare family id and plain display name.
    if len(cards) == 1 and cards[0].card_id != family:
        only = cards[0]
        cards[0] = AccountCard(
            card_id=family,
            identity_key=only.identity_key,
            organization_id=only.organization_id,
            display="Claude",
            swap=only.swap,
        )
    return cards


def to_ref(card: AccountCard) -> model.CardRef:
    hashed = hashlib.sha256(card.identity_key.lower().encode("utf-8")).hexdigest()
    return model.CardRef(
        card_id=card.card_id,
        family=family,
        label=card.display,
        account_key=hashed,
    )
