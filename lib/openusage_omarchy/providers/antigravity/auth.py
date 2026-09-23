"""Antigravity credentials. Keyring token plus an in-memory refresh cache.

Current builds keep OAuth tokens where the app / ``agy`` CLI wrote them: on
macOS the Keychain, on Linux the Secret Service store. The lookup tries the
attribute layouts go-keyring uses; unknown layouts simply yield no token.

The refreshed access token lives in memory only (bound to the refresh
credential's fingerprint), never on disk: cache files hold no tokens. We
never write back to Antigravity's own credential.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import threading
from dataclasses import dataclass
from typing import Any

from ... import log, model, parse, secrets
from ...providers import Env

SERVICE = "gemini"
ACCOUNT = "antigravity"
REFRESH_BUFFER_S = 60

_ACCESS_KEYS = (
    "access_token", "accessToken", "token", "id_token", "idToken",
    "bearerToken", "auth_token", "authToken",
)
_REFRESH_KEYS = ("refresh_token", "refreshToken")
_EXPIRY_KEYS = ("expiry", "expires_at", "expiresAt")
_NESTED_KEYS = ("tokens", "oauth", "oauth2", "credentials", "auth")

_CACHE: dict[str, tuple[str, float]] = {}
_CACHE_LOCK = threading.Lock()


@dataclass(frozen=True)
class KeychainToken:
    access_token: str | None = None
    refresh_token: str | None = None
    expiry: dt.datetime | None = None


def _first_string(found: dict[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = found.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def token_from_object(found: dict[str, Any]) -> KeychainToken | None:
    """Nested ``token`` object preferred, else fields off the root."""
    source = found.get("token")
    source = source if isinstance(source, dict) else found
    access = _first_string(source, _ACCESS_KEYS)
    refresh = _first_string(source, _REFRESH_KEYS)
    expiry_raw = _first_string(source, _EXPIRY_KEYS)
    expiry = parse.parse_time(expiry_raw) if expiry_raw else None
    if access is None and refresh is None:
        for key in _NESTED_KEYS:
            nested = found.get(key)
            if isinstance(nested, dict):
                token = token_from_object(nested)
                if token is not None:
                    return token
        return None
    return KeychainToken(access_token=access, refresh_token=refresh, expiry=expiry)


def extract_token(raw: str) -> KeychainToken | None:
    """A keyring value to tokens: JSON, Bearer, or a bare token."""
    import json

    cleaned = raw.strip().strip("\ufeff").strip()
    unwrapped = parse.unwrap_go_keyring(cleaned)
    if not unwrapped:
        return None
    text = unwrapped.strip().strip("\ufeff").strip()
    if not text:
        return None
    try:
        decoded = json.loads(text)
    except ValueError:
        decoded = None
    if isinstance(decoded, dict):
        return token_from_object(decoded)
    if isinstance(decoded, str) and decoded.strip():
        return KeychainToken(access_token=decoded.strip())
    if decoded is not None:
        return None
    if text.startswith("{") or text.startswith("["):
        return None
    if text.startswith("Bearer "):
        token = text[len("Bearer "):].strip()
        return KeychainToken(access_token=token) if token else None
    return KeychainToken(access_token=text)


def load_keychain_token(env: Env) -> KeychainToken | None:
    """The stored Antigravity login. None when absent; raises when malformed."""
    combos = [
        {"service": SERVICE, "account": ACCOUNT},
        {"service": SERVICE, "username": ACCOUNT},
        {"application": "go-keyring", "service": SERVICE, "username": ACCOUNT},
        {"application": "go-keyring", "service": SERVICE, "account": ACCOUNT},
    ]
    malformed = False
    for attributes in combos:
        raw = secrets.lookup(attributes)
        if raw is None:
            continue
        token = extract_token(raw)
        if token is not None:
            return token
        malformed = True
    if malformed:
        log.get_logger("auth.antigravity").error(
            "keyring credential is malformed")
        raise model.CollectorError(
            "auth",
            "Antigravity credentials are invalid. "
            "Open Antigravity or run `agy` to sign in again.",
        )
    return None


def is_usable(expiry: dt.datetime | None, now: dt.datetime) -> bool:
    if expiry is None:
        return True
    return (expiry - now).total_seconds() > REFRESH_BUFFER_S


def fingerprint(refresh_token: str | None) -> str | None:
    cleaned = (refresh_token or "").strip()
    if not cleaned:
        return None
    return hashlib.sha256(cleaned.encode("utf-8")).hexdigest()


def load_cached_token(refresh_token: str | None, now: dt.datetime) -> str | None:
    expected = fingerprint(refresh_token)
    if expected is None:
        discard_cached_token()
        return None
    with _CACHE_LOCK:
        hit = _CACHE.get(expected)
        if hit is None:
            return None
        token, expires = hit
        if expires <= now.timestamp() + REFRESH_BUFFER_S or not token.strip():
            _CACHE.pop(expected, None)
            return None
        return token


def cache_token(
    access_token: str, expires_in: float,
    refresh_token: str, now: dt.datetime,
) -> None:
    expected = fingerprint(refresh_token)
    if expected is None or not access_token.strip():
        return
    with _CACHE_LOCK:
        _CACHE[expected] = (access_token, now.timestamp() + expires_in)


def discard_cached_token(refresh_token: str | None = None) -> None:
    with _CACHE_LOCK:
        if refresh_token is None:
            _CACHE.clear()
        else:
            expected = fingerprint(refresh_token)
            if expected is not None:
                _CACHE.pop(expected, None)
