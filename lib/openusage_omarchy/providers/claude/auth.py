"""Claude credentials. File plus environment on Linux.

Upstream order is keychain-before-file; Claude Code on Linux keeps its login
in the credentials file only, so there is no keychain read here. Desktop
tokens need macOS Keychain AES decryption and are out of scope on Linux:
Desktop org cards authenticate through CLI or Swap logins for that org.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ... import credentials as _cas, log, parse
from ...providers import Env

PROD_BASE_API = "https://api.anthropic.com"
PROD_REFRESH_URL = "https://platform.claude.com/v1/oauth/token"
PROD_CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
NONPROD_CLIENT_ID = "22422756-60c9-4084-8eb7-27705fd5cf9a"
USAGE_SCOPE = "user:profile"
NOT_LOGGED_IN = "Not logged in. Run `claude` to authenticate."
SESSION_EXPIRED = "Session expired. Run `claude` to log in again."
TOKEN_EXPIRED = "Token expired. Run `claude` to log in again."
MISSING_SCOPE = (
    "Re-login for live usage. Run `claude` and sign in again "
    "to restore session and weekly limits."
)


@dataclass
class OAuth:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float | None = None
    subscription_type: str = ""
    rate_limit_tier: str = ""
    scopes: list[str] | None = None

    @classmethod
    def from_dict(cls, raw: Any) -> "OAuth":
        if not isinstance(raw, dict):
            return cls()
        scopes = raw.get("scopes")
        return cls(
            access_token=str(raw.get("accessToken") or "").strip(),
            refresh_token=str(raw.get("refreshToken") or "").strip(),
            expires_at=parse.number(raw.get("expiresAt")),
            subscription_type=str(raw.get("subscriptionType") or "").strip(),
            rate_limit_tier=str(raw.get("rateLimitTier") or "").strip(),
            scopes=[str(item) for item in scopes] if isinstance(scopes, list) else None,
        )

    def to_dict(self) -> dict:
        out: dict[str, Any] = {}
        if self.access_token:
            out["accessToken"] = self.access_token
        if self.refresh_token:
            out["refreshToken"] = self.refresh_token
        if self.expires_at is not None:
            out["expiresAt"] = self.expires_at
        if self.subscription_type:
            out["subscriptionType"] = self.subscription_type
        if self.rate_limit_tier:
            out["rateLimitTier"] = self.rate_limit_tier
        if self.scopes is not None:
            out["scopes"] = list(self.scopes)
        return out


@dataclass
class Credential:
    oauth: OAuth
    source: str = "file"
    path: str = ""
    inference_only: bool = False

    @property
    def usable(self) -> bool:
        return bool(self.oauth.access_token.strip())


@dataclass
class OAuthConfig:
    usage_url: str
    refresh_url: str
    client_id: str


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def claude_home(env: Env, session_dir: str = "") -> Path:
    if session_dir:
        return Path(session_dir).expanduser()
    override = _env("CLAUDE_CONFIG_DIR")
    if override and "," not in override:
        return Path(override).expanduser()
    return env.paths.home / ".claude"


def credentials_path(env: Env, session_dir: str = "") -> Path:
    return claude_home(env, session_dir) / ".credentials.json"


def parse_credentials(text: str) -> dict[str, Any] | None:
    decoded = parse.decode_json_hex(text)
    return decoded if isinstance(decoded, dict) else None


def load_file(env: Env, session_dir: str = "") -> Credential | None:
    path = credentials_path(env, session_dir)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    parsed = parse_credentials(text)
    if parsed is None:
        return None
    oauth = OAuth.from_dict(parsed.get("claudeAiOauth"))
    if not oauth.access_token:
        return None
    source = "file" if not session_dir else "accountFile"
    return Credential(oauth=oauth, source=source, path=str(path))


def oauth_config() -> OAuthConfig:
    base = PROD_BASE_API
    refresh = PROD_REFRESH_URL
    client = PROD_CLIENT_ID
    if _env("USER_TYPE") == "ant":
        flag = (_env("USE_LOCAL_OAUTH") or "").lower()
        staging = (_env("USE_STAGING_OAUTH") or "").lower()
        if flag and flag not in ("0", "false", "no", "off"):
            root = (_env("CLAUDE_LOCAL_OAUTH_API_BASE") or "http://localhost:8000").rstrip("/")
            base, refresh, client = root, root + "/v1/oauth/token", NONPROD_CLIENT_ID
        elif staging and staging not in ("0", "false", "no", "off"):
            base = "https://api-staging.anthropic.com"
            refresh = "https://platform.staging.ant.dev/v1/oauth/token"
            client = NONPROD_CLIENT_ID
    custom = _env("CLAUDE_CODE_CUSTOM_OAUTH_URL")
    if custom:
        root = custom.rstrip("/")
        base, refresh = root, root + "/v1/oauth/token"
    override = _env("CLAUDE_CODE_OAUTH_CLIENT_ID")
    if override:
        client = override
    usage = base.rstrip("/") + "/api/oauth/usage"
    for candidate in (usage, refresh):
        parts = urlparse(candidate)
        if not parts.scheme or not parts.netloc:
            raise ValueError(f"Invalid Claude OAuth URL: {candidate}")
    return OAuthConfig(usage_url=usage, refresh_url=refresh, client_id=client)


def needs_refresh(oauth: OAuth, now_ms: float) -> bool:
    if oauth.expires_at is None:
        return False
    return oauth.expires_at - now_ms <= 5 * 60 * 1000


def live_availability(cred: Credential) -> str:
    if cred.inference_only:
        return "inferenceOnlyToken"
    scopes = cred.oauth.scopes
    if not scopes:
        return "available"
    return "available" if USAGE_SCOPE in scopes else "missingProfileScope"


def with_environment_token(stored: list[Credential]) -> list[Credential]:
    token = _env("CLAUDE_CODE_OAUTH_TOKEN")
    if not token:
        return stored
    live = [item for item in stored if live_availability(item) == "available"]
    base = (live or stored or [None])[0]
    oauth = OAuth(access_token=token)
    if base is not None:
        oauth = OAuth(
            access_token=token,
            subscription_type=base.oauth.subscription_type,
            rate_limit_tier=base.oauth.rate_limit_tier,
            scopes=base.oauth.scopes,
        )
    candidate = Credential(oauth=oauth, source="environment", inference_only=True)
    return [candidate] if not live else live + [candidate]


def save(cred: Credential, expected: tuple) -> bool:
    """CAS-write a rotation. Environment and vault sources never persist."""
    if cred.source in ("environment", "swapVault", "desktop"):
        return False
    if not cred.path:
        return False
    from ...providers import Env as _Env  # noqa: F401  (keeps seam visible)

    def _apply(payload: Any) -> Any | None:
        if not isinstance(payload, dict):
            return None
        payload = dict(payload)
        payload["claudeAiOauth"] = cred.oauth.to_dict()
        return payload

    current = load_generation(cred.path)
    if current != expected:
        return False
    return _cas.cas_update_json(
        Path(cred.path), _apply, "claude", log.get_logger("auth.claude")
    )


def load_generation(path: str) -> tuple:
    try:
        text = Path(path).read_text(encoding="utf-8")
    except OSError:
        return ()
    parsed = parse_credentials(text)
    if not isinstance(parsed, dict):
        return ()
    oauth = OAuth.from_dict(parsed.get("claudeAiOauth"))
    return (oauth.access_token, oauth.refresh_token, oauth.expires_at)


def diagnostics(cred: Credential, now_ms: float) -> str:
    refresh = "yes" if cred.oauth.refresh_token else "no"
    if cred.oauth.expires_at is None:
        expired = "unknown"
    else:
        expired = "yes" if cred.oauth.expires_at <= now_ms else "no"
    return f"{cred.source} refresh={refresh} expired={expired}"
