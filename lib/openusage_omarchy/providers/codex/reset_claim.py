"""Codex reset-credit claim. One credit per call, by explicit id.

Protocol from the open-source Codex CLI, verified live (see upstream
docs/research/codex-reset-credit-claim.md). The caller mints one UUID per
credit and reuses it on retry, so a retry can never spend a second credit.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from ... import http as _http, log, model, parse
from ...providers import Env
from . import client as _client

SUCCESS = "success"
NOTHING_TO_RESET = "nothingToReset"
NO_CREDIT = "noCredit"
FAILED = "failed"


def parse_expiry(value: Any) -> dt.datetime | None:
    moment = parse.parse_time(value)
    if moment is not None:
        return moment
    seconds = parse.number(value)
    if seconds is None:
        return None
    try:
        return dt.datetime.fromtimestamp(seconds, dt.timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def credit_id_for(body: dict, expiry: dt.datetime) -> str | None:
    credits = body.get("credits")
    if not isinstance(credits, list):
        return None
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        status = credit.get("status")
        if isinstance(status, str) and status != "available":
            continue
        moment = parse_expiry(credit.get("expires_at"))
        if moment is None:
            continue
        if abs((moment - expiry).total_seconds()) < 1:
            found = credit.get("id")
            if isinstance(found, str) and found:
                return found
    return None


def soonest_available(body: dict) -> tuple[str, dt.datetime] | None:
    credits = body.get("credits")
    if not isinstance(credits, list):
        return None
    best: tuple[str, dt.datetime] | None = None
    for credit in credits:
        if not isinstance(credit, dict):
            continue
        status = credit.get("status")
        if isinstance(status, str) and status != "available":
            continue
        found = credit.get("id")
        if not isinstance(found, str) or not found:
            continue
        moment = parse_expiry(credit.get("expires_at"))
        if moment is None:
            continue
        if best is None or moment < best[1]:
            best = (found, moment)
    return best


def outcome_from_consume(status: int, body: bytes) -> str:
    if not 200 <= status < 300:
        return FAILED
    payload = _http.parse_json_object(body)
    if not isinstance(payload, dict):
        return FAILED
    code = payload.get("code")
    if code in ("reset", "already_redeemed"):
        return SUCCESS
    if code == "nothing_to_reset":
        return NOTHING_TO_RESET
    if code == "no_credit":
        return NO_CREDIT
    return FAILED


def claim(
    http: _http.HttpClient,
    token: str,
    account_id: str,
    expiry: dt.datetime | None,
    redeem_request_id: str,
) -> str:
    """Claim one credit. None expiry means the soonest available."""
    logger = log.get_logger("plugin.codex")
    try:
        listing = _client.fetch_reset_credits(http, token, account_id)
    except _http.HttpError as exc:
        logger.error("reset claim: credit list fetch failed: %s", type(exc).__name__)
        return FAILED
    if listing.status in (401, 403):
        logger.error("reset claim: credit list rejected (%s)", listing.status)
        return FAILED
    if not 200 <= listing.status < 300:
        logger.error("reset claim: credit list fetch failed (%s)", listing.status)
        return FAILED
    body = _http.parse_json_object(listing.body)
    if not isinstance(body, dict):
        logger.error("reset claim: credit list undecodable")
        return FAILED
    credit_id = ""
    if expiry is not None:
        found = credit_id_for(body, expiry)
        if found is None:
            return NO_CREDIT
        credit_id = found
    else:
        soonest = soonest_available(body)
        if soonest is None:
            count = parse.number(body.get("available_count")) or 0
            return NO_CREDIT if count <= 0 else FAILED
        credit_id = soonest[0]
    try:
        reply = _client.consume_reset_credit(
            http, token, account_id, credit_id, redeem_request_id
        )
    except _http.HttpError as exc:
        logger.error("reset claim: consume request failed: %s", type(exc).__name__)
        return FAILED
    if reply.status in (401, 403):
        logger.error("reset claim: consume rejected (%s)", reply.status)
        return FAILED
    result = outcome_from_consume(reply.status, reply.body)
    if result == FAILED:
        logger.error("reset claim: consume failed (%s)", reply.status)
    return result


def claim_for_card(card: model.CardRef, env: Env,
                   expiry: str | None, request_id: str | None) -> str:
    """Redeem only with credentials belonging to the requested card."""
    from . import _card_entry, _fetch_usage, _refresh, _scoped
    from . import auth as _auth

    entry = _card_entry(card, env)
    if entry is not None:
        candidates = _scoped(_auth.load_candidates(list(entry.homes)),
                             entry.identity, True)
    elif card.card_id == "codex":
        candidates = _auth.load_candidates()
    else:
        return FAILED
    moment = parse.parse_time(expiry) if expiry else None
    key = request_id or str(uuid.uuid4())
    for credential in candidates:
        if not credential.usable or credential.auth.tokens is None:
            continue
        try:
            if (_auth.needs_refresh(credential.auth, env.clock.now())
                    and not credential.read_only):
                credential = _refresh(env, credential)
            # The same request path as fetch can refresh on a 401 or 403.
            _, credential = _fetch_usage(env, credential)
        except model.CollectorError:
            continue
        tokens = credential.auth.tokens
        if tokens is None or not tokens.access_token:
            continue
        outcome = claim(env.http, tokens.access_token,
                        tokens.account_id, moment, key)
        if outcome != FAILED:
            return outcome
    return FAILED
