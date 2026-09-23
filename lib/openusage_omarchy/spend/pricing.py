"""Layered model pricing. Supplement wins, then LiteLLM, then models.dev."""

from __future__ import annotations

from .price_catalog import PricingCatalog
from .rates import ModelRates, TokenBreakdown
from .supplement import Supplement


class ModelPricing:
    """Immutable snapshot for one scan pass."""

    def __init__(self, supplement: Supplement, primary: PricingCatalog,
                 secondary: PricingCatalog) -> None:
        self.supplement = supplement
        self.primary = primary
        self.secondary = secondary
        self._memo: dict[str, ModelRates | None] = {}
        self._canon: dict[str, str] = {}

    def resolve(self, model: str) -> ModelRates | None:
        if model in self._memo:
            return self._memo[model]
        found = self._resolve_uncached(model)
        self._memo[model] = found
        return found

    def canonical_name(self, model: str) -> str:
        if model not in self._canon:
            self._canon[model] = self.supplement.canonical_name(model) or model
        return self._canon[model]

    def family_name(self, model: str, suffixes: list[str]) -> str:
        canon = self.canonical_name(model)
        for suffix in suffixes:
            if canon.endswith(suffix) and len(canon) > len(suffix):
                return canon[:-len(suffix)]
        return canon

    def estimated_cost(self, model: str, tokens: TokenBreakdown,
                       long_rates: bool = True) -> float | None:
        rates = self.resolve(model)
        if rates is None:
            return None
        return rates.cost_dollars(tokens, long_rates)

    def fallback_rates(self, model: str, provider: str) -> ModelRates | None:
        allowed = self.supplement.fallback_models.get(provider) or []
        if model not in allowed:
            return None
        rates = (self.supplement.pricing.get(model)
                 or (self.primary.find_exact(model) or (None, None))[1]
                 or (self.secondary.find_exact(model) or (None, None))[1])
        if rates is None:
            return None
        if not (rates.input_per_m > 0 and rates.output_per_m >= 0
                and rates.cache_read_per_m >= 0):
            return None
        return rates

    def fallback_options(self, provider: str) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for name in self.supplement.fallback_models.get(provider) or []:
            if name in seen:
                continue
            seen.add(name)
            if self.fallback_rates(name, provider) is not None:
                out.append(name)
        return out

    def _resolve_uncached(self, model: str) -> ModelRates | None:
        canon = self.supplement.canonical_name(model)
        if canon is not None and canon != model:
            return self._lookup(canon) or self._lookup(model)
        return self._lookup(model)

    def _lookup(self, name: str) -> ModelRates | None:
        if name in self.supplement.pricing:
            return self.supplement.pricing[name]
        exact = self.primary.find_exact(name)
        if exact is not None:
            return exact[1]
        fast = self._fast_variant(name)
        if fast is not None:
            return fast
        if name.endswith("-fast"):
            hit = self.secondary.find_exact(name)
            return hit[1] if hit else None
        fuzzy = self.primary.find_fuzzy(name)
        if fuzzy is not None:
            return fuzzy[1]
        hit = self.secondary.find_exact(name)
        return hit[1] if hit else None

    def _fast_variant(self, name: str) -> ModelRates | None:
        if not name.endswith("-fast"):
            return None
        base = name[:-5]
        if not base:
            return None
        entry = None
        if base in self.supplement.pricing:
            entry = (base, self.supplement.pricing[base])
        else:
            entry = (self.primary.find_exact(base) or self.primary.find_fuzzy(base)
                     or self.secondary.find_exact(base))
        if entry is None:
            return None
        key, rates = entry
        mult = rates.fast_multiplier
        if mult == 1.0:
            mult = (self.supplement.fast_multiplier(key)
                    or self.supplement.fast_multiplier(base) or 1.0)
            if mult == 1.0:
                return None
        return rates.scaled(mult)


def fallback_title(model: str) -> str:
    """Picker title. Ports PricingFallbackOption.title (gpt to GPT)."""
    words = []
    for part in str(model).split("-"):
        if part == "gpt":
            words.append("GPT")
        elif part in ("o1", "o3", "o4"):
            words.append(part)
        elif part:
            words.append(part[:1].upper() + part[1:])
    return " ".join(words) or str(model)


EMPTY = ModelPricing(Supplement(), PricingCatalog(), PricingCatalog())
