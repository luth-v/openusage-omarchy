"""Antigravity collector. Pool quotas plus local spend history."""

from __future__ import annotations

import datetime as dt

from ... import http as _http, log, model
from ...providers import Env, iso_now
from ...spend import antigravity_scan as _scan
from ...spend import context as _spend_ctx
from ...spend import tiles as _tiles
from . import auth as _auth
from . import cloud as _cloud
from . import ls as _ls
from . import mapper as _mapper

family = "antigravity"
LABEL = "Antigravity"
NOTE = "From your Antigravity conversations (estimated)"
NOT_SIGNED_IN = "Start Antigravity or run `agy` and try again."
AUTH_EXPIRED = "Antigravity sign-in expired. Open Antigravity or run `agy` to refresh."
UNAVAILABLE = "Antigravity usage is temporarily unavailable. Try again shortly."


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="antigravity", family=family, label=LABEL)]


def has_credentials(env: Env) -> bool:
    # The stored login is the source of truth. A malformed store still
    # counts as present so refresh can show the repair, not a logout.
    try:
        token = _auth.load_keychain_token(env)
    except model.CollectorError:
        return True
    if token is None:
        _auth.discard_cached_token()
        return False
    return True


def _probe_ls(
    env: Env, process_name: str, markers: list[str],
    csrf_flag: str, port_flag: str | None,
) -> tuple[str | None, dict[str, model.Metric]] | None:
    found = _ls.discover(process_name, markers, csrf_flag, port_flag)
    if found is None:
        return None
    endpoints: list[tuple[str, int]] = []
    for port in found.ports:
        endpoints.append(("https", port))
        endpoints.append(("http", port))
    if found.extension_port is not None:
        endpoints.append(("http", found.extension_port))
    for scheme, port in endpoints:
        summary = _cloud.call_ls(
            env.http, scheme, port, found.csrf, "RetrieveUserQuotaSummary")
        if summary is not None:
            if 200 <= summary.status < 300:
                lines = _mapper.parse_quota_summary(summary.body)
                if lines is not None:
                    plan: str | None = None
                    status = _cloud.call_ls(
                        env.http, scheme, port, found.csrf, "GetUserStatus")
                    if status is not None and 200 <= status.status < 300:
                        parsed = _mapper.parse_user_status(status.body)
                        plan = parsed[0] if parsed else None
                    return plan, lines
            elif summary.status != 404:
                log.get_logger("plugin.antigravity").warning(
                    "RetrieveUserQuotaSummary HTTP %s; "
                    "falling back to legacy quota endpoints", summary.status)
        status = _cloud.call_ls(env.http, scheme, port, found.csrf, "GetUserStatus")
        if status is None or not 200 <= status.status < 300:
            continue
        parsed = _mapper.parse_user_status(status.body)
        if parsed is not None:
            lines = _mapper.build_lines(parsed[1])
            if lines:
                return parsed[0], lines
        fallback = _cloud.call_ls(
            env.http, scheme, port, found.csrf, "GetCommandModelConfigs")
        if fallback is not None and 200 <= fallback.status < 300:
            configs = _mapper.parse_command_configs(fallback.body)
            if configs is not None:
                lines = _mapper.build_lines(configs)
                if lines:
                    return None, lines
    return None


def _load_plan(env: Env, token: str) -> str | None:
    outcome, body = _cloud.cloud_code(
        env.http, _cloud.LOAD_CODE_ASSIST_PATH, token, "agy", {})
    if outcome == "ok" and body is not None:
        return _mapper.parse_plan(body)
    return None


def _fetch_cloud(
    env: Env, token: str
) -> tuple[str, tuple[str | None, dict[str, model.Metric]] | None]:
    outcome, body = _cloud.cloud_code(
        env.http, _cloud.QUOTA_SUMMARY_PATH, token, "antigravity", {})
    if outcome == "auth":
        return "auth", None
    if outcome == "ok" and body is not None:
        lines = _mapper.parse_quota_summary(body)
        if lines is not None:
            return "success", (_load_plan(env, token), lines)
    outcome, body = _cloud.cloud_code(
        env.http, _cloud.FETCH_MODELS_PATH, token, "antigravity", {})
    if outcome == "auth":
        return "auth", None
    if outcome == "ok" and body is not None:
        lines = _mapper.build_lines(_mapper.parse_cloud_models(body))
        if lines:
            return "success", (_load_plan(env, token), lines)
    plan: str | None = None
    project: str | None = None
    outcome, body = _cloud.cloud_code(
        env.http, _cloud.LOAD_CODE_ASSIST_PATH, token, "agy", {})
    if outcome == "auth":
        return "auth", None
    if outcome == "ok" and body is not None:
        plan = _mapper.parse_plan(body)
        project = _mapper.parse_project(body)
    query = {"project": project} if project else {}
    outcome, body = _cloud.cloud_code(
        env.http, _cloud.RETRIEVE_QUOTA_PATH, token, "agy", query)
    if outcome == "unavailable" and project:
        outcome, body = _cloud.cloud_code(
            env.http, _cloud.RETRIEVE_QUOTA_PATH, token, "agy", {})
    if outcome == "auth":
        return "auth", None
    if outcome == "ok" and body is not None:
        lines = _mapper.build_lines(_mapper.parse_quota_buckets(body))
        if lines:
            return "success", (plan, lines)
    return "unavailable", None


def _probe_cloud(
    card: model.CardRef, env: Env
) -> model.Snapshot:
    token = _auth.load_keychain_token(env)
    if token is None:
        _auth.discard_cached_token()
        raise model.CollectorError("auth", NOT_SIGNED_IN)
    now = env.clock.now()
    tokens: list[str] = []
    if token.access_token and _auth.is_usable(token.expiry, now):
        tokens.append(token.access_token)
    cached = _auth.load_cached_token(token.refresh_token, now)
    if cached and cached not in tokens:
        tokens.append(cached)
    has_creds = bool(tokens) or bool((token.refresh_token or "").strip())
    saw_auth = False
    for candidate in tokens:
        outcome, result = _fetch_cloud(env, candidate)
        if outcome == "success" and result is not None:
            plan, metrics = result
            return model.Snapshot(
                card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
        if outcome == "auth":
            saw_auth = True
    refresh = (token.refresh_token or "").strip()
    oauth = _cloud.oauth_client(env.paths.config_dir) if refresh else None
    if (saw_auth or not tokens) and refresh and oauth:
        outcome, fresh, ttl = _cloud.refresh_google_token(env.http, refresh, oauth)
        if outcome == "refreshed" and fresh:
            _auth.cache_token(fresh, ttl, refresh, now)
            outcome, result = _fetch_cloud(env, fresh)
            if outcome == "success" and result is not None:
                plan, metrics = result
                return model.Snapshot(
                    card=card, plan=plan, fetched_at=iso_now(env),
                    metrics=metrics)
            if outcome == "auth":
                raise model.CollectorError("auth", AUTH_EXPIRED)
            raise model.CollectorError("transport", UNAVAILABLE)
        if outcome == "auth":
            raise model.CollectorError("auth", AUTH_EXPIRED)
        raise model.CollectorError("transport", UNAVAILABLE)
    if saw_auth or (refresh and not tokens):
        raise model.CollectorError("auth", AUTH_EXPIRED)
    if has_creds:
        raise model.CollectorError("transport", UNAVAILABLE)
    raise model.CollectorError("auth", NOT_SIGNED_IN)


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    local = _probe_ls(
        env, "language_server", ["antigravity", "antigravity-ide"],
        "--csrf_token", "--extension_server_port",
    )
    if local is None:
        local = _probe_ls(env, "agy", [], "", None)
    if local is not None:
        plan, metrics = local
        return model.Snapshot(card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
    return _probe_cloud(card, env)


def attach_spend(card: model.CardRef, env: Env, snap: model.Snapshot,
                 now: dt.datetime) -> model.Snapshot:
    """Spend tiles for a quota snapshot. Never raises; quota wins on failure.

    Runs after the quota batch publishes (see engine.refresh.attach_spend),
    priced from the cached store while it revalidates in the background.
    """
    try:
        pricing = _spend_ctx.load_pricing(env)
        stamp = _spend_ctx.since_ts(env)
        found = _scan.scan(env.paths.home, stamp, pricing)
        if found is None:
            return snap
        metrics = dict(snap.metrics)
        _tiles.append_token_usage(
            found.series, metrics, now, estimated=True,
            unknown_by_day=found.unknown_by_day, model_usage=found.model_usage,
            model_note=NOTE)
        _tiles.append_trend(found.series, metrics, now, NOTE)
        return model.Snapshot(card=snap.card, plan=snap.plan,
                              fetched_at=snap.fetched_at, metrics=metrics,
                              error=snap.error)
    except Exception as exc:
        log.get_logger("plugin.antigravity").warning("spend scan failed: %s", exc)
        return snap
