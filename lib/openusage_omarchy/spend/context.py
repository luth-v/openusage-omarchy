"""Spend wiring helpers. Pricing plus scan window, one place."""

from __future__ import annotations

import datetime as dt

from ..providers import Env
from . import jsonl as _jsonl
from .pricing import EMPTY, ModelPricing, fallback_title
from .pricing_store import Store


def since_ts(env: Env, days_back: int = 30) -> float:
    now = env.clock.now()
    return _jsonl.since_date(days_back, now).timestamp()


def load_pricing(env: Env) -> ModelPricing:
    try:
        store = Store(env.paths.pricing_dir, env.http)
        return store.current()
    except Exception:
        return EMPTY


def pricing_info(env: Env) -> tuple[str, str | None]:
    try:
        return Store(env.paths.pricing_dir, env.http).source_info()
    except Exception:
        return "bundled", None


def cursor_window(now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    local = now.astimezone() if now.tzinfo else now
    start_today = local.replace(hour=0, minute=0, second=0, microsecond=0)
    start = start_today - dt.timedelta(days=29)
    return start, now


def codex_options(env: Env) -> list[dict[str, str]]:
    """Priced fallback models for the Customize picker. Never raises."""
    try:
        pricing = load_pricing(env)
    except Exception:
        return []
    try:
        names = pricing.fallback_options("codex")
    except Exception:
        return []
    return [{"id": name, "title": fallback_title(name)} for name in names]


def fallback_setting(env: Env) -> str:
    """The shell.json codexFallbackModel choice, or "" for None."""
    settings = getattr(env, "settings", None)
    if settings is None:
        return ""
    try:
        value = settings.get("codexFallbackModel", "")
    except Exception:
        return ""
    return value.strip() if isinstance(value, str) else ""
