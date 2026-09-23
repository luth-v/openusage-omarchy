"""Codex collector tests: mapper, auth, accounts, claim, fetch."""

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import http as _http, model
from openusage_omarchy.providers import Env
from openusage_omarchy.providers.codex import accounts as _accounts
from openusage_omarchy.providers.codex import auth as _auth
from openusage_omarchy.providers.codex import client as _client
from openusage_omarchy.providers.codex import mapper as _mapper
from openusage_omarchy.providers.codex import reset_claim as _claim
from openusage_omarchy.providers import codex

import support

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text())


def make_jwt(payload: dict) -> str:
    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return f"{_b64(b'{}')}.{_b64(json.dumps(payload).encode())}.test-only-sig"


class _Sequence:
    """First usage GET returns 401, later calls delegate to the fake."""

    def __init__(self, inner: support.FakeHttp) -> None:
        self.inner = inner
        self.count = 0

    def get(self, url, headers=None, timeout=10):
        self.count += 1
        if self.count == 1 and url == _client.USAGE_URL:
            return _http.Response(status=401, body=b"{}", headers={})
        return self.inner.get(url, headers=headers, timeout=timeout)

    def post(self, url, body, headers=None, timeout=10):
        return self.inner.post(url, body, headers=headers, timeout=timeout)


class CodexMapper(unittest.TestCase):
    def test_windows_spark_and_plan(self):
        metrics, plan = _mapper.map_usage(
            (FIX / "codex_usage.json").read_bytes(), None, None, None,
            support.NOW)
        self.assertEqual(metrics["session"].used, 42)
        self.assertEqual(metrics["weekly"].used, 30)
        self.assertEqual(metrics["spark"].used, 20)
        self.assertEqual(metrics["sparkWeekly"].used, 10)
        self.assertEqual(plan, "Pro 20x")
        credits = metrics["credits"]
        assert isinstance(credits, model.Values)
        dollars = [v for v in credits.values if v.kind == "dollars"][0]
        counts = [v for v in credits.values if v.kind == "count"][0]
        self.assertEqual(counts.number, 821)
        self.assertAlmostEqual(dollars.number, 821 * 0.04)

    def test_moved_weekly_slot(self):
        body = json.dumps({"rate_limit": {
            "primary_window": {"limit_window_seconds": 604800,
                               "reset_after_seconds": 100, "used_percent": 30},
            "secondary_window": {"limit_window_seconds": 18000,
                                 "reset_after_seconds": 50, "used_percent": 42},
        }}).encode()
        metrics, _ = _mapper.map_usage(body, None, None, None, support.NOW)
        self.assertEqual(metrics["session"].used, 42)
        self.assertEqual(metrics["weekly"].used, 30)

    def test_headers_fill_missing_windows(self):
        body = json.dumps({}).encode()
        metrics, _ = _mapper.map_usage(
            body, {"X-Codex-Primary-Used-Percent": "11",
                   "X-Codex-Secondary-Used-Percent": "22"}, None, None,
            support.NOW)
        self.assertEqual(metrics["session"].used, 11)
        self.assertEqual(metrics["weekly"].used, 22)

    def test_reset_credits_dedicated_and_embedded(self):
        dedicated = (FIX / "codex_credits.json").read_bytes()
        resets = _mapper.reset_credits({}, dedicated, 200)
        assert resets is not None
        self.assertEqual(resets.values[0].number, 2)
        self.assertEqual(len(resets.expiries_at), 2)
        self.assertLess(resets.expiries_at[0], resets.expiries_at[1])
        body = {"rate_limit_reset_credits": {"available_count": 2}}
        resets = _mapper.reset_credits(body, None, None)
        assert resets is not None
        self.assertEqual(resets.values[0].number, 2)
        self.assertEqual(resets.expiries_at, ())
        self.assertIsNone(_mapper.reset_credits({}, None, None))

    def test_credit_values_floor(self):
        dollars, counts = _mapper.credit_values(821.9)
        self.assertEqual(counts.number, 821)
        self.assertAlmostEqual(dollars.number, 821 * 0.04)

    def test_plan_names(self):
        self.assertEqual(_mapper.format_plan("prolite"), "Pro 5x")
        self.assertEqual(_mapper.format_plan("pro"), "Pro 20x")
        self.assertEqual(_mapper.format_plan("self_serve_business_prolite"),
                         "Business Premium")
        self.assertEqual(_mapper.format_plan("team"), "Team")
        self.assertIsNone(_mapper.format_plan(""))


class CodexAuth(unittest.TestCase):
    def test_parse_and_identity(self):
        found = _auth.parse_auth((FIX / "codex_auth.json").read_text())
        assert found is not None
        assert found.tokens is not None
        self.assertEqual(found.tokens.access_token, "test-only-access")
        identity = _accounts.identity_of(found)
        assert identity is not None
        self.assertEqual(identity.account_id, "test-only-account")

    def test_jwt_refresh_logic(self):
        soon = make_jwt({"exp": int(support.NOW.timestamp()) + 60})
        late = make_jwt({"exp": int(support.NOW.timestamp()) + 3600})
        auth_data = _auth.Auth(tokens=_auth.Tokens(access_token=soon))
        self.assertTrue(_auth.needs_refresh(auth_data, support.NOW))
        auth_data = _auth.Auth(tokens=_auth.Tokens(access_token=late))
        self.assertFalse(_auth.needs_refresh(auth_data, support.NOW))
        old = _auth.Auth(tokens=_auth.Tokens(access_token="test-only-opaque"),
                         last_refresh="2026-01-01T00:00:00+00:00")
        self.assertTrue(_auth.needs_refresh(old, support.NOW))

    def test_swap_discovery(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            root = Path(tmp) / "data" / "codex-swap"
            root.mkdir(parents=True)
            payload = load("codex_accounts.json")
            payload["accounts"][0]["home"] = str(Path(tmp) / "swap-home")
            payload["mainHome"] = str(Path(tmp) / "main-home")
            (root / "accounts.json").write_text(json.dumps(payload))
            swaps = _accounts.discover_swap(env)
            self.assertEqual(len(swaps), 1)
            self.assertEqual(swaps[0].identity.account_id, "test-only-acct-2")
            cards = _accounts.assemble(env)
            self.assertEqual([c.card_id for c in cards], ["codex"])

    def test_two_swaps_make_family_card(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            root = Path(tmp) / "data" / "codex-swap"
            root.mkdir(parents=True)
            (root / "accounts.json").write_text(json.dumps({
                "schemaVersion": 1, "mainHome": str(Path(tmp) / "main"),
                "accounts": [
                    {"number": 1, "home": str(Path(tmp) / "a"),
                     "identity": {"accountId": "test-only-a",
                                 "email": "a@example.com"}},
                    {"number": 2, "home": str(Path(tmp) / "b"), "alias": "b",
                     "identity": {"accountId": "test-only-b",
                                 "email": "b@example.com"}},
                ]}))
            cards = _accounts.assemble(env)
            self.assertEqual(cards[0].card_id, "codex")
            self.assertTrue(cards[1].card_id.startswith("codex:"))
            self.assertEqual(len(cards[1].card_id), len("codex:") + 8)


class CodexClaim(unittest.TestCase):
    def test_claim_uses_only_target_account(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            identity = _accounts.Identity("test-only-b")
            entry = _accounts.AccountCard("codex:b", identity, "B", ("/test/b",))
            target = _accounts.to_ref(entry)
            first = _auth.Credential(_auth.Auth(tokens=_auth.Tokens(
                access_token="test-only-token-a", account_id="test-only-a")))
            second = _auth.Credential(_auth.Auth(tokens=_auth.Tokens(
                access_token="test-only-token-b", account_id="test-only-b")))
            with (patch.object(codex, "_card_entry", return_value=entry),
                  patch.object(_auth, "load_candidates", return_value=[first, second]) as loaded,
                  patch.object(codex, "_fetch_usage", side_effect=lambda e, c: (None, c)),
                  patch.object(_claim, "claim", return_value="success") as claim):
                outcome = _claim.claim_for_card(target, env, None, "test-only-request")
            self.assertEqual(outcome, "success")
            loaded.assert_called_once_with(["/test/b"])
            claim.assert_called_once()
            self.assertEqual(claim.call_args.args[1:3],
                             ("test-only-token-b", "test-only-b"))

    def test_match_by_expiry_and_soonest(self):
        from openusage_omarchy import parse as _parse
        body = load("codex_credits.json")
        moment = _parse.parse_time("2026-09-30T00:00:00Z")
        assert moment is not None
        self.assertEqual(
            _claim.credit_id_for(body, moment), "test-only-credit-1")
        missing = _parse.parse_time("2031-01-01T00:00:00Z")
        assert missing is not None
        self.assertIsNone(_claim.credit_id_for(body, missing))
        soonest = _claim.soonest_available(body)
        assert soonest is not None
        self.assertEqual(soonest[0], "test-only-credit-1")

    def test_consume_codes(self):
        cases = {"reset": "success", "already_redeemed": "success",
                 "nothing_to_reset": "nothingToReset", "no_credit": "noCredit",
                 "other": "failed"}
        for code, want in cases.items():
            body = json.dumps({"code": code}).encode()
            self.assertEqual(_claim.outcome_from_consume(200, body), want)
        self.assertEqual(_claim.outcome_from_consume(500, b"{}"), "failed")
        self.assertEqual(_claim.outcome_from_consume(200, b"nope"), "failed")

    def test_claim_success(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", _client.RESET_CREDITS_URL,
                              load("codex_credits.json"))
            env.http.add_json("POST", _client.CONSUME_URL, {"code": "reset"})
            outcome = _claim.claim(env.http, "test-only-token", "test-only-acct",
                                   None, "test-only-request")
            self.assertEqual(outcome, "success")

    def test_claim_no_credit(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", _client.RESET_CREDITS_URL,
                              {"available_count": 0, "credits": []})
            outcome = _claim.claim(env.http, "test-only-token", "test-only-acct",
                                   None, "test-only-request")
            self.assertEqual(outcome, "noCredit")


class CodexFetch(unittest.TestCase):
    def _stub(self, env):
        assert isinstance(env.http, support.FakeHttp)
        env.http.add_json("GET", _client.USAGE_URL, load("codex_usage.json"))
        env.http.add_json("GET", _client.RESET_CREDITS_URL,
                          load("codex_credits.json"))

    def test_fetch_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "codex-home"
            home.mkdir()
            (home / "auth.json").write_text(
                (FIX / "codex_auth.json").read_text())
            with patch.dict("os.environ", {"CODEX_HOME": str(home)}):
                self.assertTrue(codex.has_credentials(env))
                self._stub(env)
                snap = codex.fetch(codex.cards(env)[0], env)
                self.assertEqual(snap.plan, "Pro 20x")
                self.assertEqual(snap.metrics["session"].used, 42)
                resets = snap.metrics["rateLimitResets"]
                assert isinstance(resets, model.Values)
                self.assertEqual(len(resets.expiries_at), 2)

    def test_fetch_no_auth(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with patch.dict("os.environ", {"CODEX_HOME": str(Path(tmp) / "none")}):
                self.assertFalse(codex.has_credentials(env))
                with self.assertRaises(model.CollectorError) as ctx:
                    codex.fetch(codex.cards(env)[0], env)
                self.assertEqual(ctx.exception.category, "auth")

    def test_reactive_401_refresh(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "codex-home"
            home.mkdir()
            auth_path = home / "auth.json"
            auth_path.write_text((FIX / "codex_auth.json").read_text())
            with patch.dict("os.environ", {"CODEX_HOME": str(home)}):
                self._stub(env)
                assert isinstance(env.http, support.FakeHttp)
                env.http.add_json("POST", _client.REFRESH_URL, {
                    "access_token": "test-only-new",
                    "refresh_token": "test-only-refresh-2"})
                sequenced = Env(http=_Sequence(env.http), clock=env.clock,
                                paths=env.paths)
                snap = codex.fetch(codex.cards(sequenced)[0], sequenced)
                self.assertEqual(snap.metrics["weekly"].used, 30)
                stored = json.loads(auth_path.read_text())
                self.assertEqual(stored["tokens"]["access_token"],
                                 "test-only-new")


if __name__ == "__main__":
    unittest.main()
