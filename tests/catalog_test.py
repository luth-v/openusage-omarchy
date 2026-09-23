"""Catalog invariants. The vocabulary every seam keys on."""

import json
import unittest
from pathlib import Path

from openusage_omarchy import catalog
from openusage_omarchy.providers import registry

ROOT = Path(__file__).resolve().parent.parent

# Exact copy of the docs/local-http-api.md public-resources table.
API_TABLE = {
    "claude": {"session", "weekly", "sonnet", "fable", "extraUsage", "rateLimitResets"},
    "codex": {"session", "weekly", "spark", "sparkWeekly", "credits", "creditValue", "rateLimitResets"},
    "cursor": {"totalUsage", "grokBot", "autoUsage", "apiUsage", "onDemand", "requests", "credits"},
    "antigravity": {"geminiSession", "geminiWeekly", "nonGeminiSession", "nonGeminiWeekly"},
    "copilot": {"premiumCredits", "extraUsage", "orgCredits", "orgSpend", "chat", "completions"},
    "devin": {"daily", "weekly", "extraUsageBalance"},
    "grok": {"weekly"},
    "ollama": {"session", "weekly", "monthly"},
    "opencode": {"session", "weekly", "monthly"},
    "openrouter": {"credits", "balance", "keyLimit"},
    "zai": {"session", "weekly", "webSearches"},
}


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = catalog.load(ROOT / "catalog.json")

    def test_order_and_count(self):
        self.assertEqual(self.table.families(), list(catalog.ORDER))
        self.assertEqual(len(self.table.families()), 11)

    def test_spend_flags_match_scanners(self):
        self.assertEqual(self.table.spend_families(), {
            "claude", "codex", "cursor", "antigravity", "grok", "opencode"})

    def test_metric_fields(self):
        for provider in self.table.providers:
            self.assertTrue(provider.display_name)
            self.assertTrue(provider.mark)
            for metric in provider.metrics:
                self.assertIn(metric.kind, ("progress", "text", "badge", "chart"))
                self.assertIn(metric.placement, ("alwaysVisible", "onDemand"))
                self.assertTrue(metric.label)
                self.assertTrue(metric.metric_label)

    def test_star_budgets(self):
        for provider in self.table.providers:
            stars = [m for m in provider.metrics if m.default_star]
            self.assertLessEqual(len(stars), 2, provider.provider_id)
            for metric in provider.metrics:
                if metric.kind == "chart":
                    self.assertFalse(metric.starrable, metric.metric_id)
                    self.assertFalse(metric.default_star, metric.metric_id)
                if metric.default_star:
                    self.assertTrue(metric.starrable, metric.metric_id)

    def test_api_resources_match_upstream_table(self):
        for provider in self.table.providers:
            keys: set[str] = set()
            for metric in provider.metrics:
                keys.update(metric.api_resources)
            self.assertEqual(keys, API_TABLE[provider.provider_id], provider.provider_id)

    def test_default_stars_match_upstream(self):
        stars = {
            f"{p.provider_id}.{m.metric_id}"
            for p in self.table.providers
            for m in p.metrics
            if m.default_star
        }
        self.assertEqual(
            stars,
            {
                "antigravity.geminiPro", "antigravity.geminiWeekly",
                "claude.session", "claude.weekly",
                "codex.session", "codex.weekly",
                "cursor.auto", "cursor.api",
                "copilot.premium",
                "ollama.session", "ollama.weekly",
                "openrouter.credits",
                "zai.session", "zai.weekly",
            },
        )

    def test_off_by_default(self):
        off = {
            f"{p.provider_id}.{m.metric_id}"
            for p in self.table.providers
            for m in p.metrics
            if not m.default_on
        }
        self.assertEqual(off, {"claude.sonnet", "cursor.requests", "cursor.credits"})

    def test_ollama_never_auto_enables(self):
        for provider in self.table.providers:
            if provider.provider_id == "ollama":
                self.assertFalse(provider.auto_enable)
            else:
                self.assertTrue(provider.auto_enable)

    def test_registry_labels_match_catalog(self):
        for module in registry():
            provider = self.table.provider(module.family)
            self.assertIsNotNone(provider)
            assert provider is not None
            self.assertEqual(module.LABEL, provider.display_name)

    def test_marks_exist(self):
        for provider in self.table.providers:
            self.assertTrue((ROOT / provider.mark).is_file(), provider.mark)

    def test_catalog_json_valid(self):
        raw = json.loads((ROOT / "catalog.json").read_text())
        self.assertEqual(raw["schema"], "openusage-omarchy.catalog.v1")


if __name__ == "__main__":
    unittest.main()
