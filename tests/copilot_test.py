"""Copilot collector: credit pools, free counts, and org billing."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import model
from openusage_omarchy.providers import copilot
from openusage_omarchy.providers.copilot import auth as _auth
from openusage_omarchy.providers.copilot import billing as _billing
from openusage_omarchy.providers.copilot import mapper as _mapper

import support

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text())


def raw(name: str) -> bytes:
    return (FIX / name).read_bytes()


def write_editor(env, payload: dict) -> None:
    path = _auth.editor_paths(env)[0]
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload))


class CopilotAuthTest(unittest.TestCase):
    def test_editor_json(self):
        apps = {"github.com:vscode": {"oauth_token": "test-only-apps"}}
        self.assertEqual(_auth.oauth_token_from_editor_json(json.dumps(apps)),
                         "test-only-apps")
        hosts = {"github.com": {"oauth_token": "  test-only-hosts  "}}
        self.assertEqual(_auth.oauth_token_from_editor_json(json.dumps(hosts)),
                         "test-only-hosts")
        enterprise = {"ghe.test": {"oauth_token": "test-only-no"}}
        self.assertIsNone(
            _auth.oauth_token_from_editor_json(json.dumps(enterprise)))
        self.assertIsNone(_auth.oauth_token_from_editor_json("broken"))

    def test_yaml_scoped_to_github_com(self):
        text = (
            "ghe.test:\n"
            "    oauth_token: test-only-wrong\n"
            "    user: enterprise\n"
            "github.com:\n"
            "    user: test-only-user\n"
            "    oauth_token: 'test-only-gh'\n"
        )
        self.assertEqual(_auth.yaml_value(text, "oauth_token"), "test-only-gh")
        self.assertEqual(_auth.yaml_value(text, "user"), "test-only-user")
        self.assertIsNone(_auth.yaml_value("github.com:\n", "oauth_token"))

    def test_token_order(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            self.assertFalse(copilot.has_credentials(env))
            gh_dir = _auth.gh_hosts_path(env).parent
            gh_dir.mkdir(parents=True)
            _auth.gh_hosts_path(env).write_text(
                "github.com:\n    oauth_token: test-only-file\n")
            self.assertEqual(_auth.load_token(env), "test-only-file")
            write_editor(env, {"github.com": {"oauth_token": "test-only-editor"}})
            self.assertEqual(_auth.load_token(env), "test-only-editor")

    def test_gh_keyring_unwraps_go_keyring(self):
        import base64

        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env:
                wrapped = "go-keyring-base64:" + base64.b64encode(
                    b"test-only-ring").decode()
                base = Path(tmp)
                shim_dir = support.install_shim(base)
                with patch.dict(os.environ, {
                    "PATH": str(shim_dir),
                    "SHIM_LOG": str(base / "shim.log"),
                    "SHIM_HIT_GH": wrapped,
                }):
                    self.assertEqual(_auth.load_token(env), "test-only-ring")


class CopilotMapperTest(unittest.TestCase):
    def test_paid_plan(self):
        plan, lines, org = _mapper.map_body(load("copilot_usage.json"))
        self.assertEqual(plan, "Pro")
        self.assertFalse(org)
        premium = lines["premium"]
        assert isinstance(premium, model.Progress)
        self.assertEqual(premium.used, 40.0)
        self.assertEqual(premium.resets_at, "2026-10-01T00:00:00+00:00")
        extra = lines["extra"]
        assert isinstance(extra, model.Values)
        self.assertEqual(extra.values[0].number, 5)
        self.assertNotIn("chat", lines)
        self.assertNotIn("completions", lines)

    def test_free_plan(self):
        plan, lines, org = _mapper.map_body(load("copilot_free.json"))
        self.assertEqual(plan, "Free")
        self.assertFalse(org)
        self.assertNotIn("premium", lines)
        self.assertNotIn("extra", lines)
        self.assertEqual(lines["chat"].used, 60.0)
        self.assertEqual(lines["completions"].used, 10.0)
        self.assertEqual(lines["chat"].resets_at, "2026-10-01T00:00:00+00:00")

    def test_legacy_limited_shape(self):
        body = {"copilot_plan": "free",
                "limited_user_quotas": {"chat": 10, "completions": 50},
                "monthly_quotas": {"chat": 100, "completions": 100}}
        _, lines, _ = _mapper.map_body(body)
        self.assertEqual(lines["chat"].used, 90.0)
        self.assertEqual(lines["completions"].used, 50.0)

    def test_org_seat_personal_credits(self):
        plan, lines, org = _mapper.map_body(load("copilot_org_seat.json"))
        self.assertEqual(plan, "Business")
        self.assertTrue(org)
        premium = lines["premium"]
        assert isinstance(premium, model.Values)
        self.assertEqual(premium.values[0].number, 321)

    def test_org_seat_without_credits(self):
        body = {"copilot_plan": "business", "token_based_billing": True,
                "quota_snapshots": {"premium_interactions": {"entitlement": 0}}}
        plan, lines, org = _mapper.map_body(body)
        self.assertTrue(org)
        self.assertEqual(lines, {})

    def test_garbage_raises(self):
        with self.assertRaises(ValueError):
            _mapper.map_body({})


class CopilotBillingTest(unittest.TestCase):
    def test_usage_lines(self):
        lines = _billing.usage_lines(raw("copilot_billing.json"))
        assert lines is not None
        credits = lines["orgCredits"]
        assert isinstance(credits, model.Values)
        self.assertEqual(credits.values[0].number, 1200)
        self.assertEqual(credits.values[0].label, "credits")
        self.assertAlmostEqual(lines["orgSpend"].values[0].number, 30.0)
        self.assertIsNone(_billing.usage_lines(b'{"usageItems": []}'))
        self.assertIsNone(_billing.usage_lines(b"broken"))

    def test_org_logins(self):
        self.assertEqual(_billing.org_logins(raw("copilot_orgs.json")),
                         ["test-only-acme", "test-only-other"])
        self.assertEqual(_billing.org_logins(b"{}"), [])

    def test_remembered_org_short_circuits(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            _billing.remember_org(env, "test-only-acme")
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", _billing.summary_url("test-only-acme"), 200,
                         raw("copilot_billing.json"))
            lines = _billing.org_billing_lines(env, "test-only-t")
            self.assertIn("orgCredits", lines)
            self.assertEqual(len(env.http.calls), 1)

    def test_transient_keeps_cache(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            _billing.remember_org(env, "test-only-acme")
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", _billing.summary_url("test-only-acme"), 429, b"{}")
            self.assertEqual(_billing.org_billing_lines(env, "test-only-t"), {})
            self.assertEqual(_billing.remembered_org(env), "test-only-acme")

    def test_miss_reprobes_and_remembers(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", _billing.ORGS_URL, 200, raw("copilot_orgs.json"))
            env.http.add("GET", _billing.summary_url("test-only-acme"), 403, b"{}")
            env.http.add("GET", _billing.summary_url("test-only-other"), 200,
                         raw("copilot_billing.json"))
            lines = _billing.org_billing_lines(env, "test-only-t")
            self.assertIn("orgSpend", lines)
            self.assertEqual(_billing.remembered_org(env), "test-only-other")


class CopilotFetchTest(unittest.TestCase):
    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_editor(env, {"github.com": {"oauth_token": "test-only-t"}})
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", copilot.USAGE_URL, load("copilot_usage.json"))
            snap = copilot.fetch(copilot.cards(env)[0], env)
            self.assertEqual(snap.plan, "Pro")
            self.assertEqual(snap.metrics["premium"].used, 40.0)

    def test_org_seat_merges_billing(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_editor(env, {"github.com": {"oauth_token": "test-only-t"}})
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", copilot.USAGE_URL, load("copilot_org_seat.json"))
            env.http.add("GET", _billing.ORGS_URL, 200, raw("copilot_orgs.json"))
            env.http.add("GET", _billing.summary_url("test-only-acme"), 200,
                         raw("copilot_billing.json"))
            snap = copilot.fetch(copilot.cards(env)[0], env)
            self.assertEqual(snap.metrics["premium"].values[0].number, 321)
            self.assertIn("orgCredits", snap.metrics)

    def test_failures(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with self.assertRaises(model.CollectorError) as ctx:
                copilot.fetch(copilot.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")
            write_editor(env, {"github.com": {"oauth_token": "test-only-t"}})
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", copilot.USAGE_URL, 401, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                copilot.fetch(copilot.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")


if __name__ == "__main__":
    unittest.main()
