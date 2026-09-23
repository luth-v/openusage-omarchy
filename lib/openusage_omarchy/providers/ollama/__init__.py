"""Ollama collector. Cloud plan limits signed with the local Ollama key.

Ollama never auto-enables: the key exists for local-only users too, so
presence cannot tell a Cloud account apart. ``/api/usage`` is required;
``/api/me`` is best-effort (plan name only). Windows carry no reset: Ollama
reports how much is used, never when the window ends, so none is guessed.
"""

from __future__ import annotations

from pathlib import Path

from ... import http as _http, log, model, parse
from ...providers import Env, iso_now
from . import crypto as _crypto

family = "ollama"
LABEL = "Ollama"
HOST = "https://ollama.com"
USAGE_PATH = "/api/usage"
ACCOUNT_PATH = "/api/me"
MISSING_KEY = "No Ollama key found. Install Ollama and run `ollama signin` to track cloud usage."
KEY_UNREADABLE = "Couldn't read ~/.ollama/id_ed25519. Check the file's permissions."
INVALID_KEY = "~/.ollama/id_ed25519 isn't a usable Ollama signing key."
NOT_SIGNED_IN = "Not signed in to Ollama Cloud. Run `ollama signin` to see usage."
CONNECTION_FAILED = "Couldn't reach Ollama. Check your connection."
INVALID_RESPONSE = "Ollama usage data unavailable. Try again later."


def key_path(env: Env) -> Path:
    return env.paths.home / ".ollama" / "id_ed25519"


def load_signing_key(env: Env) -> tuple[bytes, bytes]:
    """(public blob, seed). Raises CollectorError when unusable."""
    path = key_path(env)
    if not path.exists():
        raise model.CollectorError("auth", MISSING_KEY)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        raise model.CollectorError("auth", KEY_UNREADABLE)
    if not text.strip():
        raise model.CollectorError("auth", MISSING_KEY)
    parsed = _crypto.parse_openssh_private_key(text)
    if parsed is None:
        raise model.CollectorError("auth", INVALID_KEY)
    return parsed


def cards(env: Env) -> list[model.CardRef]:
    return [model.CardRef(card_id="ollama", family=family, label=LABEL)]


def has_credentials(env: Env) -> bool:
    # The key cannot tell Cloud from local-only use, so Ollama stays
    # manual: the user turns it on in Customize when they want it.
    return False


def _send(
    env: Env, method: str, path: str, public_blob: bytes, seed: bytes
) -> _http.Response:
    stamp = int(env.clock.now().timestamp())
    uri = f"{path}?ts={stamp}"
    headers = {
        "Authorization": _crypto.authorization(public_blob, seed, method, uri),
        "Accept": "application/json",
    }
    try:
        if method == "POST":
            return env.http.post(HOST + uri, b"", headers=headers, timeout=15)
        return env.http.get(HOST + uri, headers=headers, timeout=15)
    except _http.HttpError as exc:
        if exc.status is not None:
            raise model.CollectorError(
                "status", f"Ollama request failed (HTTP {exc.status}). Try again later.")
        raise model.CollectorError("transport", CONNECTION_FAILED)


def plan_name(body: bytes) -> str | None:
    root = _http.parse_json_object(body)
    if root is None:
        return None
    raw = root.get("Plan", root.get("plan"))
    name = str(raw).strip() if isinstance(raw, str) else ""
    return parse.title_cased(name, lower_tail=True) if name else None


def map_usage(
    usage_body: bytes, account_body: bytes | None
) -> tuple[str | None, dict[str, model.Metric]]:
    """Usage payload plus the optional account payload. May be empty."""
    root = _http.parse_json_object(usage_body)
    if root is None:
        raise ValueError("invalid response")
    limits = root.get("limits")
    if not isinstance(limits, dict):
        raise ValueError("invalid response")
    out: dict[str, model.Metric] = {}
    for field, metric_id in (
        ("session", "session"), ("weekly", "weekly"), ("monthly", "monthly")
    ):
        entry = limits.get(field)
        if not isinstance(entry, dict):
            continue
        fraction = parse.number(entry.get("usage"))
        if fraction is None:
            continue
        out[metric_id] = model.Progress(
            metric_id=metric_id,
            used=parse.clamp_percent(fraction * 100.0), limit=100,
        )
    activity = root.get("activity")
    if isinstance(activity, dict):
        cost = parse.number(activity.get("cost"))
        if cost is not None and cost >= 0:
            out["last4Weeks"] = model.Values(
                metric_id="last4Weeks",
                values=(model.ScalarValue(number=cost, kind="dollars"),),
            )
    return plan_name(account_body) if account_body else None, out


def fetch(card: model.CardRef, env: Env) -> model.Snapshot:
    public_blob, seed = load_signing_key(env)
    usage = _send(env, "GET", USAGE_PATH, public_blob, seed)
    if usage.status in (401, 403):
        raise model.CollectorError("auth", NOT_SIGNED_IN)
    if not 200 <= usage.status < 300:
        raise model.CollectorError(
            "status", f"Ollama request failed (HTTP {usage.status}). Try again later.")
    account_body: bytes | None = None
    try:
        account = _send(env, "POST", ACCOUNT_PATH, public_blob, seed)
    except model.CollectorError as exc:
        log.get_logger("plugin.ollama").warning(
            "ollama plan lookup failed (%s); meters unaffected", exc.category)
    else:
        if 200 <= account.status < 300:
            account_body = account.body
        else:
            log.get_logger("plugin.ollama").warning(
                "ollama plan lookup failed (HTTP %s); meters unaffected",
                account.status,
            )
    try:
        plan, metrics = map_usage(usage.body, account_body)
    except ValueError:
        raise model.CollectorError("empty", INVALID_RESPONSE)
    return model.Snapshot(
        card=card, plan=plan, fetched_at=iso_now(env), metrics=metrics)
