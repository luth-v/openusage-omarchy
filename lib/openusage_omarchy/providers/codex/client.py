"""Codex HTTP calls. Usage, reset credits, claim, refresh."""

from __future__ import annotations

import json
from urllib.parse import quote

from ... import http as _http

CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
REFRESH_URL = "https://auth.openai.com/oauth/token"
USAGE_URL = "https://chatgpt.com/backend-api/wham/usage"
RESET_CREDITS_URL = "https://chatgpt.com/backend-api/wham/rate-limit-reset-credits"
CONSUME_URL = RESET_CREDITS_URL + "/consume"


def refresh_token(client: _http.HttpClient, refresh: str) -> _http.Response:
    body = (
        "grant_type=refresh_token"
        f"&client_id={quote(CLIENT_ID, safe='')}"
        f"&refresh_token={quote(refresh, safe='')}"
    ).encode("utf-8")
    return client.post(
        REFRESH_URL,
        body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=15,
    )


def _usage_headers(token: str, account_id: str) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": "OpenUsage",
    }
    if account_id.strip():
        headers["ChatGPT-Account-Id"] = account_id.strip()
    return headers


def _credit_headers(token: str, account_id: str) -> dict[str, str]:
    headers = _usage_headers(token, account_id)
    headers["OpenAI-Beta"] = "codex-1"
    headers["originator"] = "Codex Desktop"
    return headers


def fetch_usage(
    client: _http.HttpClient, token: str, account_id: str
) -> _http.Response:
    return client.get(USAGE_URL, headers=_usage_headers(token, account_id), timeout=10)


def fetch_reset_credits(
    client: _http.HttpClient, token: str, account_id: str
) -> _http.Response:
    return client.get(
        RESET_CREDITS_URL, headers=_credit_headers(token, account_id), timeout=10
    )


def consume_reset_credit(
    client: _http.HttpClient,
    token: str,
    account_id: str,
    credit_id: str,
    redeem_request_id: str,
) -> _http.Response:
    body = json.dumps(
        {"redeem_request_id": redeem_request_id, "credit_id": credit_id},
        sort_keys=True,
    ).encode("utf-8")
    headers = _credit_headers(token, account_id)
    headers["Content-Type"] = "application/json"
    return client.post(CONSUME_URL, body, headers=headers, timeout=15)
