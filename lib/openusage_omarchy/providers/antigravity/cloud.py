"""Antigravity network: language-server RPC, Cloud Code, Google OAuth.

Outcomes split genuine auth failures (try a refresh) from transient ones
(try the next base URL, never a refresh). The Google client pair is the
installed-application credential from the Antigravity bundle. It is not
shipped here: it is read at run time from the environment or a private
config file, and without it the refresh grant is skipped.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import quote

from ... import http as _http

LS_SERVICE = "exa.language_server_pb.LanguageServerService"
BASES = [
    "https://daily-cloudcode-pa.googleapis.com",
    "https://cloudcode-pa.googleapis.com",
]
FETCH_MODELS_PATH = "/v1internal:fetchAvailableModels"
LOAD_CODE_ASSIST_PATH = "/v1internal:loadCodeAssist"
RETRIEVE_QUOTA_PATH = "/v1internal:retrieveUserQuota"
QUOTA_SUMMARY_PATH = "/v1internal:retrieveUserQuotaSummary"
OAUTH_URL = "https://oauth2.googleapis.com/token"
CLIENT_ID_ENV = "OPENUSAGE_OMARCHY_ANTIGRAVITY_CLIENT_ID"
CLIENT_SECRET_ENV = "OPENUSAGE_OMARCHY_ANTIGRAVITY_CLIENT_SECRET"
CLIENT_FILE = "antigravity-oauth.json"
LS_METADATA = {
    "ideName": "antigravity",
    "extensionName": "antigravity",
    "ideVersion": "unknown",
    "locale": "en",
}


def call_ls(
    client: _http.HttpClient, scheme: str, port: int, csrf: str, method: str
) -> _http.Response | None:
    """One language-server RPC. None on transport failure (wrong port)."""
    url = f"{scheme}://127.0.0.1:{port}/{LS_SERVICE}/{method}"
    body = json.dumps({"metadata": LS_METADATA}).encode("utf-8")
    try:
        return client.post(
            url, body,
            headers={
                "Content-Type": "application/json",
                "Connect-Protocol-Version": "1",
                "x-codeium-csrf-token": csrf,
            },
            timeout=10,
        )
    except _http.HttpError:
        return None


def cloud_code(
    client: _http.HttpClient, path: str, token: str,
    user_agent: str, body: dict[str, str],
) -> tuple[str, bytes | None]:
    """("ok", body), ("auth", None), or ("unavailable", None)."""
    payload = json.dumps(body).encode("utf-8")
    for base in BASES:
        try:
            reply = client.post(
                base + path, payload,
                headers={
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                    "Authorization": "Bearer " + token,
                    "User-Agent": user_agent,
                },
                timeout=15,
            )
        except _http.HttpError:
            continue
        if reply.status in (401, 403):
            return "auth", None
        if 200 <= reply.status < 300:
            return "ok", reply.body
    return "unavailable", None


def oauth_client(
    config_dir: Path, environ: Mapping[str, str] | None = None
) -> tuple[str, str] | None:
    """The Google client pair from the environment, else a private file."""
    src = environ if environ is not None else os.environ
    client_id = (src.get(CLIENT_ID_ENV) or "").strip()
    secret = (src.get(CLIENT_SECRET_ENV) or "").strip()
    if client_id and secret:
        return client_id, secret
    path = config_dir / CLIENT_FILE
    try:
        info = path.lstat()
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    client_id = _value(payload, "client_id")
    secret = _value(payload, "client_secret")
    return (client_id.strip(), secret.strip()) if client_id and secret else None


def refresh_google_token(
    client: _http.HttpClient, refresh_token: str, oauth: tuple[str, str]
) -> tuple[str, str | None, float]:
    """("refreshed", token, ttl), ("auth", None, 0), or ("unavailable",...)."""
    form = "&".join(
        f"{key}={quote(value, safe='')}"
        for key, value in (
            ("client_id", oauth[0]),
            ("client_secret", oauth[1]),
            ("refresh_token", refresh_token),
            ("grant_type", "refresh_token"),
        )
    ).encode("utf-8")
    try:
        reply = client.post(
            OAUTH_URL, form,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=15,
        )
    except _http.HttpError:
        return "unavailable", None, 0.0
    if 200 <= reply.status < 300:
        payload = _http.parse_json_object(reply.body)
        token = _value(payload, "access_token")
        if token:
            ttl = _number(payload, "expires_in") or 3600.0
            return "refreshed", token, ttl
        return "unavailable", None, 0.0
    if reply.status in (408, 429):
        return "unavailable", None, 0.0
    if 400 <= reply.status < 500:
        return "auth", None, 0.0
    return "unavailable", None, 0.0


def _value(payload: dict[str, Any] | None, key: str) -> str | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _number(payload: dict[str, Any] | None, key: str) -> float | None:
    if not isinstance(payload, dict):
        return None
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None
