"""Codex request pricing. Long-context, cache, and priority rules."""

from __future__ import annotations

from dataclasses import dataclass

from .pricing import ModelPricing
from .rates import ModelRates, TokenBreakdown


@dataclass(frozen=True)
class Prepared:
    rates: ModelRates
    fast_tier: bool


def dated_base(model: str) -> str:
    for pattern in ("-dddd-dd-dd", "-dddddddd"):
        if len(model) <= len(pattern):
            continue
        suffix = model[-len(pattern):]
        ok = all(
            char.isdigit() if token == "d" else char == token
            for char, token in zip(suffix, pattern))
        if ok:
            return model[:-len(pattern)]
    return model


def _long_rates(base: str) -> tuple[float, float, float] | None:
    table = {
        "gpt-5.4": (5, 22.5, 0.5),
        "gpt-5.4-pro": (60, 270, 60),
        "gpt-5.5": (10, 45, 1),
        "gpt-5.5-pro": (60, 270, 60),
        "gpt-5.6-sol": (10, 45, 1),
        "gpt-5.6-terra": (4, 18, 0.4),
        "gpt-5.6-luna": (0.4, 1.8, 0.04),
        "gpt-6-astra": (20, 75, 2),
    }
    return table.get(base)


def _no_discount(base: str) -> bool:
    return base in ("gpt-5.4-pro", "gpt-5.5-pro")


def priority_multiplier(model: str, rates: ModelRates) -> float:
    base = dated_base(model)
    if base in ("gpt-5.5", "gpt-5.5-pro"):
        return 2.5
    if base in ("gpt-5.4", "gpt-5.4-pro", "gpt-5.6-sol", "gpt-5.6-terra",
                "gpt-5.6-luna", "gpt-6-astra"):
        return 2.0
    return 2.0 if rates.fast_multiplier == 1.0 else rates.fast_multiplier


def _adjusted(rates: ModelRates, model: str) -> ModelRates:
    base = dated_base(model)
    long = _long_rates(base)
    threshold = 272000 if long else rates.long_threshold
    above_in = long[0] if long else rates.input_above
    above_out = long[1] if long else rates.output_above
    above_read = long[2] if long else rates.cache_read_above
    if _no_discount(base) or not rates.cache_read_explicit:
        read = rates.input_per_m
        read_above = above_in
    else:
        read = rates.cache_read_per_m
        read_above = above_read
    return ModelRates(
        input_per_m=rates.input_per_m, output_per_m=rates.output_per_m,
        cache_write_per_m=rates.cache_write_per_m, cache_read_per_m=read,
        input_above=above_in, output_above=above_out,
        cache_write_above=rates.cache_write_above,
        cache_read_above=read_above,
        cache_read_explicit=rates.cache_read_explicit,
        long_threshold=threshold,
        fast_multiplier=priority_multiplier(model, rates))


def resolve_rates(pricing: ModelPricing, model: str
                  ) -> tuple[ModelRates | None, str, bool, bool]:
    canon = pricing.canonical_name(model)
    fast_alias = canon.endswith("-fast")
    base = canon[:-5] if fast_alias else canon
    found = pricing.resolve(base)
    rates = found or pricing.resolve(model)
    return rates, base, fast_alias, found is not None


def prepare(pricing: ModelPricing, model: str) -> Prepared | None:
    rates, base, fast_alias, has_base = resolve_rates(pricing, model)
    if rates is None:
        return None
    return Prepared(rates=_adjusted(rates, base),
                    fast_tier=fast_alias and has_base)


def cost_prepared(prepared: Prepared, tokens: TokenBreakdown) -> float:
    priced = TokenBreakdown(
        input=tokens.input, cache_write_5m=tokens.cache_write_5m,
        cache_write_1h=tokens.cache_write_1h, cache_read=tokens.cache_read,
        output=tokens.output, is_fast=prepared.fast_tier)
    return prepared.rates.cost_dollars(priced)


def cost_rates(rates: ModelRates, tokens: TokenBreakdown,
               model: str, fast_tier: bool) -> float:
    return cost_prepared(Prepared(rates=_adjusted(rates, model), fast_tier=fast_tier),
                         tokens)


def estimated_cost(pricing: ModelPricing, model: str,
                   tokens: TokenBreakdown) -> float | None:
    prepared = prepare(pricing, model)
    if prepared is None:
        return None
    return cost_prepared(prepared, tokens)
