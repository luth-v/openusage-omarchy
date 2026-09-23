"""Claude collector. File and environment logins, Swap multi-account.

Linux port notes: no macOS keychain read (Claude Code on Linux uses the
credentials file); no Desktop token decryption (no AES in stdlib, no Linux
Desktop app). Desktop org cards authenticate through matching CLI or Swap
logins. Rate limits surface as errors; the engine keeps last-good data.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
from typing import Any

from ... import http as _http, log, model, parse
from ...providers import Env, iso_now
from ...spend import context as _spend_ctx
from ...spend import pi as _pi
from ...spend import tiles as _tiles
from ...spend.aggregate import Accumulator
from . import accounts as _accounts
from . import auth as _auth
from . import client as _client
from . import logs as _logs
from . import mapper as _mapper

family = "claude"
LABEL = "Claude"
NOTE = "From your Claude usage history (estimated)"
NOTE_PI = "From your Claude usage history and pi (estimated)"


def cards(env: Env) -> list[model.CardRef]:
    found = _accounts.assemble(env)
    if not found:
        return [model.CardRef(card_id="claude", family=family, label=LABEL)]
    return [_accounts.to_ref(card) for card in found]


def _card_identity(card: model.CardRef, env: Env) -> _accounts.AccountCard | None:
    for item in _accounts.assemble(env):
        if item.card_id == card.card_id:
            return item
    return None


def has_credentials(env: Env) -> bool:
    if _auth.load_file(env) is not None:
        return True
    import os

    if (os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or "").strip():
        return True
    for swap in _accounts.discover_swap(env):
        if _auth.load_file(env, swap.session_dir) is not None:
            return True
        if _load_vault(swap) is not None:
            return True
    return False


def _load_vault(swap: _accounts.SwapAccount) -> _auth.Credential | None:
    from pathlib import Path

    path = Path(f"{swap.root}/credentials/.creds-{swap.slot}-{swap.email}.enc")
    try:
        encoded = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        text = base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeError):
        return None
    parsed = _auth.parse_credentials(text)
    if not isinstance(parsed, dict):
        return None
    oauth = _auth.OAuth.from_dict(parsed.get("claudeAiOauth"))
    if not oauth.access_token:
        return None
    oauth.refresh_token = ""
    return _auth.Credential(oauth=oauth, source="swapVault")


def _candidates(env: Env, card: model.CardRef) -> list[_auth.Credential]:
    identity = _card_identity(card, env)
    if identity is not None and identity.swap is not None:
        return _swap_candidates(env, identity.swap)
    stored: list[_auth.Credential] = []
    file_cred = _auth.load_file(env)
    if file_cred is not None:
        stored.append(file_cred)
    return _auth.with_environment_token(stored)


def _swap_candidates(env: Env, swap: _accounts.SwapAccount) -> list[_auth.Credential]:
    import os

    out: list[_auth.Credential] = []
    default_key, _label, _anchor = _accounts.default_identity(env)
    if default_key == swap.identity_key:
        file_cred = _auth.load_file(env)
        if file_cred is not None:
            out.append(file_cred)
    session = _auth.load_file(env, swap.session_dir)
    if session is not None:
        out.append(session)
    vault = _load_vault(swap)
    if vault is not None:
        out.append(vault)
    live = [item for item in out if _auth.live_availability(item) == "available"]
    rest = [item for item in out if _auth.live_availability(item) != "available"]
    ordered = live + rest
    _ = os.environ
    return ordered


def _refresh(
    env: Env, cred: _auth.Credential, config: _auth.OAuthConfig
) -> _auth.Credential:
    if not cred.oauth.refresh_token:
        raise model.CollectorError("auth", _auth.SESSION_EXPIRED)
    try:
        reply = _client.refresh_token(env.http, cred.oauth.refresh_token, config)
    except _http.HttpError as exc:
        raise model.CollectorError(
            "transport", "Usage request failed. Check your connection."
        ) from exc
    if reply.status in (400, 401):
        payload = _http.parse_json_object(reply.body) or {}
        code = str(payload.get("error") or payload.get("error_description") or "")
        if code == "invalid_grant":
            raise model.CollectorError("auth", _auth.SESSION_EXPIRED)
        raise model.CollectorError(
            "status", f"Usage request failed (HTTP {reply.status}). Try again later."
        )
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status", f"Usage request failed (HTTP {reply.status}). Try again later."
        )
    try:
        decoded = json.loads(reply.body.decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise model.CollectorError(
            "empty", "Usage response invalid. Try again later."
        ) from exc
    token = str(decoded.get("access_token") or "").strip()
    if not token:
        raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    oauth = _auth.OAuth(
        access_token=token,
        refresh_token=str(decoded.get("refresh_token") or "").strip()
        or cred.oauth.refresh_token,
        expires_at=cred.oauth.expires_at,
        subscription_type=cred.oauth.subscription_type,
        rate_limit_tier=cred.oauth.rate_limit_tier,
        scopes=cred.oauth.scopes,
    )
    expires_in = parse.number(decoded.get("expires_in"))
    if expires_in is not None:
        oauth.expires_at = env.clock.now().timestamp() * 1000 + expires_in * 1000
    updated = _auth.Credential(
        oauth=oauth, source=cred.source, path=cred.path,
        inference_only=cred.inference_only,
    )
    expected = _auth.load_generation(cred.path) if cred.path else ()
    try:
        _auth.save(updated, expected)
    except (OSError, ValueError) as exc:
        log.get_logger("auth.claude").error("rotation persist failed: %s", type(exc).__name__)
    return updated


def _verify(
    env: Env, token: str, identity: str, config: _auth.OAuthConfig
) -> dict[str, Any] | None:
    if "|" not in identity:
        return None
    try:
        reply = _client.fetch_profile(env.http, token, config)
    except _http.HttpError as exc:
        raise model.CollectorError(
            "transport", "Usage request failed. Check your connection."
        ) from exc
    if not 200 <= reply.status < 300:
        return None
    profile = _client.decode_profile(reply.body)
    if profile is None:
        return None
    if _client.identity_of(profile) != identity.lower():
        raise model.CollectorError("auth", _auth.SESSION_EXPIRED)
    return profile


def _attempt(
    env: Env, token: str, config: _auth.OAuthConfig
) -> tuple[int, bytes, dict[str, str] | None]:
    try:
        reply = _client.fetch_usage(env.http, token, config)
    except _http.HttpError as exc:
        if exc.status is not None:
            raise model.CollectorError(
                "status", f"Usage request failed (HTTP {exc.status}). Try again later."
            )
        raise model.CollectorError(
            "transport", "Usage request failed. Check your connection."
        )
    return reply.status, reply.body, reply.headers


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    try:
        config = _auth.oauth_config()
    except ValueError as exc:
        raise model.CollectorError("auth", str(exc))
    candidates = _candidates(env, card)
    candidates = [item for item in candidates if item.usable]
    if not candidates:
        raise model.CollectorError("auth", _auth.NOT_LOGGED_IN)
    now = env.clock.now()
    now_ms = now.timestamp() * 1000
    sources = ", ".join(_auth.diagnostics(item, now_ms) for item in candidates)
    log.get_logger("plugin.claude").info("refresh start (%s)", sources)
    identity = ""
    found = _card_identity(card, env)
    if found is not None:
        identity = found.identity_key
    last_error: model.CollectorError | None = None
    for cred in candidates:
        if _auth.live_availability(cred) == "missingProfileScope":
            last_error = model.CollectorError("auth", _auth.MISSING_SCOPE)
            continue
        if _auth.live_availability(cred) == "inferenceOnlyToken":
            continue
        try:
            return _probe(env, card, cred, identity, config, now)
        except model.CollectorError as exc:
            if exc.category == "auth":
                last_error = exc
                continue
            raise
    raise last_error or model.CollectorError("auth", _auth.NOT_LOGGED_IN)


def attach_spend(card: model.CardRef, env: Env, snap: model.Snapshot,
                 now: dt.datetime) -> model.Snapshot:
    """Spend tiles for a quota snapshot. Never raises; quota wins on failure.

    The engine runs this after the quota batch publishes, so a slow log
    scan never trips the provider deadline. Pricing is cached-only here:
    the store revalidates in the background (see pricing_store.Store).
    """
    # Multi-account installs share one home; only the bare card carries
    # history so Total Spend never double-counts. Full per-org filtering
    # stays future work.
    if card.card_id != family:
        return snap
    try:
        pricing = _spend_ctx.load_pricing(env)
        stamp = _spend_ctx.since_ts(env)
        native = _logs.scan(env.paths.home, env.paths.scan_dir, stamp, pricing)
        extra = _pi.scan(env.paths.home, env.paths.scan_dir, "claude",
                         stamp, pricing)
        merged = Accumulator.merged([native, extra])
        if merged is None:
            return snap
        metrics = dict(snap.metrics)
        note = NOTE_PI if extra is not None else NOTE
        _tiles.append_token_usage(
            merged.series, metrics, now, estimated=True,
            unknown_by_day=merged.unknown_by_day,
            model_usage=merged.model_usage, model_note=note,
            fallback_by_day=merged.fallback_by_day)
        _tiles.append_trend(merged.series, metrics, now, note,
                            fallback_by_day=merged.fallback_by_day)
        return model.Snapshot(card=snap.card, plan=snap.plan,
                              fetched_at=snap.fetched_at, metrics=metrics,
                              error=snap.error)
    except Exception as exc:
        log.get_logger("plugin.claude").warning("spend scan failed: %s", exc)
        return snap


def _probe(
    env: Env,
    card: model.CardRef,
    cred: _auth.Credential,
    identity: str,
    config: _auth.OAuthConfig,
    now: dt.datetime,
) -> model.Snapshot:
    working = cred
    if _auth.needs_refresh(working.oauth, now.timestamp() * 1000):
        working = _refresh(env, working, config)
    profile: dict[str, Any] | None = None
    if identity:
        profile = _verify(env, working.oauth.access_token, identity, config)
    status, body, headers = _attempt(env, working.oauth.access_token, config)
    if status in (401, 403):
        working = _refresh(env, working, config)
        if identity:
            profile = _verify(env, working.oauth.access_token, identity, config)
        status, body, headers = _attempt(env, working.oauth.access_token, config)
        if status in (401, 403):
            raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    if status == 429:
        retry = _mapper.parse_retry_after(headers or {}, now)
        raise model.CollectorError("rate_limited", _mapper.rate_limit_message(retry))
    if not 200 <= status < 300:
        raise model.CollectorError(
            "status", f"Usage request failed (HTTP {status}). Try again later."
        )
    try:
        metrics, plan = _mapper.map_usage(body, working.oauth, now)
    except ValueError:
        raise model.CollectorError("empty", "Usage response invalid. Try again later.")
    if profile is None:
        try:
            reply = _client.fetch_profile(env.http, working.oauth.access_token, config)
        except _http.HttpError:
            reply = None
        if reply is not None and 200 <= reply.status < 300:
            profile = _client.decode_profile(reply.body)
    if profile is not None:
        live = _mapper.format_live_plan(profile, working.oauth)
        if live:
            plan = live
    return model.Snapshot(card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
