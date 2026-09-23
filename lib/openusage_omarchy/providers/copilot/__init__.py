"""Copilot collector. Quotas from the internal Copilot user endpoint.

Paid plans meter the AI-credit pool; free plans show Chat and Completions
counts; org-managed seats add org-wide billing when the token may read it.
Since the endpoint reports percent remaining, meters flip to percent used.
"""

from __future__ import annotations

from ... import http as _http, model
from ...providers import Env, iso_now
from . import auth as _auth
from . import billing as _billing
from . import mapper as _mapper

family = "copilot"
LABEL = "Copilot"
USAGE_URL = "https://api.github.com/copilot_internal/user"
NOT_LOGGED_IN = "Sign in to GitHub Copilot in your editor, or run gh auth login, and try again."
TOKEN_INVALID = "GitHub token invalid or expired. Re-authenticate (gh auth login) and try again."
CONNECTION_FAILED = "Couldn't reach GitHub. Check your connection."
INVALID_RESPONSE = "Copilot usage response invalid. Try again later."
QUOTA_UNAVAILABLE = "Copilot usage data is unavailable for this account."


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="copilot", family=family, label=LABEL)]


def has_credentials(env: Env) -> bool:
    return _auth.load_token(env) is not None


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    token = _auth.load_token(env)
    if not token:
        raise model.CollectorError("auth", NOT_LOGGED_IN)
    try:
        reply = env.http.get(
            USAGE_URL,
            headers={
                "Authorization": "token " + token,
                "Accept": "application/json",
                "Editor-Version": "vscode/1.96.2",
                "Editor-Plugin-Version": "copilot-chat/0.26.7",
                "User-Agent": "GitHubCopilotChat/0.26.7",
                "X-Github-Api-Version": "2025-04-01",
            },
            timeout=15,
        )
    except _http.HttpError as exc:
        if exc.status is not None:
            raise model.CollectorError(
                "status",
                f"Copilot usage request failed (HTTP {exc.status}). Try again later.")
        raise model.CollectorError("transport", CONNECTION_FAILED)
    if reply.status in (401, 403):
        raise model.CollectorError("auth", TOKEN_INVALID)
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status",
            f"Copilot usage request failed (HTTP {reply.status}). Try again later.")
    body = _http.parse_json_object(reply.body)
    if body is None:
        raise model.CollectorError("empty", INVALID_RESPONSE)
    try:
        plan, metrics, org_managed = _mapper.map_body(body)
    except ValueError:
        raise model.CollectorError("empty", QUOTA_UNAVAILABLE)
    if org_managed:
        metrics.update(_billing.org_billing_lines(env, token))
    return model.Snapshot(
        card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
