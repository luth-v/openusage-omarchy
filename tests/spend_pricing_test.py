"""Pricing layers: rates, fuzzy match, supplement, codecs, store."""

import json
import re
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy.spend import price_catalog as _cat
from openusage_omarchy.spend import pricing as _pricing
from openusage_omarchy.spend import pricing_store as _store
from openusage_omarchy.spend import supplement as _supp
from openusage_omarchy.spend.rates import ModelRates, TokenBreakdown

import support


def _rates(**kwargs):
    base = {"input_per_m": 1.0, "output_per_m": 2.0,
            "cache_write_per_m": 1.0, "cache_read_per_m": 0.1}
    base.update(kwargs)
    return ModelRates(**base)


class RatesTest(unittest.TestCase):
    def test_buckets_and_1h_double(self):
        rates = _rates()
        tokens = TokenBreakdown(input=1_000_000, cache_write_5m=500_000,
                                cache_write_1h=500_000, cache_read=1_000_000,
                                output=1_000_000)
        # 1 + 0.5 + (0.5*2) + 0.1 + 2 = 4.6
        self.assertAlmostEqual(rates.cost_dollars(tokens), 4.6)

    def test_long_context_whole_request(self):
        rates = _rates(input_above=10.0, output_above=20.0, long_threshold=200_000)
        small = TokenBreakdown(input=1000, output=1000)
        self.assertAlmostEqual(small and rates.cost_dollars(small), 0.003)
        big = TokenBreakdown(input=300_000, output=1000)
        self.assertAlmostEqual(rates.cost_dollars(big), 3.02)

    def test_fast_multiplier(self):
        rates = _rates(fast_multiplier=2.0)
        tokens = TokenBreakdown(input=1_000_000, is_fast=True)
        self.assertAlmostEqual(rates.cost_dollars(tokens), 2.0)
        plain = TokenBreakdown(input=1_000_000)
        self.assertAlmostEqual(rates.cost_dollars(plain), 1.0)

    def test_scaled(self):
        scaled = _rates().scaled(2.0)
        self.assertEqual(scaled.input_per_m, 2.0)
        self.assertEqual(scaled.fast_multiplier, 1.0)


class CatalogTest(unittest.TestCase):
    def test_exact_wins(self):
        catalog = _cat.PricingCatalog(entries={"a": _rates(), "ab": _rates()})
        self.assertEqual(catalog.find_exact("a")[0], "a")

    def test_fuzzy_prefix_and_separator(self):
        catalog = _cat.PricingCatalog(entries={"grok-4-3": _rates()})
        self.assertIsNotNone(catalog.find_fuzzy("xai/grok-4.3"))

    def test_fuzzy_rejects_numeric_version(self):
        catalog = _cat.PricingCatalog(entries={"claude-sonnet-4-5": _rates()})
        self.assertIsNone(catalog.find_fuzzy("claude-sonnet-4"))

    def test_fuzzy_allows_date_suffix(self):
        catalog = _cat.PricingCatalog(entries={"claude-sonnet-4-20250514": _rates()})
        self.assertIsNotNone(catalog.find_fuzzy("claude-sonnet-4"))

    def test_merge_other_wins(self):
        base = _cat.PricingCatalog(entries={"a": _rates(input_per_m=1.0)})
        over = _cat.PricingCatalog(entries={"a": _rates(input_per_m=9.0)})
        self.assertEqual(base.merging(over).entries["a"].input_per_m, 9.0)


class SupplementTest(unittest.TestCase):
    def test_decode_and_alias(self):
        payload = {
            "updated_at": "2026-09-23T00:00:00Z",
            "pricing": {"test-only-model": {"input_per_million": 1.0,
                                            "output_per_million": 2.0}},
            "fast_multipliers": {"test-only-model": 2.0},
            "alias_rules": [{"pattern": "^test-only-.*", "canonical": "test-only-model"}],
            "fallback_models": {"codex": ["test-only-model"]},
        }
        supp = _supp.Supplement.decode(json.dumps(payload).encode())
        self.assertEqual(supp.canonical_name("test-only-x"), "test-only-model")
        self.assertEqual(supp.fast_multiplier("test-only-model"), 2.0)
        self.assertIn("test-only-model", supp.fallback_models["codex"])

    def test_bad_alias_skipped(self):
        payload = {"pricing": {}, "alias_rules": [{"pattern": "([", "canonical": "x"}]}
        supp = _supp.Supplement.decode(json.dumps(payload).encode())
        self.assertEqual(supp.alias_rules, [])


class PricingTest(unittest.TestCase):
    def test_layers_supplement_first(self):
        supp = _supp.Supplement(pricing={"m": _rates(input_per_m=1.0)})
        primary = _cat.PricingCatalog(entries={"m": _rates(input_per_m=2.0)})
        pricing = _pricing.ModelPricing(supp, primary, _cat.PricingCatalog())
        self.assertEqual(pricing.resolve("m").input_per_m, 1.0)

    def test_fast_variant_needs_multiplier(self):
        primary = _cat.PricingCatalog(entries={"base": _rates()})
        pricing = _pricing.ModelPricing(_supp.Supplement(), primary, _cat.PricingCatalog())
        self.assertIsNone(pricing.resolve("base-fast"))
        supp = _supp.Supplement(fast_multipliers={"base": 2.0})
        pricing = _pricing.ModelPricing(supp, primary, _cat.PricingCatalog())
        self.assertAlmostEqual(pricing.resolve("base-fast").input_per_m, 2.0)

    def test_secondary_exact_only(self):
        secondary = _cat.PricingCatalog(entries={"gap-model": _rates()})
        pricing = _pricing.ModelPricing(_supp.Supplement(), _cat.PricingCatalog(), secondary)
        self.assertIsNotNone(pricing.resolve("gap-model"))
        self.assertIsNone(pricing.resolve("gap-model-variant"))

    def test_fallback_exact_only(self):
        supp = _supp.Supplement(
            pricing={"exact": _rates()},
            fallback_models={"codex": ["exact", "missing"]})
        pricing = _pricing.ModelPricing(supp, _cat.PricingCatalog(), _cat.PricingCatalog())
        self.assertIsNotNone(pricing.fallback_rates("exact", "codex"))
        self.assertIsNone(pricing.fallback_rates("missing", "codex"))
        self.assertEqual(pricing.fallback_options("codex"), ["exact"])

    def test_family_strips_suffix(self):
        supp = _supp.Supplement(
            alias_rules=[(re.compile(".*"), "canon-fast")])
        pricing = _pricing.ModelPricing(supp, _cat.PricingCatalog(), _cat.PricingCatalog())
        self.assertEqual(pricing.family_name("anything", ["-fast"]), "canon")


class CodecsTest(unittest.TestCase):
    def test_litellm_skips_stubs(self):
        payload = {"good": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6},
                   "stub": {"input_cost_per_token": 1e-6}}
        catalog = _cat.catalog_from_litellm(json.dumps(payload).encode())
        self.assertIn("good", catalog.entries)
        self.assertNotIn("stub", catalog.entries)
        self.assertEqual(catalog.entries["good"].input_per_m, 1.0)

    def test_modelsdev_first_provider_wins(self):
        payload = {"b": {"models": {"m": {"cost": {"input": 2.0, "output": 3.0}}}},
                   "a": {"models": {"m": {"cost": {"input": 1.0, "output": 1.0}}}}}
        catalog = _cat.catalog_from_modelsdev(json.dumps(payload).encode())
        self.assertEqual(catalog.entries["m"].input_per_m, 1.0)

    def test_compact_roundtrip(self):
        catalog = _cat.PricingCatalog(
            entries={"m": _rates(input_above=5.0, fast_multiplier=2.0)},
            retrieved_at="2026-09-23")
        data = _cat.compact_data(catalog)
        back = _cat.catalog_from_compact(data)
        self.assertEqual(back.entries["m"].input_above, 5.0)
        self.assertEqual(back.entries["m"].fast_multiplier, 2.0)


class StoreTest(unittest.TestCase):
    def test_bundled_loads_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _store.Store(Path(tmp) / "pricing", http=None)
            pricing = store.current()
            self.assertGreater(len(pricing.primary.entries), 100)
            source, _ = store.source_info()
            self.assertEqual(source, "bundled")

    def test_fetch_and_304(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            assert isinstance(env.http, support.FakeHttp)
            lite = {"m": {"input_cost_per_token": 1e-6, "output_cost_per_token": 2e-6}}
            env.http.add("GET", _store.LITELLM_URL, 200, json.dumps(lite).encode(),
                         {"etag": "test-only-etag"})
            env.http.add("GET", _store.MODELS_DEV_URL, 304, b"")
            env.http.add("GET", _store.SUPPLEMENT_URL, 200,
                         json.dumps({"pricing": {}, "alias_rules": []}).encode())
            store = _store.Store(env.paths.pricing_dir, env.http)
            self.assertTrue(store.refresh_due(now=support.NOW))
            self.assertIn("m", store.current().primary.entries)
            self.assertFalse(store.refresh_due(now=support.NOW))

    def test_bad_payload_keeps_cache(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", _store.LITELLM_URL, 200, b"not json")
            env.http.add("GET", _store.MODELS_DEV_URL, 200, b"not json")
            env.http.add("GET", _store.SUPPLEMENT_URL, 200, b"not json")
            store = _store.Store(env.paths.pricing_dir, env.http)
            store.refresh_due(now=support.NOW)
            self.assertGreater(len(store.current().primary.entries), 100)


if __name__ == "__main__":
    unittest.main()
