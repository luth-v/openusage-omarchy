"""Codex account discovery. Swap registry plus default homes.

Card ids mirror Claude: the bare family id for the first account, else
``family:<hash8>`` from the identity key. Identity is the workspace id plus
the lowercased email from the id token.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ... import log, model, parse
from ...providers import Env
from . import auth as _auth

family = "codex"


@dataclass(frozen=True)
class Identity:
    account_id: str
    email: str = ""

    @property
    def key(self) -> str:
        return f"{self.account_id}|{self.email}"

    @classmethod
    def from_parts(cls, account_id: Any, email: Any) -> "Identity | None":
        account = str(account_id or "").strip().lower()
        mail = str(email or "").strip().lower()
        if not account and not mail:
            return None
        for part in (account, mail):
            if any(c in part for c in (" ", "\t", "\n", "/", "\\", "|")):
                return None
        return cls(account_id=account, email=mail)


@dataclass(frozen=True)
class SwapAccount:
    number: int
    alias: str
    identity: Identity
    home: str
    main_home: str


@dataclass(frozen=True)
class AccountCard:
    card_id: str
    identity: Identity
    display: str
    homes: tuple[str, ...] = ()


def chatgpt_account_id(payload: dict[str, Any] | None) -> str:
    if not payload:
        return ""
    claim = payload.get("https://api.openai.com/auth")
    raw: Any = None
    if isinstance(claim, dict):
        raw = claim.get("chatgpt_account_id")
    if raw is None:
        raw = payload.get("chatgpt_account_id")
    return str(raw or "").strip()


def identity_of(found: _auth.Auth) -> Identity | None:
    tokens = found.tokens
    if tokens is None:
        return None
    payload = parse.jwt_payload(tokens.id_token) if tokens.id_token else None
    claim_id = chatgpt_account_id(payload)
    stored = tokens.account_id.strip()
    if stored and claim_id and stored.lower() != claim_id.lower():
        return None
    email = ""
    if isinstance(payload, dict):
        email = str(payload.get("email") or "")
    return Identity.from_parts(stored or claim_id, email)


def _swap_root(env: Env) -> Path:
    override = (os.environ.get("XSWAP_HOME") or "").strip()
    if override:
        expanded = str(Path(override).expanduser())
        return Path(expanded[1:] if override.startswith("~/") else expanded)
    xdg = (os.environ.get("XDG_DATA_HOME") or "").strip()
    if xdg.startswith("/"):
        return Path(xdg.rstrip("/")) / "codex-swap"
    return env.paths.home / ".local" / "share" / "codex-swap"


def discover_swap(env: Env) -> list[SwapAccount]:
    try:
        raw = json.loads((_swap_root(env) / "accounts.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(raw, dict) or raw.get("schemaVersion") != 1:
        log.get_logger("config").error("Codex Swap registry has an unsupported version")
        return []
    main_home = str(raw.get("mainHome") or "")
    if not main_home.startswith("/") or "\0" in main_home:
        log.get_logger("config").error("Codex Swap registry has an invalid main home")
        return []
    entries = raw.get("accounts")
    if not isinstance(entries, list):
        return []
    found: list[SwapAccount] = []
    seen: set[int] = set()
    for entry in sorted(
        [item for item in entries if isinstance(item, dict)],
        key=lambda item: parse.number(item.get("number")) or 0,
    ):
        number = parse.number(entry.get("number"))
        home = str(entry.get("home") or "")
        ident = entry.get("identity") if isinstance(entry.get("identity"), dict) else {}
        identity = Identity.from_parts(ident.get("accountId"), ident.get("email"))
        if (
            number is None
            or int(number) <= 0
            or int(number) in seen
            or not home.startswith("/")
            or "\0" in home
            or identity is None
            or not identity.account_id
        ):
            log.get_logger("config").warning("Codex Swap account has no usable identity")
            continue
        seen.add(int(number))
        alias = str(entry.get("alias") or "").strip()
        found.append(
            SwapAccount(
                number=int(number), alias=alias, identity=identity,
                home=home, main_home=main_home,
            )
        )
    return found


def _display_default(identity: Identity) -> str:
    workspace = identity.account_id[:8] if identity.account_id else "Unknown"
    who = identity.email or identity.account_id
    return f"Codex: Workspace {workspace} ({who})"


def _display_swap(swap: SwapAccount) -> str:
    label = swap.alias or f"Workspace {swap.identity.account_id[:8]}"
    who = swap.identity.email or swap.identity.account_id
    return f"Codex: {label} ({who})"


def assemble(env: Env) -> list[AccountCard]:
    swaps = discover_swap(env)
    candidates = _auth.load_candidates()
    main_paths = [(swap.main_home + "/auth.json") for swap in swaps]
    for path in main_paths:
        found = _auth.load_auth_at(path)
        if found is not None and all(item.path != path for item in candidates):
            candidates.append(found)
    identities: list[tuple[Identity, str, list[str]]] = []
    for cred in candidates:
        if not cred.usable:
            continue
        identity = identity_of(cred.auth)
        if identity is None:
            continue
        anchor = str(Path(cred.path).parent) if cred.path else ""
        identities.append((identity, _display_default(identity), [anchor] if anchor else []))
    for swap in swaps:
        identities.append((swap.identity, _display_swap(swap), [swap.home, swap.main_home]))
    if not identities and not swaps:
        return []
    if not swaps and len(identities) <= 1:
        return []
    merged: dict[str, AccountCard] = {}
    order: list[str] = []
    for identity, display, homes in identities:
        if identity.key in merged:
            card = merged[identity.key]
            merged[identity.key] = AccountCard(
                card_id=card.card_id, identity=identity, display=card.display,
                homes=tuple(sorted(set(card.homes) | set(homes))),
            )
            continue
        order.append(identity.key)
        merged[identity.key] = AccountCard(
            card_id="", identity=identity, display=display, homes=tuple(sorted(set(homes)))
        )
    cards: list[AccountCard] = []
    for position, key in enumerate(order):
        card = merged[key]
        if position == 0:
            card_id = family
        else:
            digest = hashlib.sha256(key.lower().encode("utf-8")).hexdigest()[:8]
            card_id = f"{family}:{digest}"
        cards.append(
            AccountCard(
                card_id=card_id, identity=card.identity, display=card.display,
                homes=card.homes,
            )
        )
    if len(cards) == 1:
        only = cards[0]
        cards[0] = AccountCard(
            card_id=family, identity=only.identity, display="Codex", homes=only.homes
        )
    return cards


def to_ref(card: AccountCard) -> model.CardRef:
    hashed = hashlib.sha256(card.identity.key.lower().encode("utf-8")).hexdigest()
    return model.CardRef(
        card_id=card.card_id,
        family=family,
        label=card.display,
        account_key=hashed,
    )
