"""Cursor collector. Quota plus CSV spend history."""

from __future__ import annotations

from typing import Any

from ... import http as _http, log, model, parse
from ...providers import Env, iso_now
from ...spend import context as _spend_ctx
from ...spend import tiles as _tiles
from . import auth as _auth
from . import client as _client
from . import mapper as _mapper
from . import summary as _summary
from . import usage_csv as _csv

family = "cursor"
LABEL = "Cursor"
NOTE = "From your Cursor usage export"
USAGE_URL = _client.USAGE_URL
PLAN_URL = _client.PLAN_URL
GROK_BOT_URL = _client.GROK_BOT_URL
CREDITS_URL = _client.CREDITS_URL
REST_USAGE_URL = _client.REST_USAGE_URL
SUMMARY_URL = _client.SUMMARY_URL
STRIPE_URL = _client.STRIPE_URL

# Pass 1 seam names, kept so older tests and callers keep working.
map_usage = _mapper.map_usage_simple


def plan_label(remote: str, local_plan: str, local_status: str) -> str:
    name = (remote or local_plan or "").strip()
    if not name:
        return ""
    label = parse.title_cased(name)
    if local_status and local_status.lower() not in ("", "active"):
        return f"{label} ({local_status})"
    return label


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="cursor", family=family, label=LABEL)]


def has_credentials(env: Env) -> bool:
    return _auth.has_credentials(env)


def _request_failed(status: int | None) -> model.CollectorError:
    if status is not None:
        return model.CollectorError(
            "status", f"Usage request failed (HTTP {status}). Try again later."
        )
    return model.CollectorError("transport", _client.CONNECTION_FAILED)


def _fetch_plan(env: Env, access: str) -> tuple[str | None, bool]:
    body = _client.optional_connect(env.http, _client.PLAN_URL, access)
    if body is None:
        return None, True
    info = body.get("planInfo")
    info = info if isinstance(info, dict) else {}
    name = str(info.get("planName") or "").strip()
    if not name:
        log.get_logger("plugin.cursor").warning(
            "optional plan response contained invalid plan metadata")
        return None, True
    return name, False


def _append_grok_bot(env: Env, access: str, metrics: dict[str, model.Metric]) -> None:
    body = _client.optional_connect(env.http, _client.GROK_BOT_URL, access)
    if body is None:
        return
    if body.get("usesPooledEnterpriseAllowance") is True:
        return
    if body.get("hasNonZeroIncludedLimit") is False or body.get("includedLimitZero") is True:
        return
    line = _mapper.map_grok_bot(body)
    if line is None:
        if body.get("usagePercent") is not None:
            log.get_logger("plugin.cursor").warning(
                "optional Grok Bot usage response contained invalid usage metadata")
        return
    metrics["grokBot"] = line


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    state = _auth.read_state(_auth.db_path(env))
    access = state.get("cursorAuth/accessToken", "")
    refresh = state.get("cursorAuth/refreshToken", "")
    now = env.clock.now()
    if _auth.needs_refresh(access or None, now):
        if refresh:
            try:
                updated = _client.refresh_access_token(env.http, refresh)
                _auth.save_access_token(env, access, updated)
                access = updated
            except model.CollectorError as exc:
                if not access:
                    raise
                log.get_logger("plugin.cursor").warning(
                    "proactive refresh failed; trying stored token: %s", exc.category)
        elif not access:
            raise model.CollectorError("auth", _auth.NOT_LOGGED_IN)
    if not access:
        raise model.CollectorError("auth", _auth.NOT_LOGGED_IN)
    try:
        reply = _client.connect_post(env.http, _client.USAGE_URL, access)
    except _http.HttpError as exc:
        raise _request_failed(exc.status)
    if reply.status in (401, 403):
        if not refresh:
            raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
        updated = _client.refresh_access_token(env.http, refresh)
        _auth.save_access_token(env, access, updated)
        access = updated
        try:
            reply = _client.connect_post(env.http, _client.USAGE_URL, access)
        except _http.HttpError:
            raise model.CollectorError(
                "transport", "Usage request failed after refresh. Try again.")
        if reply.status in (401, 403):
            raise model.CollectorError("auth", _auth.TOKEN_EXPIRED)
    if not 200 <= reply.status < 300:
        raise _request_failed(reply.status)
    usage = _http.parse_json_object(reply.body)
    if usage is None:
        raise model.CollectorError("empty", "Usage response invalid. Try again later.")
    plan_name, plan_missing = _fetch_plan(env, access)
    fallback, message = _mapper.should_fallback(usage, plan_name, plan_missing)
    if fallback:
        summary = _client.optional_rest(env.http, _client.SUMMARY_URL, access)
        request_usage = _client.optional_rest(env.http, _client.REST_USAGE_URL, access)
        metrics, label = _summary.map_summary(summary, request_usage, plan_name, message)
        _append_grok_bot(env, access, metrics)
        return model.Snapshot(
            card=card, plan=label, fetched_at=iso_now(env), metrics=metrics)
    info = _mapper.facts(usage)
    if info["enabled"] and info["hasPlanUsage"] and info["limit"] is None and info["totalPct"] is None:
        try:
            request_usage = _client.optional_rest(env.http, _client.REST_USAGE_URL, access)
            metrics, label = _mapper.map_request_based(
                request_usage, plan_name,
                "Cursor request-based usage data unavailable. Try again later.")
            _append_grok_bot(env, access, metrics)
            return model.Snapshot(
                card=card, plan=label, fetched_at=iso_now(env), metrics=metrics)
        except model.CollectorError:
            log.get_logger("plugin.cursor").warning(
                "optional request-based usage fallback failed")
    grants = _client.optional_connect(env.http, _client.CREDITS_URL, access)
    stripe = _client.optional_rest(env.http, _client.STRIPE_URL, access)
    stripe_cents = 0.0
    if stripe is not None:
        if parse.number(stripe.get("customerBalance")) is None:
            log.get_logger("plugin.cursor").warning(
                "optional prepaid-balance response contained invalid balance metadata")
        stripe_cents = _mapper.stripe_balance_cents(stripe)
    metrics, label = _mapper.map_usage(usage, plan_name, grants, stripe_cents)
    _append_grok_bot(env, access, metrics)
    if not metrics:
        raise model.CollectorError("empty", "Usage response invalid. Try again later.")
    return model.Snapshot(card=card, plan=label, fetched_at=iso_now(env), metrics=metrics)


def attach_spend(card: model.CardRef, env: Env, snap: model.Snapshot,
                 now: Any) -> model.Snapshot:
    """Spend tiles for a quota snapshot. Never raises; quota wins on failure.

    Runs after the quota batch publishes (see engine.refresh.attach_spend).
    Re-reads the access token so rotation between quota and spend is safe.
    """
    # CSV is strictly additive: any failure leaves quota intact.
    try:
        access = _auth.read_state(_auth.db_path(env)).get(
            "cursorAuth/accessToken", "")
        if not access:
            return snap
        session = _auth.session_cookie(access)
        if session is None:
            return snap
        _user, cookie = session
        start, end = _spend_ctx.cursor_window(now)
        url = _csv.csv_url(int(start.timestamp() * 1000), int(end.timestamp() * 1000))
        try:
            reply = env.http.get(
                url, headers={"Cookie": f"WorkosCursorSessionToken={cookie}",
                              "Accept": "text/csv"}, timeout=30)
        except _http.HttpError:
            log.get_logger("plugin.cursor").warning("usage CSV request failed")
            return snap
        if not 200 <= reply.status < 300:
            log.get_logger("plugin.cursor").warning(
                "usage CSV request returned HTTP %s", reply.status)
            return snap
        try:
            text = reply.body.decode("utf-8")
        except UnicodeError:
            log.get_logger("plugin.cursor").warning("usage CSV was not valid UTF-8")
            return snap
        pricing = _spend_ctx.load_pricing(env)
        try:
            rows, rejected = _csv.parse_csv(text, pricing)
        except _csv.CsvError as exc:
            log.get_logger("plugin.cursor").warning("usage CSV invalid: %s", exc)
            return snap
        if rejected:
            log.get_logger("plugin.cursor").warning(
                "usage CSV ignored %d malformed rows", rejected)
        scan = _csv.to_scan_with_pricing(rows, pricing)
        metrics = dict(snap.metrics)
        _tiles.append_token_usage(
            scan.series, metrics, now, estimated=True,
            unknown_by_day=scan.unknown_by_day, model_usage=scan.model_usage,
            model_note=NOTE)
        _tiles.append_trend(scan.series, metrics, now, NOTE)
        return model.Snapshot(card=snap.card, plan=snap.plan,
                              fetched_at=snap.fetched_at, metrics=metrics,
                              error=snap.error)
    except Exception as exc:
        log.get_logger("plugin.cursor").warning("spend scan failed: %s", exc)
        return snap
