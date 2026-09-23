"""Copilot org billing. Org-wide credit use for org-managed seats.

Only org owners and billing managers can read org billing; a 403 is the
expected outcome for plain members and yields no lines, never an error.
The matching org slug is remembered in the cache dir so steady-state
refreshes make one extra call. The slug is not a secret and never reaches
state.json. Transient failures (429, 5xx) keep the remembered org.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from ... import http as _http, log, model, parse
from ...providers import Env

ORGS_URL = "https://api.github.com/user/orgs?per_page=100"


def summary_url(org: str) -> str:
    return (
        "https://api.github.com/orgs/" + quote(org, safe="")
        + "/settings/billing/usage/summary"
    )


def org_file(env: Env) -> Path:
    return env.paths.cache_dir / "copilot-org"


def remembered_org(env: Env) -> str | None:
    try:
        return org_file(env).read_text(encoding="utf-8").strip() or None
    except OSError:
        return None


def remember_org(env: Env, org: str) -> None:
    try:
        env.paths.cache_dir.mkdir(parents=True, exist_ok=True)
        org_file(env).write_text(org + "\n", encoding="utf-8")
    except OSError as exc:
        log.get_logger("plugin.copilot").debug("org cache write failed: %s", exc)


def forget_org(env: Env) -> None:
    try:
        org_file(env).unlink(missing_ok=True)
    except OSError:
        pass


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": "token " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


def _get(env: Env, url: str, token: str) -> _http.Response:
    return env.http.get(url, headers=_headers(token), timeout=15)


def org_logins(body: bytes) -> list[str]:
    try:
        found = json.loads(body.decode("utf-8", errors="replace"))
    except ValueError:
        return []
    if not isinstance(found, list):
        return []
    out = []
    for entry in found:
        if isinstance(entry, dict):
            login = str(entry.get("login") or "").strip()
            if login:
                out.append(login)
    return out


def usage_lines(body: bytes) -> dict[str, model.Metric] | None:
    """Billing summary to Org Credits plus Org Spend. None when no items."""
    payload = _http.parse_json_object(body)
    if payload is None:
        return None
    items = payload.get("usageItems")
    if not isinstance(items, list):
        return None
    credits = 0.0
    spend = 0.0
    seen = False
    for item in items:
        if not isinstance(item, dict):
            continue
        product = str(item.get("product") or "").strip().lower()
        unit = str(item.get("unitType") or "").strip().lower()
        if product != "copilot" or unit not in ("ai-units", "ai-credits"):
            continue
        seen = True
        credits += max(0.0, parse.number(item.get("grossQuantity")) or 0.0)
        spend += max(0.0, parse.number(item.get("netAmount")) or 0.0)
    if not seen:
        return None
    return {
        "orgCredits": model.Values(
            metric_id="orgCredits",
            values=(model.ScalarValue(number=credits, kind="count",
                                      label="credits"),),
        ),
        "orgSpend": model.Values(
            metric_id="orgSpend",
            values=(model.ScalarValue(number=spend, kind="dollars"),),
        ),
    }


def _summary_lines(env: Env, org: str, token: str) -> dict[str, model.Metric] | None:
    """One org: lines, None when definitively empty, raises when transient."""
    reply = _get(env, summary_url(org), token)
    if reply.status != 200:
        log.get_logger("plugin.copilot").debug(
            "org billing summary for one org: HTTP %s", reply.status)
        if reply.status == 429 or reply.status >= 500:
            raise _http.HttpError(f"billing summary failed ({reply.status})")
        return None
    return usage_lines(reply.body)


def org_billing_lines(env: Env, token: str) -> dict[str, model.Metric]:
    """Best-effort org lines for an org-managed seat. Never raises."""
    logger = log.get_logger("plugin.copilot")
    cached = remembered_org(env)
    if cached:
        try:
            lines = _summary_lines(env, cached, token)
            if lines is not None:
                return lines
            forget_org(env)
        except _http.HttpError as exc:
            logger.warning("org billing lookup failed for the remembered org: %s", exc)
            return {}
    try:
        reply = _get(env, ORGS_URL, token)
    except _http.HttpError as exc:
        logger.warning("org list fetch failed: %s", exc)
        return {}
    if reply.status != 200:
        logger.info("org list HTTP %s; skipping org billing lookup", reply.status)
        return {}
    for org in org_logins(reply.body):
        try:
            lines = _summary_lines(env, org, token)
        except _http.HttpError as exc:
            logger.warning(
                "org billing summary failed for one org; trying the next: %s", exc)
            continue
        if lines is not None:
            remember_org(env, org)
            return lines
    return {}
