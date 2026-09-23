"""Cursor HTTP calls. Connect RPC plus cookie REST fallbacks."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from ... import http as _http, model
from . import auth as _auth

USAGE_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCurrentPeriodUsage"
GROK_BOT_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetSandUsageStatus"
PLAN_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetPlanInfo"
REFRESH_URL = "https://api2.cursor.sh/oauth/token"
CREDITS_URL = "https://api2.cursor.sh/aiserver.v1.DashboardService/GetCreditGrantsBalance"
REST_USAGE_URL = "https://cursor.com/api/usage"
SUMMARY_URL = "https://cursor.com/api/usage-summary"
STRIPE_URL = "https://cursor.com/api/auth/stripe"
CLIENT_ID = "KbZUR41cY7W6zRSdpSUJ7I7mLYBKOCmB"
CONNECTION_FAILED = "Usage request failed. Check your connection."


def connect_post(client: _http.HttpClient, url: str, token: str) -> _http.Response:
    return client.post(
        url,
        b"{}",
        headers={
            "Authorization": "Bearer " + token,
            "Content-Type": "application/json",
            "Connect-Protocol-Version": "1",
        },
        timeout=10,
    )


def rest_get(client: _http.HttpClient, url: str, cookie: str) -> _http.Response:
    return client.get(
        url, headers={"Cookie": f"WorkosCursorSessionToken={cookie}"}, timeout=10
    )


def refresh_access_token(
    client: _http.HttpClient, refresh: str
) -> str:
    try:
        reply = client.post(
            REFRESH_URL,
            json.dumps(
                {
                    "grant_type": "refresh_token",
                    "client_id": CLIENT_ID,
                    "refresh_token": refresh,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            timeout=15,
        )
    except _http.HttpError as exc:
        raise model.CollectorError("transport", CONNECTION_FAILED) from exc
    if reply.status in (400, 401):
        payload = _http.parse_json_object(reply.body) or {}
        if payload.get("shouldLogout") is True:
            raise model.CollectorError("auth", _auth.SESSION_EXPIRED)
        raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status", f"Usage request failed (HTTP {reply.status}). Try again later."
        )
    payload = _http.parse_json_object(reply.body) or {}
    if payload.get("shouldLogout") is True:
        raise model.CollectorError("auth", _auth.SESSION_EXPIRED)
    token = str(payload.get("access_token") or "").strip()
    if not token:
        raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    return token


def optional_connect(
    client: _http.HttpClient, url: str, access: str
) -> dict[str, Any] | None:
    try:
        reply = connect_post(client, url, access)
    except _http.HttpError:
        return None
    if not 200 <= reply.status < 300:
        return None
    return _http.parse_json_object(reply.body)


def optional_rest(
    client: _http.HttpClient, url: str, access: str
) -> dict[str, Any] | None:
    session = _auth.session_cookie(access)
    if session is None:
        return None
    user_id, cookie = session
    target = url
    if url == REST_USAGE_URL:
        target = f"{url}?{urlencode({'user': user_id})}"
    try:
        reply = rest_get(client, target, cookie)
    except _http.HttpError:
        return None
    if not 200 <= reply.status < 300:
        return None
    return _http.parse_json_object(reply.body)
