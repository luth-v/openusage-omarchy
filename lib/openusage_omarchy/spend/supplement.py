"""Pricing supplement. Alias rules, fast multipliers, fallback list."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .. import log
from . import price_catalog as _catalog
from .rates import ModelRates


@dataclass
class Supplement:
    pricing: dict[str, ModelRates] = field(default_factory=dict)
    fast_multipliers: dict[str, float] = field(default_factory=dict)
    alias_rules: list[tuple[re.Pattern[str], str]] = field(default_factory=list)
    updated_at: str | None = None
    fallback_models: dict[str, list[str]] = field(default_factory=dict)

    def canonical_name(self, model: str) -> str | None:
        for pattern, target in self.alias_rules:
            try:
                if pattern.search(model):
                    return target
            except re.error:
                continue
        return None

    def fast_multiplier(self, model: str) -> float | None:
        if model in self.fast_multipliers:
            return self.fast_multipliers[model]
        norm = _catalog.normalized_key(model)
        for part in re.split(r"[/:]", norm):
            for base, mult in self.fast_multipliers.items():
                norm_base = _catalog.normalized_key(base)
                idx = part.rfind(norm_base)
                if idx < 0:
                    continue
                tail = part[idx + len(norm_base):]
                if not tail or tail.startswith("-"):
                    return mult
        return None

    def filling_missing_fallbacks(self, other: "Supplement") -> "Supplement":
        merged = dict(other.fallback_models)
        merged.update(self.fallback_models)
        return Supplement(
            pricing=self.pricing, fast_multipliers=self.fast_multipliers,
            alias_rules=self.alias_rules, updated_at=self.updated_at,
            fallback_models=merged)

    @classmethod
    def decode(cls, data: bytes) -> "Supplement":
        raw = json.loads(data.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("supplement is not an object")
        fast = raw.get("fast_multipliers") or {}
        pricing: dict[str, ModelRates] = {}
        for name, entry in (raw.get("pricing") or {}).items():
            if not isinstance(entry, dict):
                continue
            try:
                inp = float(entry["input_per_million"])
                out = float(entry["output_per_million"])
            except (KeyError, TypeError, ValueError):
                continue
            cw = entry.get("cache_write_per_million")
            cr = entry.get("cache_read_per_million")
            pricing[str(name)] = ModelRates(
                input_per_m=inp, output_per_m=out,
                cache_write_per_m=float(cw) if cw is not None else inp,
                cache_read_per_m=float(cr) if cr is not None else inp * 0.1,
                cache_read_explicit=cr is not None,
                fast_multiplier=float(fast.get(name, 1.0) or 1.0),
            )
        rules: list[tuple[re.Pattern[str], str]] = []
        for rule in raw.get("alias_rules") or []:
            if not isinstance(rule, dict):
                continue
            try:
                rules.append((re.compile(str(rule["pattern"])), str(rule["canonical"])))
            except (re.error, KeyError, TypeError):
                log.get_logger("pricing").warning("bad supplement alias skipped")
        fallbacks: dict[str, list[str]] = {}
        for key, items in (raw.get("fallback_models") or {}).items():
            if isinstance(items, list):
                fallbacks[str(key)] = [str(item) for item in items]
        updated = raw.get("updated_at")
        return cls(
            pricing=pricing,
            fast_multipliers={str(k): float(v) for k, v in fast.items()
                              if isinstance(v, (int, float))},
            alias_rules=rules,
            updated_at=str(updated) if updated else None,
            fallback_models=fallbacks)
