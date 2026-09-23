"""OpenRouter collector: independent endpoints, gated keys stay valid."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import model, secrets
from openusage_omarchy.providers import openrouter

import support

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text())


def save_key(env, key: str = "test-only-key") -> None:
    secrets.set_key("openrouter", key, env.paths)


class OpenRouterTest(unittest.TestCase):
    def test_credits_lines(self):
        data = openrouter.data_object((FIX / "openrouter_credits.json").read_bytes())
        assert data is not None
        lines = openrouter.credits_lines(data)
        row = lines["credits"]
        assert isinstance(row, model.Progress)
        self.assertAlmostEqual(row.used, 25.5)
        self.assertAlmostEqual(row.limit, 100.0)
        self.assertEqual(row.format_kind, "dollars")
        balance = lines["balance"]
        assert isinstance(balance, model.Values)
        self.assertAlmostEqual(balance.values[0].number, 74.5)

    def test_no_ceiling_yields_balance_only(self):
        lines = openrouter.credits_lines({"total_usage": 3.0, "total_credits": 0})
        self.assertNotIn("credits", lines)
        self.assertIn("balance", lines)
        self.assertEqual(openrouter.credits_lines({}), {})

    def test_key_metrics(self):
        data = openrouter.data_object((FIX / "openrouter_key.json").read_bytes())
        assert data is not None
        plan, lines = openrouter.key_metrics(data)
        self.assertEqual(plan, "Pay as you go")
        self.assertAlmostEqual(lines["today"].values[0].number, 1.25)
        self.assertAlmostEqual(lines["week"].values[0].number, 5.0)
        self.assertAlmostEqual(lines["month"].values[0].number, 25.5)
        cap = lines["keyLimit"]
        assert isinstance(cap, model.Progress)
        self.assertAlmostEqual(cap.used, 10.0)
        self.assertAlmostEqual(cap.limit, 50.0)

    def test_free_tier_and_missing_cap(self):
        plan, lines = openrouter.key_metrics({"is_free_tier": True})
        self.assertEqual(plan, "Free tier")
        self.assertNotIn("keyLimit", lines)
        _, lines = openrouter.key_metrics({"limit": 0, "limit_remaining": 0})
        self.assertNotIn("keyLimit", lines)

    def test_data_object_rejects_non_dict(self):
        self.assertIsNone(openrouter.data_object(b"[1, 2]"))
        self.assertIsNone(openrouter.data_object(b'{"data": [1]}'))
        self.assertIsNone(openrouter.data_object(b"not json"))

    def test_fetch_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            save_key(env)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", openrouter.CREDITS_URL,
                              load("openrouter_credits.json"))
            env.http.add_json("GET", openrouter.KEY_URL, load("openrouter_key.json"))
            self.assertTrue(openrouter.has_credentials(env))
            snap = openrouter.fetch(openrouter.cards(env)[0], env)
            self.assertEqual(snap.plan, "Pay as you go")
            self.assertAlmostEqual(snap.metrics["credits"].used, 25.5)
            self.assertIn("balance", snap.metrics)
            self.assertIn("keyLimit", snap.metrics)

    def test_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            self.assertFalse(openrouter.has_credentials(env))
            with self.assertRaises(model.CollectorError) as ctx:
                openrouter.fetch(openrouter.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")

    def test_both_rejected_means_invalid(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            save_key(env)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", openrouter.CREDITS_URL, 403, b"{}")
            env.http.add("GET", openrouter.KEY_URL, 401, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                openrouter.fetch(openrouter.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")
            self.assertIn("invalid", ctx.exception.message)

    def test_single_rejection_keeps_other_rows(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            save_key(env)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", openrouter.CREDITS_URL, 403, b"{}")
            env.http.add_json("GET", openrouter.KEY_URL, load("openrouter_key.json"))
            snap = openrouter.fetch(openrouter.cards(env)[0], env)
            self.assertNotIn("credits", snap.metrics)
            self.assertIn("today", snap.metrics)

    def test_status_and_transport(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            save_key(env)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", openrouter.CREDITS_URL, 500, b"{}")
            env.http.add("GET", openrouter.KEY_URL, 500, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                openrouter.fetch(openrouter.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "status")

    def test_env_key_works(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with patch.dict(os.environ, {"OPENROUTER_API_KEY": "test-only-env"}):
                self.assertTrue(openrouter.has_credentials(env))


if __name__ == "__main__":
    unittest.main()
