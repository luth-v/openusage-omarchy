"""OpenRouter collector. Credit balance and spend from the account API key.

The key comes from the plugin key store (keyring, fallback file, or env);
upstream's ``~/.config/openusage/`` files are never read (forbidden path).
``/credits`` and ``/key`` map independently: either endpoint may fail while
the other still renders. Period spend is API-reported, so $0.00 is measured.
"""

from __future__ import annotations

from typing import Any

from .. import http as _http, model, parse, secrets
from ..providers import Env, iso_now

family = "openrouter"
LABEL = "OpenRouter"
CREDITS_URL = "https://openrouter.ai/api/v1/credits"
KEY_URL = "https://openrouter.ai/api/v1/key"
MISSING_KEY = "No OpenRouter API key. Set OPENROUTER_API_KEY or add it in Settings → API Keys."
INVALID_KEY = "OpenRouter API key invalid. Check your key at openrouter.ai/keys."
CONNECTION_FAILED = "Couldn't reach OpenRouter. Check your connection."
INVALID_RESPONSE = "OpenRouter usage data unavailable. Try again later."


def _headers(key: str) -> dict[str, str]:
    return {"Authorization": "Bearer " + key, "Accept": "application/json"}


def _get(env: Env, url: str, key: str) -> _http.Response:
    try:
        return env.http.get(url, headers=_headers(key), timeout=15)
    except _http.HttpError as exc:
        if exc.status is not None:
            raise model.CollectorError(
                "status", f"OpenRouter request failed (HTTP {exc.status}).")
        raise model.CollectorError("transport", CONNECTION_FAILED)


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="openrouter", family=family, label=LABEL)]


def has_credentials(env: Env) -> bool:
    return secrets.get_key("openrouter", env.paths) is not None


def data_object(body: bytes) -> dict[str, Any] | None:
    """OpenRouter wraps every payload in ``{"data": {...}}``."""
    payload = _http.parse_json_object(body)
    if payload is None:
        return None
    data = payload.get("data")
    return data if isinstance(data, dict) else None


def credits_lines(data: dict[str, Any]) -> dict[str, model.Metric]:
    """Credits meter plus Balance from ``/credits``."""
    total_usage = parse.number(data.get("total_usage"))
    if total_usage is None:
        return {}
    used = max(0.0, total_usage)
    total_credits = max(0.0, parse.number(data.get("total_credits")) or 0.0)
    out: dict[str, model.Metric] = {}
    if total_credits > 0:
        out["credits"] = model.Progress(
            metric_id="credits", used=used, limit=total_credits,
            format_kind="dollars",
        )
    out["balance"] = model.Values(
        metric_id="balance",
        values=(model.ScalarValue(number=max(0.0, total_credits - used),
                                  kind="dollars"),),
    )
    return out


def key_metrics(data: dict[str, Any]) -> tuple[str | None, dict[str, model.Metric]]:
    """Period spend plus the optional per-key cap from ``/key``."""
    out: dict[str, model.Metric] = {}
    for field, metric_id in (
        ("usage_daily", "today"), ("usage_weekly", "week"),
        ("usage_monthly", "month"),
    ):
        amount = parse.number(data.get(field))
        if amount is not None:
            out[metric_id] = model.Values(
                metric_id=metric_id,
                values=(model.ScalarValue(number=max(0.0, amount),
                                          kind="dollars"),),
            )
    limit = parse.number(data.get("limit"))
    if limit is not None and limit > 0:
        remaining = max(0.0, parse.number(data.get("limit_remaining")) or 0.0)
        out["keyLimit"] = model.Progress(
            metric_id="keyLimit", used=max(0.0, limit - remaining),
            limit=limit, format_kind="dollars",
        )
    free = data.get("is_free_tier")
    plan = None if not isinstance(free, bool) else ("Free tier" if free else "Pay as you go")
    return plan, out


def _load(env: Env, url: str, key: str) -> tuple[dict | None, str | None]:
    """One endpoint: (data, None), (None, "auth"), or raises CollectorError."""
    reply = _get(env, url, key)
    if reply.status in (401, 403):
        return None, "auth"
    if not 200 <= reply.status < 300:
        raise model.CollectorError(
            "status", f"OpenRouter request failed (HTTP {reply.status}).")
    data = data_object(reply.body)
    if data is None:
        raise model.CollectorError("empty", INVALID_RESPONSE)
    return data, None


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    key = secrets.get_key("openrouter", env.paths)
    if not key:
        raise model.CollectorError("auth", MISSING_KEY)
    try:
        credits, credits_auth = _load(env, CREDITS_URL, key)
    except model.CollectorError as exc:
        credits, credits_auth, credits_error = None, None, exc
    else:
        credits_error = None
    try:
        key_data, key_auth = _load(env, KEY_URL, key)
    except model.CollectorError as exc:
        key_data, key_auth, key_error = None, None, exc
    else:
        key_error = None
    metrics: dict[str, model.Metric] = {}
    plan: str | None = None
    if credits is not None:
        metrics.update(credits_lines(credits))
    if key_data is not None:
        plan, keyed = key_metrics(key_data)
        metrics.update(keyed)
    if metrics:
        return model.Snapshot(
            card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
    if credits_auth == "auth" and key_auth == "auth":
        raise model.CollectorError("auth", INVALID_KEY)
    error = credits_error or key_error
    if error is not None:
        raise error
    raise model.CollectorError("empty", INVALID_RESPONSE)
