"""Per-model rates and token buckets. Ports upstream ModelRates."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TokenBreakdown:
    input: int = 0
    cache_write_5m: int = 0
    cache_write_1h: int = 0
    cache_read: int = 0
    output: int = 0
    is_fast: bool = False

    @property
    def prompt_tokens(self) -> int:
        return self.input + self.cache_write_5m + self.cache_write_1h + self.cache_read

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output


@dataclass(frozen=True)
class ModelRates:
    input_per_m: float = 0.0
    output_per_m: float = 0.0
    cache_write_per_m: float = 0.0
    cache_read_per_m: float = 0.0
    input_above: float | None = None
    output_above: float | None = None
    cache_write_above: float | None = None
    cache_read_above: float | None = None
    cache_read_explicit: bool = True
    long_threshold: int = 200000
    fast_multiplier: float = 1.0

    def scaled(self, factor: float) -> "ModelRates":
        def _scale(value: float | None) -> float | None:
            return None if value is None else value * factor

        return ModelRates(
            input_per_m=self.input_per_m * factor,
            output_per_m=self.output_per_m * factor,
            cache_write_per_m=self.cache_write_per_m * factor,
            cache_read_per_m=self.cache_read_per_m * factor,
            input_above=_scale(self.input_above),
            output_above=_scale(self.output_above),
            cache_write_above=_scale(self.cache_write_above),
            cache_read_above=_scale(self.cache_read_above),
            cache_read_explicit=self.cache_read_explicit,
            long_threshold=self.long_threshold,
            fast_multiplier=1.0,
        )

    def cost_dollars(self, tokens: TokenBreakdown, long_rates: bool = True) -> float:
        mult = self.fast_multiplier if tokens.is_fast else 1.0
        use_long = long_rates and tokens.prompt_tokens > self.long_threshold

        def _pick(base: float, over: float | None) -> float:
            return over if (use_long and over is not None) else base

        write_1h = _pick(self.input_per_m, self.input_above) * 2.0
        total = (
            tokens.input * _pick(self.input_per_m, self.input_above)
            + tokens.output * _pick(self.output_per_m, self.output_above)
            + tokens.cache_write_5m * _pick(self.cache_write_per_m, self.cache_write_above)
            + tokens.cache_write_1h * write_1h
            + tokens.cache_read * _pick(self.cache_read_per_m, self.cache_read_above)
        )
        return total / 1000000.0 * mult
