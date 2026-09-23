"""Pricing catalogs. Exact plus ccusage fuzzy match, and feed codecs."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from .rates import ModelRates


def normalized_key(value: str) -> str:
    if "." in value or "@" in value:
        return value.replace(".", "-").replace("@", "-")
    return value


def _is_alnum(byte: int) -> bool:
    return (48 <= byte <= 57) or (97 <= byte <= 122) or (65 <= byte <= 90)


def contains_key(value: str, key: str) -> bool:
    if not key:
        return False
    vb, kb = value.encode(), key.encode()
    if len(kb) > len(vb):
        return False
    for start in range(len(vb) - len(kb) + 1):
        if vb[start:start + len(kb)] != kb:
            continue
        if start > 0 and _is_alnum(vb[start - 1]):
            continue
        suffix = vb[start + len(kb):]
        if not suffix:
            return True
        if _is_alnum(suffix[0]):
            continue
        if kb[-1:].isdigit() and suffix[:1] in (b"-", b"."):
            rest = suffix[1:]
            digits = 0
            while digits < len(rest) and 48 <= rest[digits] <= 57:
                digits += 1
            if digits > 0:
                after = rest[digits:digits + 1]
                is_date = digits == 8 and (not after or not _is_alnum(after[0]))
                if not is_date:
                    continue
        return True
    return False


def key_matches(candidate: str, model: str, norm_model: str) -> bool:
    if contains_key(model, candidate) or contains_key(candidate, model):
        return True
    norm_cand = normalized_key(candidate)
    return contains_key(norm_model, norm_cand) or contains_key(norm_cand, norm_model)


@dataclass
class PricingCatalog:
    entries: dict[str, ModelRates] = field(default_factory=dict)
    retrieved_at: str | None = None

    def find_exact(self, name: str) -> tuple[str, ModelRates] | None:
        rates = self.entries.get(name)
        return (name, rates) if rates is not None else None

    def find_fuzzy(self, name: str) -> tuple[str, ModelRates] | None:
        norm = normalized_key(name)
        best: tuple[str, ModelRates] | None = None
        for key, rates in self.entries.items():
            if not key_matches(key, name, norm):
                continue
            if best is None or len(key) > len(best[0]) or (
                    len(key) == len(best[0]) and key < best[0]):
                best = (key, rates)
        return best

    def merging(self, other: "PricingCatalog") -> "PricingCatalog":
        merged = dict(self.entries)
        merged.update(other.entries)
        return PricingCatalog(entries=merged,
                              retrieved_at=other.retrieved_at or self.retrieved_at)


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
        return result if result == result and abs(result) != float("inf") else None
    return None


def catalog_from_litellm(data: bytes) -> PricingCatalog:
    root = json.loads(data.decode("utf-8"))
    if not isinstance(root, dict):
        raise ValueError("LiteLLM feed is not an object")
    entries: dict[str, ModelRates] = {}
    for key, value in root.items():
        if not isinstance(value, dict):
            continue
        inp = _num(value.get("input_cost_per_token"))
        out = _num(value.get("output_cost_per_token"))
        if inp is None or out is None:
            continue
        cw = _num(value.get("cache_creation_input_token_cost"))
        cr = _num(value.get("cache_read_input_token_cost"))
        rates = ModelRates(
            input_per_m=inp * 1000000, output_per_m=out * 1000000,
            cache_write_per_m=(cw if cw is not None else inp) * 1000000,
            cache_read_per_m=(cr if cr is not None else inp * 0.1) * 1000000,
            cache_read_explicit=cr is not None,
            input_above=_above(value, "input_cost_per_token_above_200k_tokens"),
            output_above=_above(value, "output_cost_per_token_above_200k_tokens"),
            cache_write_above=_above(value, "cache_creation_input_token_cost_above_200k_tokens"),
            cache_read_above=_above(value, "cache_read_input_token_cost_above_200k_tokens"),
        )
        provider = value.get("provider_specific_entry")
        if isinstance(provider, dict):
            fast = _num(provider.get("fast"))
            if fast is not None:
                rates = ModelRates(
                    input_per_m=rates.input_per_m, output_per_m=rates.output_per_m,
                    cache_write_per_m=rates.cache_write_per_m,
                    cache_read_per_m=rates.cache_read_per_m,
                    input_above=rates.input_above, output_above=rates.output_above,
                    cache_write_above=rates.cache_write_above,
                    cache_read_above=rates.cache_read_above,
                    cache_read_explicit=rates.cache_read_explicit,
                    long_threshold=rates.long_threshold, fast_multiplier=fast)
        entries[str(key)] = rates
    if not entries:
        raise ValueError("LiteLLM feed has no usable entries")
    return PricingCatalog(entries=entries)


def _above(entry: dict, name: str) -> float | None:
    value = _num(entry.get(name))
    return None if value is None else value * 1000000


def catalog_from_modelsdev(data: bytes) -> PricingCatalog:
    root = json.loads(data.decode("utf-8"))
    if not isinstance(root, dict):
        raise ValueError("models.dev feed is not an object")
    entries: dict[str, ModelRates] = {}
    for provider in sorted(root):
        block = root[provider]
        if not isinstance(block, dict):
            continue
        models = block.get("models")
        if not isinstance(models, dict):
            continue
        for model_id, spec in models.items():
            if model_id in entries or not isinstance(spec, dict):
                continue
            cost = spec.get("cost")
            if not isinstance(cost, dict):
                continue
            inp = _num(cost.get("input"))
            out = _num(cost.get("output"))
            if inp is None or out is None:
                continue
            cw = _num(cost.get("cache_write"))
            cr = _num(cost.get("cache_read"))
            entries[str(model_id)] = ModelRates(
                input_per_m=inp, output_per_m=out,
                cache_write_per_m=cw if cw is not None else inp,
                cache_read_per_m=cr if cr is not None else inp * 0.1,
                cache_read_explicit="cache_read" in cost)
    if not entries:
        raise ValueError("models.dev feed has no usable entries")
    return PricingCatalog(entries=entries)


def catalog_from_compact(data: bytes) -> PricingCatalog:
    raw = json.loads(data.decode("utf-8"))
    models = raw.get("models") if isinstance(raw, dict) else None
    if not isinstance(models, dict):
        raise ValueError("compact catalog is not an object")
    entries: dict[str, ModelRates] = {}
    for key, spec in models.items():
        if not isinstance(spec, dict):
            continue
        try:
            entries[str(key)] = ModelRates(
                input_per_m=float(spec["i"]), output_per_m=float(spec["o"]),
                cache_write_per_m=float(spec["cw"]), cache_read_per_m=float(spec["cr"]),
                input_above=spec.get("ia"), output_above=spec.get("oa"),
                cache_write_above=spec.get("cwa"), cache_read_above=spec.get("cra"),
                cache_read_explicit=spec.get("cre", True) is not False,
                fast_multiplier=float(spec.get("fast", 1.0) or 1.0))
        except (KeyError, TypeError, ValueError):
            continue
    retrieved = raw.get("retrieved_at") if isinstance(raw, dict) else None
    return PricingCatalog(entries=entries,
                          retrieved_at=str(retrieved) if retrieved else None)


def compact_data(catalog: PricingCatalog) -> bytes:
    models: dict[str, dict[str, Any]] = {}
    for key, rates in catalog.entries.items():
        spec: dict[str, Any] = {
            "i": rates.input_per_m, "o": rates.output_per_m,
            "cw": rates.cache_write_per_m, "cr": rates.cache_read_per_m}
        if rates.input_above is not None:
            spec["ia"] = rates.input_above
        if rates.output_above is not None:
            spec["oa"] = rates.output_above
        if rates.cache_write_above is not None:
            spec["cwa"] = rates.cache_write_above
        if rates.cache_read_above is not None:
            spec["cra"] = rates.cache_read_above
        if not rates.cache_read_explicit:
            spec["cre"] = False
        if rates.fast_multiplier != 1.0:
            spec["fast"] = rates.fast_multiplier
        models[key] = spec
    payload = {"retrieved_at": catalog.retrieved_at, "models": models}
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode()
