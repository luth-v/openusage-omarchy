"""Claude collector tests: mapper, auth, accounts, fetch round trips."""

import base64
import json
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import http as _http, model
from openusage_omarchy.providers import Env
from openusage_omarchy.providers.claude import accounts as _accounts
from openusage_omarchy.providers.claude import auth as _auth
from openusage_omarchy.providers.claude import client as _client
from openusage_omarchy.providers.claude import mapper as _mapper
from openusage_omarchy.providers import claude

import support

FIX = Path(__file__).resolve().parent / "fixtures"
USER = "11111111-1111-1111-1111-111111111111"
ORG = "22222222-2222-2222-2222-222222222222"


def load(name: str):
    return json.loads((FIX / name).read_text())


@contextmanager
def clean_claude_env():
    """Drop machine Claude overrides so oauth_config is deterministic."""
    names = [key for key in os.environ
             if key.startswith("CLAUDE_") or key in (
                 "USER_TYPE", "USE_LOCAL_OAUTH", "USE_STAGING_OAUTH",
                 "CLAUDE_LOCAL_OAUTH_API_BASE")]
    with patch.dict(os.environ, {}, clear=False):
        for key in names:
            os.environ.pop(key, None)
        os.environ.pop("CLAUDE_CODE_OAUTH_TOKEN", None)
        yield


class _Sequence:
    """First GET returns 401, later calls delegate to the fake."""

    def __init__(self, inner: support.FakeHttp) -> None:
        self.inner = inner
        self.count = 0

    def get(self, url, headers=None, timeout=10):
        self.count += 1
        if self.count == 1:
            return _http.Response(status=401, body=b"{}", headers={})
        return self.inner.get(url, headers=headers, timeout=timeout)

    def post(self, url, body, headers=None, timeout=10):
        return self.inner.post(url, body, headers=headers, timeout=timeout)


def write_creds(home: Path, payload: dict) -> Path:
    path = home / ".claude" / ".credentials.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


class ClaudeMapper(unittest.TestCase):
    def test_windows_fable_extra_resets(self):
        oauth = _auth.OAuth(subscription_type="max", rate_limit_tier="max_5x")
        metrics, plan = _mapper.map_usage(
            (FIX / "claude_usage.json").read_bytes(), oauth, support.NOW)
        self.assertEqual(metrics["session"].used, 42)
        self.assertEqual(metrics["weekly"].used, 30)
        self.assertEqual(metrics["sonnet"].used, 5)
        self.assertEqual(metrics["fable"].used, 15)
        extra = metrics["extra"]
        assert isinstance(extra, model.Progress)
        self.assertAlmostEqual(extra.used, 25.00)
        self.assertAlmostEqual(extra.limit, 100.00)
        self.assertEqual(extra.format_kind, "dollars")
        resets = metrics["rateLimitResets"]
        assert isinstance(resets, model.Values)
        self.assertEqual(resets.values[0].number, 1)
        self.assertEqual(resets.expiries_at, ("2026-10-01T00:00:00+00:00",))
        self.assertEqual(plan, "Max 5x")

    def test_extra_uncapped_values(self):
        oauth = _auth.OAuth()
        body = json.dumps({"extra_usage": {
            "is_enabled": True, "used_credits": 100}}).encode()
        metrics, _ = _mapper.map_usage(body, oauth, support.NOW)
        extra = metrics["extra"]
        assert isinstance(extra, model.Values)
        self.assertAlmostEqual(extra.values[0].number, 1.00)
        body = json.dumps({"extra_usage": {"is_enabled": False}}).encode()
        metrics, _ = _mapper.map_usage(body, oauth, support.NOW)
        self.assertNotIn("extra", metrics)

    def test_reset_grants_ineligible(self):
        oauth = _auth.OAuth()
        body = json.dumps({"cedar_ember": {"eligible": False}}).encode()
        metrics, _ = _mapper.map_usage(body, oauth, support.NOW)
        resets = metrics["rateLimitResets"]
        assert isinstance(resets, model.Values)
        self.assertEqual(resets.values[0].number, 0)
        self.assertEqual(resets.expiries_at, ())

    def test_plan_format(self):
        self.assertEqual(_mapper.format_plan("max", "max_5x"), "Max 5x")
        self.assertEqual(_mapper.format_plan("pro", ""), "Pro")
        self.assertIsNone(_mapper.format_plan("", ""))
        live = _mapper.format_live_plan(load("claude_profile.json"), _auth.OAuth())
        self.assertEqual(live, "Max 20x")

    def test_retry_after(self):
        now = support.NOW
        self.assertEqual(_mapper.parse_retry_after({"Retry-After": "120"}, now), 120)
        self.assertIsNone(_mapper.parse_retry_after({}, now))
        self.assertIsNone(_mapper.parse_retry_after({"Retry-After": "junk junk"}, now))
        self.assertIn("2m", _mapper.rate_limit_message(120))
        self.assertIn("now", _mapper.rate_limit_message(0))


class ClaudeAuth(unittest.TestCase):
    def test_file_parse_and_hex(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "home"
            payload = load("claude_credentials.json")
            write_creds(home, payload)
            cred = _auth.load_file(env)
            assert cred is not None
            self.assertEqual(cred.oauth.access_token, "test-only-access")
            self.assertEqual(_auth.live_availability(cred), "available")
            encoded = (FIX / "claude_credentials.json").read_bytes().hex()
            self.assertEqual(_auth.parse_credentials(encoded), payload)
            self.assertIsNone(_auth.parse_credentials("not json or hex!!"))

    def test_env_token_order(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "home"
            write_creds(home, load("claude_credentials.json"))
            stored = _auth.load_file(env)
            assert stored is not None
            with patch.dict(os.environ, {"CLAUDE_CODE_OAUTH_TOKEN": "test-only-env"}):
                ordered = _auth.with_environment_token([stored])
                self.assertEqual([c.source for c in ordered], ["file", "environment"])
                self.assertTrue(ordered[1].inference_only)
                alone = _auth.with_environment_token([])
                self.assertEqual(len(alone), 1)
                self.assertTrue(alone[0].inference_only)

    def test_missing_scope(self):
        oauth = _auth.OAuth(access_token="test-only-x", scopes=["user:inference"])
        self.assertEqual(
            _auth.live_availability(_auth.Credential(oauth=oauth)),
            "missingProfileScope")

    def test_swap_discovery_and_default_identity(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "home"
            root = home / ".claude-swap-backup"
            root.mkdir(parents=True)
            (root / "sequence.json").write_text(
                (FIX / "claude_sequence.json").read_text())
            (home / ".claude.json").write_text(
                (FIX / "claude_state.json").read_text())
            swaps = _accounts.discover_swap(env)
            self.assertEqual(len(swaps), 1)
            self.assertEqual(swaps[0].identity_key, f"{USER}|{ORG}")
            key, label, _anchor = _accounts.default_identity(env)
            self.assertEqual(key, f"{USER}|{ORG}")
            self.assertIn("Acme", label)
            cards = _accounts.assemble(env)
            self.assertEqual(len(cards), 1)
            self.assertEqual(cards[0].card_id, "claude")

    def test_desktop_orgs(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            root = Path(tmp) / "config" / "Claude"
            sessions = root / "claude-code-sessions" / USER / ORG
            sessions.mkdir(parents=True)
            (root / "config.json").write_text(json.dumps(
                {"lastKnownAccountUuid": USER}))
            found = _accounts.discover_desktop_orgs(env)
            self.assertEqual(found, [(f"{USER}|{ORG}", ORG, f"Organization {ORG[:8]}")])


class ClaudeFetch(unittest.TestCase):
    def _stub(self, env, usage_status=200, usage_headers=None):
        assert isinstance(env.http, support.FakeHttp)
        with clean_claude_env():
            config = _auth.oauth_config()
        env.http.add("GET", _client.usage_url(config.usage_url), usage_status,
                     (FIX / "claude_usage.json").read_bytes(),
                     headers=usage_headers)
        env.http.add_json("GET", _client.profile_url(config.usage_url),
                          load("claude_profile.json"))
        return config

    def test_fetch_round_trip(self):
        with clean_claude_env(), tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env:
                home = Path(tmp) / "home"
                write_creds(home, load("claude_credentials.json"))
                self.assertTrue(claude.has_credentials(env))
                self._stub(env)
                snap = claude.fetch(claude.cards(env)[0], env)
                self.assertEqual(snap.plan, "Max 20x")
                self.assertEqual(snap.metrics["session"].used, 42)
                self.assertEqual(snap.metrics["fable"].used, 15)

    def test_fetch_no_auth(self):
        with clean_claude_env(), tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env:
                self.assertFalse(claude.has_credentials(env))
                with self.assertRaises(model.CollectorError) as ctx:
                    claude.fetch(claude.cards(env)[0], env)
                self.assertEqual(ctx.exception.category, "auth")

    def test_proactive_refresh_writes_back(self):
        with clean_claude_env(), tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env:
                home = Path(tmp) / "home"
                payload = load("claude_credentials.json")
                payload["claudeAiOauth"]["expiresAt"] = 1000
                path = write_creds(home, payload)
                config = self._stub(env)
                assert isinstance(env.http, support.FakeHttp)
                env.http.add_json("POST", config.refresh_url, {
                    "access_token": "test-only-new", "expires_in": 3600})
                snap = claude.fetch(claude.cards(env)[0], env)
                self.assertEqual(snap.metrics["session"].used, 42)
                stored = json.loads(path.read_text())
                self.assertEqual(
                    stored["claudeAiOauth"]["accessToken"], "test-only-new")

    def test_reactive_401_refresh(self):
        with clean_claude_env(), tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env:
                home = Path(tmp) / "home"
                write_creds(home, load("claude_credentials.json"))
                config = self._stub(env)
                assert isinstance(env.http, support.FakeHttp)
                env.http.add_json("POST", config.refresh_url, {
                    "access_token": "test-only-new", "expires_in": 3600})
                sequenced = Env(http=_Sequence(env.http), clock=env.clock,
                                paths=env.paths)
                snap = claude.fetch(claude.cards(sequenced)[0], sequenced)
                self.assertEqual(snap.metrics["weekly"].used, 30)

    def test_rate_limited(self):
        with clean_claude_env(), tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env:
                home = Path(tmp) / "home"
                write_creds(home, load("claude_credentials.json"))
                self._stub(env, usage_status=429,
                           usage_headers={"Retry-After": "120"})
                with self.assertRaises(model.CollectorError) as ctx:
                    claude.fetch(claude.cards(env)[0], env)
                self.assertEqual(ctx.exception.category, "rate_limited")
                self.assertIn("2m", ctx.exception.message)

    def test_missing_scope_is_auth_error(self):
        with clean_claude_env(), tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env:
                home = Path(tmp) / "home"
                payload = load("claude_credentials.json")
                payload["claudeAiOauth"]["scopes"] = ["user:inference"]
                write_creds(home, payload)
                self._stub(env)
                with self.assertRaises(model.CollectorError) as ctx:
                    claude.fetch(claude.cards(env)[0], env)
                self.assertEqual(ctx.exception.category, "auth")
                self.assertIn("Re-login", ctx.exception.message)

    def test_env_only_token_cannot_fetch(self):
        with clean_claude_env(), tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ,
                            {"CLAUDE_CODE_OAUTH_TOKEN": "test-only-env"}):
                with support.test_env(tmp) as env:
                    self._stub(env)
                    with self.assertRaises(model.CollectorError) as ctx:
                        claude.fetch(claude.cards(env)[0], env)
                    self.assertIn("Not logged in", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
