"""Codex collector. Auth files across homes, Swap multi-account.

Linux port notes: no macOS keychain fallback (the CLI on Linux uses
auth.json). Swap cards are read-only and never refresh tokens.
"""

from __future__ import annotations

import datetime as dt

from ... import http as _http, log, model, parse
from ...providers import Env, iso_now
from ...spend import context as _spend_ctx
from ...spend import opencode_codex as _oc_codex
from ...spend import pi as _pi
from ...spend import tiles as _tiles
from ...spend.aggregate import Accumulator
from . import accounts as _accounts
from . import auth as _auth
from . import client as _client
from . import logs as _logs
from . import mapper as _mapper

family = "codex"
LABEL = "Codex"
NOTE = "From your Codex logs (estimated)"


def cards(env: Env) -> list[model.CardRef]:
    found = _accounts.assemble(env)
    if not found:
        return [model.CardRef(card_id="codex", family=family, label=LABEL)]
    return [_accounts.to_ref(card) for card in found]


def _card_entry(card: model.CardRef, env: Env) -> _accounts.AccountCard | None:
    for item in _accounts.assemble(env):
        if item.card_id == card.card_id:
            return item
    return None


def has_credentials(env: Env) -> bool:
    for cred in _auth.load_candidates():
        if cred.usable:
            return True
    return False


def _scoped(
    candidates: list[_auth.Credential], identity: _accounts.Identity | None,
    read_only: bool,
) -> list[_auth.Credential]:
    if identity is None:
        return candidates
    out: list[_auth.Credential] = []
    for cred in candidates:
        found = _accounts.identity_of(cred.auth)
        if found != identity:
            continue
        cred.auth.tokens.account_id = identity.account_id
        cred.read_only = True
        out.append(cred)
    _ = read_only
    return out


def _refresh(env: Env, cred: _auth.Credential) -> _auth.Credential:
    tokens = cred.auth.tokens
    refresh = tokens.refresh_token if tokens else ""
    if not refresh:
        raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    try:
        reply = _client.refresh_token(env.http, refresh)
    except _http.HttpError as exc:
        raise model.CollectorError(
            "transport", "Usage request failed. Check your connection."
        ) from exc
    if reply.status in (400, 401):
        payload = _http.parse_json_object(reply.body) or {}
        code = ""
        error = payload.get("error")
        if isinstance(error, dict):
            code = str(error.get("code") or error.get("error") or "")
        elif isinstance(error, str):
            code = error
        code = code or str(payload.get("code") or "")
        if code == "refresh_token_expired":
            raise model.CollectorError("auth", _auth.SESSION_EXPIRED)
        if code == "refresh_token_reused":
            raise model.CollectorError("auth", _auth.TOKEN_CONFLICT)
        if code == "refresh_token_invalidated":
            raise model.CollectorError("auth", _auth.TOKEN_REVOKED)
        raise model.CollectorError(
            "status", f"Usage request failed (HTTP {reply.status}). Try again later."
        )
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status", f"Usage request failed (HTTP {reply.status}). Try again later."
        )
    payload = _http.parse_json_object(reply.body) or {}
    token = str(payload.get("access_token") or "")
    if not token:
        raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    if tokens is not None:
        tokens.access_token = token
        new_refresh = str(payload.get("refresh_token") or "")
        if new_refresh:
            tokens.refresh_token = new_refresh
        new_id = str(payload.get("id_token") or "")
        if new_id:
            tokens.id_token = new_id
    cred.auth.last_refresh = env.clock.now().isoformat()
    try:
        _auth.save(cred)
    except (OSError, ValueError) as exc:
        log.get_logger("auth.codex").error("rotation persist failed: %s", type(exc).__name__)
    return cred


def _fetch_usage(
    env: Env, cred: _auth.Credential
) -> tuple[_http.Response, _auth.Credential]:
    tokens = cred.auth.tokens
    token = tokens.access_token if tokens else ""
    account = tokens.account_id if tokens else ""
    try:
        reply = _client.fetch_usage(env.http, token, account)
    except _http.HttpError as exc:
        if exc.status is not None:
            raise model.CollectorError(
                "status", f"Usage request failed (HTTP {exc.status}). Try again later."
            )
        raise model.CollectorError(
            "transport", "Usage request failed. Check your connection."
        )
    if reply.status not in (401, 403):
        return reply, cred
    if cred.read_only:
        raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    refreshed = _refresh(env, cred)
    tokens = refreshed.auth.tokens
    token = tokens.access_token if tokens else ""
    account = tokens.account_id if tokens else ""
    try:
        reply = _client.fetch_usage(env.http, token, account)
    except _http.HttpError as exc:
        raise model.CollectorError(
            "transport", "Usage request failed. Check your connection."
        ) from exc
    if reply.status in (401, 403):
        raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    return reply, refreshed


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    entry = _card_entry(card, env)
    if entry is not None:
        candidates = _auth.load_candidates(list(entry.homes))
        candidates = _scoped(candidates, entry.identity, True)
        if not candidates:
            raise model.CollectorError(
                "auth",
                "No valid login for this Codex account. Sign in with Codex "
                "or use `xswap login <account>`, then refresh.",
            )
        return _probe_account(env, card, candidates)
    candidates = _auth.load_candidates()
    last: model.CollectorError | None = None
    for cred in candidates:
        try:
            snap = _probe(env, card, cred)
            return _with_spend(card, env, snap, env.clock.now())
        except model.CollectorError as exc:
            if exc.category == "auth":
                last = exc
                continue
            raise
    raise last or model.CollectorError("auth", _auth.NOT_LOGGED_IN)


def _probe(
    env: Env, card: model.CardRef, cred: _auth.Credential
) -> model.Snapshot:
    tokens = cred.auth.tokens
    if tokens is None or not tokens.access_token:
        if cred.auth.api_key:
            raise model.CollectorError("auth", _auth.USAGE_API_KEY)
        raise model.CollectorError("auth", _auth.NOT_LOGGED_IN)
    now = env.clock.now()
    if _auth.needs_refresh(cred.auth, now) and not cred.read_only:
        live = _auth.load_auth_at(cred.path) if cred.path else None
        if live is not None and live.usable:
            cred = live
    if _auth.needs_refresh(cred.auth, now):
        if cred.read_only:
            raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
        refresh = cred.auth.tokens.refresh_token if cred.auth.tokens else ""
        if refresh:
            cred = _refresh(env, cred)
    reply, cred = _fetch_usage(env, cred)
    return _finish(env, card, cred, reply, now)


def _probe_account(
    env: Env, card: model.CardRef, candidates: list[_auth.Credential]
) -> model.Snapshot:
    now = env.clock.now()
    for cred in candidates:
        tokens = cred.auth.tokens
        token = tokens.access_token if tokens else ""
        account = tokens.account_id if tokens else ""
        if not token:
            continue
        expires = _auth.access_expires_at(token)
        if expires is not None and expires <= now:
            continue
        try:
            reply = _client.fetch_usage(env.http, token, account)
        except _http.HttpError:
            continue
        if reply.status in (401, 403):
            continue
        snap = _finish(env, card, cred, reply, now)
        # Swap cards are read-only and share rollouts; history stays off
        # so totals never double-count or misattribute spend.
        return snap
    raise model.CollectorError(
        "auth",
        "No valid login for this Codex account. Sign in with Codex "
        "or use `xswap login <account>`, then refresh.",
    )


def _with_spend(card: model.CardRef, env: Env, snap: model.Snapshot,
                now: dt.datetime) -> model.Snapshot:
    if card.card_id != family:
        return snap
    try:
        from ...spend import codex_pricing as _codex_pricing

        pricing = _spend_ctx.load_pricing(env)
        stamp = _spend_ctx.since_ts(env)
        fallback = _spend_ctx.fallback_setting(env) or None
        native = _logs.scan(
            env.paths.home, env.paths.scan_dir, stamp, pricing, fallback)
        pi_scan = _pi.scan(
            env.paths.home, env.paths.scan_dir, "codex", stamp, pricing,
            estimate=lambda name, tokens: _codex_pricing.estimated_cost(
                pricing, name, tokens))
        oc_scan = None
        try:
            from ..opencode import data_dir as _oc_dir
            oc_path = _oc_dir(env)
            auth_text = (oc_path / "auth.json").read_text(encoding="utf-8") \
                if (oc_path / "auth.json").is_file() else "{}"
            import json as _json
            try:
                auth_json = _json.loads(auth_text)
            except ValueError:
                auth_json = {}
            oc_scan = _oc_codex.scan(
                oc_path, auth_json if isinstance(auth_json, dict) else {},
                stamp, pricing)
        except Exception as exc:
            log.get_logger("plugin.codex").warning("opencode slice failed: %s", exc)
        merged = Accumulator.merged([native, pi_scan, oc_scan])
        if merged is None:
            return snap
        parts = ["Codex logs"]
        if pi_scan is not None:
            parts.append("pi")
        if oc_scan is not None:
            parts.append("OpenCode")
        note = f"From your {' and '.join(parts)} (estimated)" if len(parts) <= 2 \
            else f"From your {', '.join(parts[:-1])} and {parts[-1]} (estimated)"
        metrics = dict(snap.metrics)
        _tiles.append_token_usage(
            merged.series, metrics, now, estimated=True,
            unknown_by_day=merged.unknown_by_day, model_usage=merged.model_usage,
            model_note=note, fallback_by_day=merged.fallback_by_day)
        _tiles.append_trend(merged.series, metrics, now, note,
                            fallback_by_day=merged.fallback_by_day)
        return model.Snapshot(card=snap.card, plan=snap.plan,
                              fetched_at=snap.fetched_at, metrics=metrics,
                              error=snap.error)
    except Exception as exc:
        log.get_logger("plugin.codex").warning("spend scan failed: %s", exc)
        return snap


def _finish(
    env: Env, card: model.CardRef, cred: _auth.Credential,
    reply: _http.Response, now: dt.datetime,
) -> model.Snapshot:
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status", f"Usage request failed (HTTP {reply.status}). Try again later."
        )
    tokens = cred.auth.tokens
    token = tokens.access_token if tokens else ""
    account = tokens.account_id if tokens else ""
    dedicated: bytes | None = None
    dedicated_status: int | None = None
    try:
        credits = _client.fetch_reset_credits(env.http, token, account)
        dedicated, dedicated_status = credits.body, credits.status
    except _http.HttpError as exc:
        log.get_logger("plugin.codex").warning(
            "reset-credit fetch failed; using usage-body count: %s", type(exc).__name__
        )
    try:
        metrics, plan = _mapper.map_usage(
            reply.body, reply.headers, dedicated, dedicated_status, now
        )
    except ValueError:
        raise model.CollectorError("empty", "Usage response invalid. Try again later.")
    return model.Snapshot(card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
