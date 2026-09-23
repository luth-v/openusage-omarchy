"""The single metric vocabulary. Read by Python; QML reads catalog.json too."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from . import CATALOG_SCHEMA, log, model

ORDER = (
    "claude",
    "codex",
    "cursor",
    "antigravity",
    "copilot",
    "devin",
    "grok",
    "ollama",
    "opencode",
    "openrouter",
    "zai",
)


@dataclass(frozen=True)
class MetricDef:
    metric_id: str
    label: str
    metric_label: str
    kind: str
    starrable: bool
    placement: str
    default_star: bool
    default_on: bool
    api_resources: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProviderDef:
    provider_id: str
    display_name: str
    mark: str
    auto_enable: bool
    spend: bool = False
    links: tuple[dict[str, str], ...] = ()
    metrics: tuple[MetricDef, ...] = field(default_factory=tuple)

    def metric(self, metric_id: str) -> MetricDef | None:
        for item in self.metrics:
            if item.metric_id == metric_id:
                return item
        return None


@dataclass(frozen=True)
class Catalog:
    providers: tuple[ProviderDef, ...] = ()

    def provider(self, provider_id: str) -> ProviderDef | None:
        for item in self.providers:
            if item.provider_id == provider_id:
                return item
        return None

    def families(self) -> list[str]:
        return [item.provider_id for item in self.providers]

    def spend_families(self) -> set[str]:
        return {item.provider_id for item in self.providers if item.spend}


def plugin_root() -> Path:
    return Path(__file__).resolve().parent.parent.parent


def catalog_path() -> Path:
    return plugin_root() / "catalog.json"


def manifest_path() -> Path:
    return plugin_root() / "manifest.json"


def load(path: Path | None = None) -> Catalog:
    raw = json.loads((path or catalog_path()).read_text(encoding="utf-8"))
    if raw.get("schema") != CATALOG_SCHEMA:
        raise ValueError(f"bad catalog schema: {raw.get('schema')!r}")
    providers = []
    for entry in raw.get("providers", []):
        metrics = []
        for item in entry.get("metrics", []):
            resources = item.get("apiResource")
            if resources is None:
                keys: tuple[str, ...] = ()
            elif isinstance(resources, str):
                keys = (resources,)
            else:
                keys = tuple(resources)
            metrics.append(
                MetricDef(
                    metric_id=str(item["id"]),
                    label=str(item["label"]),
                    metric_label=str(item.get("metricLabel", item["label"])),
                    kind=str(item["kind"]),
                    starrable=bool(item["starrable"]),
                    placement=str(item["placement"]),
                    default_star=bool(item["defaultStar"]),
                    default_on=bool(item.get("defaultOn", True)),
                    api_resources=keys,
                )
            )
        providers.append(
            ProviderDef(
                provider_id=str(entry["id"]),
                display_name=str(entry["displayName"]),
                mark=str(entry.get("mark", "")),
                auto_enable=bool(entry.get("autoEnable", True)),
                spend=bool(entry.get("spend", False)),
                links=tuple(entry.get("links", [])),
                metrics=tuple(metrics),
            )
        )
    found = [item.provider_id for item in providers]
    if found != list(ORDER):
        raise ValueError(f"catalog order drift: {found}")
    return Catalog(providers=tuple(providers))


def check_snapshot(snapshot: model.Snapshot,
                   table: Catalog | None = None) -> model.Snapshot:
    """Drop metrics missing from the catalog before they reach cache or views."""
    provider = (table or cached()).provider(snapshot.card.family)
    known = {item.metric_id for item in provider.metrics} if provider else set()
    kept = {key: metric for key, metric in snapshot.metrics.items() if key in known}
    unknown = set(snapshot.metrics) - set(kept)
    if unknown:
        log.get_logger("catalog").warning(
            "%s emitted unknown metric ids: %s", snapshot.card.family,
            ",".join(sorted(unknown)))
    if not unknown:
        return snapshot
    return model.Snapshot(card=snapshot.card, plan=snapshot.plan,
                          fetched_at=snapshot.fetched_at, metrics=kept,
                          error=snapshot.error)


@lru_cache(maxsize=1)
def cached() -> Catalog:
    return load()


def manifest_defaults(path: Path | None = None) -> dict:
    raw = json.loads((path or manifest_path()).read_text(encoding="utf-8"))
    widget = raw.get("barWidget") or {}
    defaults = widget.get("defaults") or {}
    return dict(defaults) if isinstance(defaults, dict) else {}


def manifest_version(path: Path | None = None) -> str:
    raw = json.loads((path or manifest_path()).read_text(encoding="utf-8"))
    return str(raw.get("version", ""))
