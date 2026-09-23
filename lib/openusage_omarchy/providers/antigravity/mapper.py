"""Antigravity quota mappers. Pure: response bytes to the pool meters.

The quota summary is authoritative: two pools (Gemini as Session/Weekly,
every other model as Claude/Claude Weekly), each with a rolling 5-hour and
a weekly window. Without it, legacy per-model quotas merge into the two
5-hour pools by worst remaining fraction; weekly meters then read no-data.
"""

from __future__ import annotations

import math
import re
from typing import Any

from ... import http as _http, log, model, parse

SESSION_MS = 5 * 60 * 60 * 1000
WEEK_MS = 7 * 24 * 60 * 60 * 1000
SUMMARY: tuple[tuple[str, str, int], ...] = (
    ("gemini-5h", "geminiPro", SESSION_MS),
    ("gemini-weekly", "geminiWeekly", WEEK_MS),
    ("3p-5h", "claude", SESSION_MS),
    ("3p-weekly", "claudeWeekly", WEEK_MS),
)
BLACKLIST = frozenset({
    "MODEL_CHAT_20706", "MODEL_CHAT_23310",
    "MODEL_GOOGLE_GEMINI_2_5_FLASH", "MODEL_GOOGLE_GEMINI_2_5_FLASH_THINKING",
    "MODEL_GOOGLE_GEMINI_2_5_FLASH_LITE", "MODEL_GOOGLE_GEMINI_2_5_PRO",
    "MODEL_PLACEHOLDER_M19", "MODEL_PLACEHOLDER_M9", "MODEL_PLACEHOLDER_M12",
})
_PARENS = re.compile(r"\s*\([^)]*\)\s*$")


def _used(fraction: float) -> float:
    clamped = min(1.0, max(0.0, fraction))
    return float(math.floor((1.0 - clamped) * 100.0 + 0.5))


def _reset(value: Any) -> str | None:
    moment = parse.parse_time(value) if isinstance(value, str) else None
    return moment.isoformat() if moment else None


def parse_quota_summary(body: bytes) -> dict[str, model.Metric] | None:
    """Summary payload to meters. None means not-a-summary (try legacy)."""
    logger = log.get_logger("plugin.antigravity")
    root = _http.parse_json_object(body)
    if root is None:
        return None
    groups: Any = None
    response = root.get("response")
    if isinstance(response, dict) and isinstance(response.get("groups"), list):
        groups = response["groups"]
    elif isinstance(root.get("groups"), list):
        groups = root["groups"]
    if groups is None:
        return None
    for group in groups:
        if not isinstance(group, dict):
            return None
        buckets = group.get("buckets", [])
        if not isinstance(buckets, list):
            return None
    pooled: dict[str, tuple[float, str | None]] = {}
    for group in groups:
        for bucket in group.get("buckets", []):
            if not isinstance(bucket, dict):
                logger.warning("quota summary: skipping a malformed bucket")
                continue
            bucket_id = bucket.get("bucketId")
            if bucket_id not in {spec[0] for spec in SUMMARY}:
                logger.warning(
                    "quota summary: skipping unrecognized bucket id %r", bucket_id)
                continue
            if bucket_id in pooled:
                continue
            fraction = parse.number(bucket.get("remainingFraction"))
            if fraction is None:
                logger.warning(
                    "quota summary: bucket %r has no usable remainingFraction",
                    bucket_id,
                )
                continue
            pooled[str(bucket_id)] = (fraction, _reset(bucket.get("resetTime")))
    out: dict[str, model.Metric] = {}
    for bucket_id, metric_id, period in SUMMARY:
        if bucket_id in pooled:
            fraction, resets_at = pooled[bucket_id]
            out[metric_id] = model.Progress(
                metric_id=metric_id, used=_used(fraction), limit=100,
                resets_at=resets_at, period_ms=period,
            )
    return out


def _quota_config(
    label: Any, model_id: Any, quota: Any
) -> tuple[str, str | None, float, str | None] | None:
    if not isinstance(label, str) or not label.strip():
        return None
    fraction = 0.0
    resets_at: str | None = None
    if isinstance(quota, dict):
        if quota.get("remainingFraction") is not None:
            parsed = parse.number(quota.get("remainingFraction"))
            if parsed is None:
                return None
            fraction = parsed
        resets_at = _reset(quota.get("resetTime"))
    return (
        label.strip(),
        str(model_id).strip() or None if isinstance(model_id, str) else None,
        fraction,
        resets_at,
    )


def _tier_name(tier_name: Any, fallback: Any) -> str | None:
    """Google's own tier first, the inherited Windsurf plan name second."""
    if isinstance(tier_name, str) and tier_name.strip():
        return tier_name
    return fallback if isinstance(fallback, str) else None


def parse_user_status(body: bytes) -> tuple[str | None, list] | None:
    """Language-server GetUserStatus to plan plus model configs."""
    root = _http.parse_json_object(body)
    if root is None:
        return None
    status = root.get("userStatus")
    if not isinstance(status, dict):
        return None
    tier = status.get("userTier")
    tier_name = tier.get("name") if isinstance(tier, dict) else None
    plan_status = status.get("planStatus")
    plan_info = plan_status.get("planInfo") if isinstance(plan_status, dict) else None
    plan_fallback = plan_info.get("planName") if isinstance(plan_info, dict) else None
    plan = format_plan(_tier_name(tier_name, plan_fallback))
    cascade = status.get("cascadeModelConfigData")
    configs = cascade.get("clientModelConfigs") if isinstance(cascade, dict) else []
    if not isinstance(configs, list):
        return None
    out = []
    for entry in configs:
        if not isinstance(entry, dict):
            continue
        alias = entry.get("modelOrAlias")
        model_id = alias.get("model") if isinstance(alias, dict) else None
        config = _quota_config(
            entry.get("label"), model_id, entry.get("quotaInfo"))
        if config is not None:
            out.append(config)
    return plan, out


def parse_command_configs(body: bytes) -> list | None:
    """Language-server GetCommandModelConfigs to model configs."""
    root = _http.parse_json_object(body)
    if root is None:
        return None
    configs = root.get("clientModelConfigs")
    if not isinstance(configs, list):
        return None
    out = []
    for entry in configs:
        if not isinstance(entry, dict):
            continue
        alias = entry.get("modelOrAlias")
        model_id = alias.get("model") if isinstance(alias, dict) else None
        config = _quota_config(
            entry.get("label"), model_id, entry.get("quotaInfo"))
        if config is not None:
            out.append(config)
    return out


def parse_cloud_models(body: bytes) -> list:
    """Cloud Code fetchAvailableModels to model configs."""
    root = _http.parse_json_object(body)
    if root is None:
        return []
    found = root.get("models")
    if not isinstance(found, dict):
        return []
    out = []
    for key, item in found.items():
        if not isinstance(item, dict) or item.get("isInternal") is True:
            continue
        label = item.get("displayName") or item.get("label")
        config = _quota_config(
            label, item.get("model") or key, item.get("quotaInfo"))
        if config is not None:
            out.append(config)
    return out


def parse_quota_buckets(body: bytes) -> list:
    """Cloud Code retrieveUserQuota to model configs."""
    root = _http.parse_json_object(body)
    if root is None:
        return []
    buckets = root.get("buckets")
    if not isinstance(buckets, list):
        return []
    out = []
    for bucket in buckets:
        if not isinstance(bucket, dict):
            continue
        model_id = bucket.get("modelId")
        if not isinstance(model_id, str) or not model_id.strip():
            continue
        fraction = parse.number(bucket.get("remainingFraction"))
        out.append((
            model_id.strip(), model_id.strip(),
            fraction if fraction is not None else 0.0,
            _reset(bucket.get("resetTime")),
        ))
    return out


def parse_plan(body: bytes) -> str | None:
    root = _http.parse_json_object(body)
    if root is None:
        return None
    paid = root.get("paidTier")
    current = root.get("currentTier")
    paid_name = paid.get("name") if isinstance(paid, dict) else None
    current_name = current.get("name") if isinstance(current, dict) else None
    name = paid_name if isinstance(paid_name, str) else None
    if name is None and isinstance(current_name, str):
        name = current_name
    return format_plan(name)


def parse_project(body: bytes) -> str | None:
    root = _http.parse_json_object(body)
    if root is None:
        return None
    project = root.get("cloudaicompanionProject")
    if isinstance(project, str) and project.strip():
        return project.strip()
    return None


def normalize_label(label: str) -> str:
    return _PARENS.sub("", label).strip()


def pool_metric(label: str) -> str:
    return "geminiPro" if "gemini" in label.lower() else "claude"


def build_lines(configs: list) -> dict[str, model.Metric]:
    """Model configs to the two 5-hour pool meters (worst fraction wins)."""
    pooled: dict[str, tuple[float, str | None]] = {}
    for label, model_id, fraction, resets_at in configs:
        clean = str(label).strip()
        if not clean:
            continue
        if model_id is not None and model_id in BLACKLIST:
            continue
        pool = pool_metric(normalize_label(clean))
        if pool not in pooled or fraction < pooled[pool][0]:
            pooled[pool] = (fraction, resets_at)
    out: dict[str, model.Metric] = {}
    for pool in ("geminiPro", "claude"):
        if pool in pooled:
            fraction, resets_at = pooled[pool]
            out[pool] = model.Progress(
                metric_id=pool, used=_used(fraction), limit=100,
                resets_at=resets_at, period_ms=SESSION_MS,
            )
    return out


def format_plan(raw: str | None) -> str | None:
    if not isinstance(raw, str):
        return None
    trimmed = raw.strip()
    if not trimmed:
        return None
    if trimmed.startswith("Google AI "):
        return parse.title_cased(trimmed[len("Google AI "):])
    lowered = trimmed.lower()
    for keyword in ("Ultra", "Pro", "Free"):
        if keyword.lower() in lowered:
            return keyword
    return parse.title_cased(trimmed)
