"""Z.ai collector: window-split quotas plus the no-plan signal."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import model, secrets
from openusage_omarchy.providers import zai

import support

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text())


def raw(name: str) -> bytes:
    return (FIX / name).read_bytes()


class ZaiTest(unittest.TestCase):
    def test_map_quota(self):
        lines = zai.map_quota(raw("zai_quota.json"))
        session = lines["session"]
        assert isinstance(session, model.Progress)
        self.assertEqual(session.used, 60.0)
        self.assertEqual(session.period_ms, 5 * 3600 * 1000)
        self.assertIsNotNone(session.resets_at)
        weekly = lines["weekly"]
        assert isinstance(weekly, model.Progress)
        self.assertEqual(weekly.used, 20.0)
        self.assertEqual(weekly.period_ms, 7 * 86400 * 1000)
        web = lines["webSearches"]
        assert isinstance(web, model.Progress)
        self.assertEqual(web.used, 12)
        self.assertEqual(web.limit, 100)
        self.assertEqual(web.suffix, "searches")

    def test_legacy_token_limit_and_day_unit(self):
        payload = {"data": {"limits": [
            {"name": "TOKENS_LIMIT", "unit": 4, "number": 1, "percentage": 10},
            {"type": "UNKNOWN_FUTURE", "unit": 9, "number": 1, "percentage": 99},
        ]}}
        lines = zai.map_quota(json.dumps(payload).encode())
        self.assertEqual(lines["weekly"].used, 10)
        self.assertNotIn("session", lines)

    def test_empty_and_unrecognized_are_valid_no_data(self):
        self.assertEqual(zai.map_quota(b'{"data": {"limits": []}}'), {})
        self.assertEqual(
            zai.map_quota(b'{"data": {"limits": [{"type": "OTHER"}]}}'), {})

    def test_bad_shapes_raise(self):
        bad = [
            b"not json",
            b'{"data": []}',
            b'{"data": {}}',
            b'{"data": {"limits": [{"type": "CREDIT_LIMIT"}]}}',
            b'{"data": {"limits": [{"type": "CREDIT_LIMIT", "unit": 3, "number": 5}]}}',
            b'{"data": {"limits": [{"type": "TIME_LIMIT", "currentValue": 1}]}}',
            b'{"data": {"limits": [{"type": "TIME_LIMIT", "currentValue": -1, "usage": 5}]}}',
            b'{"data": {"limits": [{"type": "CREDIT_LIMIT", "unit": 3, "number": 0, "percentage": 1}]}}',
        ]
        for body in bad:
            with self.assertRaises(ValueError, msg=body):
                zai.map_quota(body)

    def test_no_coding_plan_signal(self):
        self.assertTrue(zai.is_no_coding_plan(raw("zai_noplan.json")))
        self.assertFalse(zai.is_no_coding_plan(raw("zai_quota.json")))
        self.assertFalse(zai.is_no_coding_plan(b'{"success": false, "msg": "boom"}'))

    def test_plan_name(self):
        self.assertEqual(zai.plan_name(raw("zai_subscription.json")), "GLM Coding Max")
        self.assertIsNone(zai.plan_name(b'{"data": []}'))
        self.assertIsNone(zai.plan_name(b"broken"))

    def test_fetch_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with patch.dict(os.environ, {"ZAI_API_KEY": "test-only-key"}):
                assert isinstance(env.http, support.FakeHttp)
                env.http.add("GET", zai.QUOTA_URL, 200, raw("zai_quota.json"))
                env.http.add("GET", zai.SUBSCRIPTION_URL, 200,
                             raw("zai_subscription.json"))
                self.assertTrue(zai.has_credentials(env))
                snap = zai.fetch(zai.cards(env)[0], env)
                self.assertEqual(snap.plan, "GLM Coding Max")
                self.assertEqual(snap.metrics["session"].used, 60.0)
                self.assertIn("webSearches", snap.metrics)

    def test_subscription_failure_keeps_meters(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            secrets.set_key("zai", "test-only-key", env.paths)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", zai.QUOTA_URL, 200, raw("zai_quota.json"))
            env.http.add("GET", zai.SUBSCRIPTION_URL, 500, b"{}")
            snap = zai.fetch(zai.cards(env)[0], env)
            self.assertIsNone(snap.plan)
            self.assertIn("session", snap.metrics)

    def test_rejected_key_no_plan_and_missing(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            self.assertFalse(zai.has_credentials(env))
            with self.assertRaises(model.CollectorError) as ctx:
                zai.fetch(zai.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")
            secrets.set_key("zai", "test-only-key", env.paths)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", zai.QUOTA_URL, 401, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                zai.fetch(zai.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")
            env.http.add("GET", zai.QUOTA_URL, 200, raw("zai_noplan.json"))
            with self.assertRaises(model.CollectorError) as ctx:
                zai.fetch(zai.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "empty")
            self.assertIn("GLM Coding Plan", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
