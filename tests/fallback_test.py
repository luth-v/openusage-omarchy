"""Codex fallback model: titles, picker options, setting, rescan marker."""

import tempfile
import unittest
from dataclasses import replace

from openusage_omarchy.daemon import main, publish
from openusage_omarchy.spend import context as _ctx
from openusage_omarchy.spend.pricing import fallback_title

import support


class FakeSettings:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, fallback=None):
        return self.values.get(key, fallback)


class FallbackTest(unittest.TestCase):
    def test_title_ports_upstream_words(self):
        self.assertEqual(fallback_title("gpt-5"), "GPT 5")
        self.assertEqual(fallback_title("gpt-5.1-codex-mini"), "GPT 5.1 Codex Mini")
        self.assertEqual(fallback_title("o3-mini"), "o3 Mini")
        self.assertEqual(fallback_title("codex-mini-latest"), "Codex Mini Latest")

    def test_options_come_priced_with_titles(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            options = _ctx.codex_options(env)
            self.assertTrue(options)
            ids = [item["id"] for item in options]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertIn("gpt-5", ids)
            for item in options:
                self.assertEqual(item["title"], fallback_title(item["id"]))

    def test_setting_reads_shell_choice(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            self.assertEqual(_ctx.fallback_setting(env), "")
            picked = replace(env, settings=FakeSettings(
                {"codexFallbackModel": "  gpt-5 "}))
            self.assertEqual(_ctx.fallback_setting(picked), "gpt-5")
            broken = replace(env, settings=FakeSettings(
                {"codexFallbackModel": 42}))
            self.assertEqual(_ctx.fallback_setting(broken), "")

    def test_marker_adopts_then_detects_change(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = main.Daemon(env.paths)
            daemon.env = env
            self.assertFalse(daemon._fallback_rescan_due())
            self.assertFalse(daemon._fallback_rescan_due())
            daemon.env = replace(
                env, settings=FakeSettings({"codexFallbackModel": "gpt-5"}))
            self.assertTrue(daemon._fallback_rescan_due())
            self.assertFalse(daemon._fallback_rescan_due())
            marker = env.paths.cache_dir / main.APPLIED_FALLBACK
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), "gpt-5")

    def test_state_carries_picker_options(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = main.Daemon(env.paths)
            options = [{"id": "gpt-5", "title": "GPT 5"}]
            state = publish.build(
                daemon.table, None, {}, "session-1", "0.0", support.NOW,
                [], None, codex_options=options)
            self.assertEqual(
                state["pricing"]["codexFallbackOptions"], options)
            plain = publish.build(
                daemon.table, None, {}, "session-1", "0.0", support.NOW,
                [], None)
            self.assertEqual(plain["pricing"]["codexFallbackOptions"], [])


if __name__ == "__main__":
    unittest.main()
