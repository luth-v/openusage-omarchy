"""Claude HTTP calls. Usage, profile, refresh. No parsing beyond JSON."""

from __future__ import annotations

import json
from typing import Any

from ... import http as _http
from . import auth as _auth

SCOPES = (
    "user:profile user:inference user:sessions:claude_code "
    "user:mcp_servers user:file_upload"
)
USER_AGENT = "claude-cli/2.1.280 (external, cli)"
BETA = "oauth-2025-04-20"


def refresh_token(
    client: _http.HttpClient, refresh: str, config: _auth.OAuthConfig
) -> _http.Response:
    body = json.dumps(
        {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": config.client_id,
            "scope": SCOPES,
        }
    ).encode("utf-8")
    return client.post(
        config.refresh_url,
        body,
        headers={"Content-Type": "application/json"},
        timeout=15,
    )


def usage_url(base: str) -> str:
    join = "&" if "?" in base else "?"
    return f"{base}{join}cedar_ember=1"


def fetch_usage(
    client: _http.HttpClient, token: str, config: _auth.OAuthConfig
) -> _http.Response:
    return client.get(
        usage_url(config.usage_url),
        headers={
            "Authorization": "Bearer " + token.strip(),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-beta": BETA,
            "User-Agent": USER_AGENT,
        },
        timeout=10,
    )


def profile_url(usage: str) -> str:
    return usage.rstrip("/").rsplit("/", 1)[0] + "/profile"


def fetch_profile(
    client: _http.HttpClient, token: str, config: _auth.OAuthConfig
) -> _http.Response:
    return client.get(
        profile_url(config.usage_url),
        headers={
            "Authorization": "Bearer " + token.strip(),
            "Accept": "application/json",
            "anthropic-beta": BETA,
        },
        timeout=10,
    )


def decode_profile(body: bytes) -> dict[str, Any] | None:
    payload = _http.parse_json_object(body)
    if not isinstance(payload, dict):
        return None
    account = payload.get("account")
    if not isinstance(account, dict) or not account.get("uuid"):
        return None
    return payload


def identity_of(profile: dict[str, Any]) -> str:
    account = profile.get("account") or {}
    org = profile.get("organization") or {}
    user = str(account.get("uuid") or "").strip().lower()
    org_id = str(org.get("uuid") or "").strip().lower()
    if user and org_id:
        return f"{user}|{org_id}"
    return user
