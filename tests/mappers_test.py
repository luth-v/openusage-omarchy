"""Mapper unit tests plus fetch integration with fake http and clock."""

import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy import http as _http, model
from openusage_omarchy.providers import cursor, grok, opencode
from openusage_omarchy.providers.cursor import mapper as _cmap
from openusage_omarchy.providers.cursor import summary as _csummary

import support

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text())


def make_jwt(payload: dict) -> str:
    import base64

    def _b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    header = _b64(b'{"alg":"none"}')
    body = _b64(json.dumps(payload).encode())
    return f"{header}.{body}.test-only-sig"


class CursorMapper(unittest.TestCase):
    def test_units_and_labels(self):
        metrics, plan = cursor.map_usage(load("cursor_usage.json"), "pro")
        self.assertEqual(metrics["auto"].used, 40)
        self.assertEqual(metrics["api"].used, 10)
        self.assertEqual(metrics["usage"].used, 40)
        self.assertEqual(plan, "pro")
        self.assertEqual(metrics["auto"].resets_at, "2026-09-03T00:00:00+00:00")
        self.assertEqual(metrics["auto"].period_ms, 2678400000)

    def test_on_demand_dollars(self):
        metrics, _ = cursor.map_usage(load("cursor_usage.json"), "")
        row = metrics["onDemand"]
        self.assertIsInstance(row, model.Progress)
        assert isinstance(row, model.Progress)
        self.assertEqual(row.format_kind, "dollars")
        self.assertAlmostEqual(row.used, 12.50)
        self.assertAlmostEqual(row.limit, 50.00)
        self.assertIsNone(row.resets_at)

    def test_fallback_total_usage(self):
        usage = {"planUsage": {"limit": 20000, "totalSpend": 5000},
                 "billingCycleEnd": 1788393600000}
        metrics, _ = cursor.map_usage(usage, "")
        self.assertEqual(metrics["usage"].used, 25)
        self.assertNotIn("auto", metrics)

    def test_empty_raises(self):
        with self.assertRaises(model.CollectorError):
            cursor.map_usage({"planUsage": {}}, "")

    def test_disabled_raises(self):
        with self.assertRaises(model.CollectorError):
            cursor.map_usage({"enabled": False, "planUsage": {"limit": 1}}, "")

    def test_plan_label(self):
        self.assertEqual(cursor.plan_label("pro", "", ""), "Pro")
        self.assertEqual(cursor.plan_label("", "team", "past_due"), "Team (past_due)")
        self.assertEqual(cursor.plan_label("", "pro", "active"), "Pro")
        self.assertEqual(cursor.plan_label("", "", ""), "")

    def test_grok_bot(self):
        line = _cmap.map_grok_bot(load("cursor_grokbot.json"))
        assert line is not None
        self.assertEqual(line.used, 35)
        self.assertEqual(line.metric_id, "grokBot")
        self.assertIsNone(_cmap.map_grok_bot({"usesPooledEnterpriseAllowance": True}))

    def test_credits(self):
        row = _cmap.credits_metric(load("cursor_credits.json"), 0)
        assert row is not None
        self.assertAlmostEqual(row.values[0].number, 75.00)
        self.assertIsNone(_cmap.credits_metric(None, 0))

    def test_stripe_balance(self):
        self.assertEqual(_cmap.stripe_balance_cents({"customerBalance": -1500}), 1500)
        self.assertEqual(_cmap.stripe_balance_cents({"customerBalance": 100}), 0)
        self.assertEqual(_cmap.stripe_balance_cents(None), 0)

    def test_request_based(self):
        metrics, _ = _cmap.map_request_based(load("cursor_requests.json"), "pro", "x")
        row = metrics["requests"]
        assert isinstance(row, model.Progress)
        self.assertEqual(row.used, 120)
        self.assertEqual(row.limit, 500)
        self.assertEqual(row.suffix, "requests")

    def test_summary(self):
        metrics, plan = _csummary.map_summary(
            load("cursor_summary.json"), load("cursor_requests.json"), None, "x")
        self.assertIn("usage", metrics)
        self.assertIn("requests", metrics)
        self.assertIn("auto", metrics)
        self.assertEqual(plan, "Pro")

    def test_should_fallback(self):
        yes, _ = _cmap.should_fallback(
            {"planUsage": {}}, "enterprise", False)
        self.assertTrue(yes)
        no, _ = _cmap.should_fallback(load("cursor_usage.json"), "pro", False)
        self.assertFalse(no)

    def test_team_dollars(self):
        usage = {"planUsage": {"limit": 20000, "totalSpend": 5000},
                 "billingCycleEnd": 1788393600000}
        metrics, _ = cursor.map_usage(usage, "team")
        row = metrics["usage"]
        assert isinstance(row, model.Progress)
        self.assertEqual(row.format_kind, "dollars")

    def test_fetch_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            user_dir = env.paths.config_dir.parent / "Cursor" / "User" / "globalStorage"
            user_dir.mkdir(parents=True)
            db = user_dir / "state.vscdb"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO ItemTable VALUES ('cursorAuth/accessToken', 'test-only-token')")
            conn.execute("INSERT INTO ItemTable VALUES ('cursorAuth/stripeMembershipType', 'pro')")
            conn.commit()
            conn.close()
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("POST", cursor.USAGE_URL, load("cursor_usage.json"))
            env.http.add_json("POST", cursor.PLAN_URL, load("cursor_plan.json"))
            env.http.add_json("POST", cursor.GROK_BOT_URL, load("cursor_grokbot.json"))
            env.http.add_json("POST", cursor.CREDITS_URL, load("cursor_credits.json"))
            self.assertTrue(cursor.has_credentials(env))
            snap = cursor.fetch(cursor.cards(env)[0], env)
            self.assertEqual(snap.plan, "Pro")
            self.assertEqual(snap.metrics["auto"].used, 40)
            assert isinstance(snap.metrics["onDemand"], model.Progress)
            self.assertEqual(snap.metrics["grokBot"].used, 35)
            assert isinstance(snap.metrics["credits"], model.Values)

    def test_fetch_no_auth(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            self.assertFalse(cursor.has_credentials(env))
            with self.assertRaises(model.CollectorError) as ctx:
                cursor.fetch(cursor.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")

    def test_fetch_status_error(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            user_dir = env.paths.config_dir.parent / "Cursor" / "User" / "globalStorage"
            user_dir.mkdir(parents=True)
            db = user_dir / "state.vscdb"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO ItemTable VALUES ('cursorAuth/accessToken', 'test-only-token')")
            conn.commit()
            conn.close()
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("POST", cursor.USAGE_URL, 500, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                cursor.fetch(cursor.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "status")

    def test_refresh_writes_back(self):
        from openusage_omarchy.providers.cursor import auth as _auth
        from openusage_omarchy.providers.cursor import client as _client

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            user_dir = env.paths.config_dir.parent / "Cursor" / "User" / "globalStorage"
            user_dir.mkdir(parents=True)
            db = user_dir / "state.vscdb"
            conn = sqlite3.connect(db)
            conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
            expired = make_jwt({"sub": "u-1", "exp": 1000})
            conn.execute("INSERT INTO ItemTable VALUES ('cursorAuth/accessToken', ?)", (expired,))
            conn.execute("INSERT INTO ItemTable VALUES ('cursorAuth/refreshToken', 'test-only-refresh')")
            conn.commit()
            conn.close()
            self.assertTrue(_auth.needs_refresh(expired, support.NOW))
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("POST", _client.REFRESH_URL, {"access_token": "test-only-new"})
            token = _client.refresh_access_token(env.http, "test-only-refresh")
            self.assertEqual(token, "test-only-new")
            self.assertTrue(_auth.save_access_token(env, expired, token))
            stored = _auth.read_state(db)
            self.assertEqual(stored["cursorAuth/accessToken"], "test-only-new")
            self.assertFalse(_auth.save_access_token(env, expired, "test-only-late"))
            self.assertEqual(_auth.read_state(db)["cursorAuth/accessToken"],
                             "test-only-new")
            db.unlink()
            self.assertFalse(_auth.save_access_token(env, token, "test-only-late"))
            self.assertFalse(db.exists())


class GrokMapper(unittest.TestCase):
    def test_weekly_and_cap_badge(self):
        import json as _json

        config = grok.decode_config(_json.dumps(load("grok_billing.json")).encode())
        self.assertEqual(config["percent"], 25)
        self.assertEqual(config["cap"], 2500)
        self.assertEqual(
            config["end"].isoformat(), "2026-07-10T04:01:09.238389+00:00")

    def test_non_weekly_decodes(self):
        import json as _json

        payload = {"config": {"creditUsagePercent": 50, "currentPeriod": {
            "type": "USAGE_PERIOD_TYPE_MONTHLY",
            "start": "2026-07-01T00:00:00+00:00", "end": "2026-08-01T00:00:00+00:00"}}}
        config = grok.decode_config(_json.dumps(payload).encode())
        self.assertEqual(config["periodType"], "USAGE_PERIOD_TYPE_MONTHLY")

    def test_bad_config_raises(self):
        import json as _json

        for payload in ({}, {"config": {}}, {"config": {"currentPeriod": {}}}):
            with self.assertRaises(model.CollectorError):
                grok.decode_config(_json.dumps(payload).encode())

    def test_multi_candidate(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "home" / ".grok"
            home.mkdir(parents=True)
            (home / "auth.json").write_text(json.dumps({
                "a": {"key": "test-only-1"}, "b": {"key": "test-only-2"}}))
            found = grok.load_candidates(env)
            self.assertEqual(len(found), 2)

    def test_fetch_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "home" / ".grok"
            home.mkdir(parents=True)
            (home / "auth.json").write_text((FIX / "grok_auth.json").read_text())
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", grok.BILLING_URL, load("grok_billing.json"))
            env.http.add_json("GET", grok.SETTINGS_URL, load("grok_settings.json"))
            self.assertTrue(grok.has_credentials(env))
            snap = grok.fetch(grok.cards(env)[0], env)
            self.assertEqual(snap.plan, "SuperGrok")
            self.assertEqual(snap.metrics["weekly"].used, 25)

    def test_refresh_writes_back_no_cache_token(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "home" / ".grok"
            home.mkdir(parents=True)
            auth_path = home / "auth.json"
            auth_path.write_text(json.dumps({
                "entry": {"key": "test-only-old", "refresh_token": "test-only-refresh",
                          "expires_at": "2000-01-01T00:00:00+00:00"}}))
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("POST", grok.TOKEN_URL, {
                "access_token": "test-only-new", "refresh_token": "test-only-refresh-2",
                "expires_in": 3600})
            env.http.add_json("GET", grok.BILLING_URL, load("grok_billing.json"))
            env.http.add_json("GET", grok.SETTINGS_URL, load("grok_settings.json"))
            snap = grok.fetch(grok.cards(env)[0], env)
            self.assertEqual(snap.metrics["weekly"].used, 25)
            stored = json.loads(auth_path.read_text())
            self.assertEqual(stored["entry"]["key"], "test-only-new")
            self.assertEqual(stored["entry"]["refresh_token"], "test-only-refresh-2")
            cache_dir = env.paths.cache_dir
            tokens = list(cache_dir.rglob("*")) if cache_dir.exists() else []
            for path in tokens:
                if path.is_file():
                    self.assertNotIn("test-only-new", path.read_text())

    def test_expiry_parse(self):
        self.assertEqual(grok.parse_expiry(None), 0.0)
        self.assertEqual(grok.parse_expiry(3600), 3600)
        self.assertEqual(grok.parse_expiry(1788393600000), 1788393600)
        self.assertGreater(grok.parse_expiry("2030-01-01T00:00:00+00:00"), 0)


class OpenCodeMapper(unittest.TestCase):
    def test_windows(self):
        metrics = opencode.parse_windows(load("opencode_usage.json"))
        self.assertEqual(metrics["session"].used, 12)
        self.assertEqual(metrics["weekly"].used, 34)
        self.assertEqual(metrics["monthly"].used, 62)
        self.assertEqual(metrics["session"].period_ms, opencode.SESSION_MS)

    def test_invalid(self):
        for payload in ({}, {"error": "denied"}, {"usage": {}},
                        {"usage": {"rolling": {"percent": True}}},
                        {"usage": {"rolling": {"percent": 1, "resetsAt": "2027-01-01T00:00:00Z"}}}):
            with self.assertRaises(ValueError, msg=str(payload)):
                opencode.parse_windows(payload)

    def test_error_type(self):
        self.assertEqual(
            opencode.error_type(b'{"error": {"type": "EntitlementError"}}'),
            "EntitlementError")
        self.assertIsNone(opencode.error_type(b"<html>"))

    def test_fetch_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            data = opencode.data_dir(env)
            data.mkdir(parents=True)
            (data / "auth.json").write_text((FIX / "opencode_auth.json").read_text())
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", opencode.URL, load("opencode_usage.json"))
            self.assertTrue(opencode.has_credentials(env))
            snap = opencode.fetch(opencode.cards(env)[0], env)
            self.assertEqual(snap.plan, "Go")
            self.assertEqual(snap.metrics["monthly"].used, 62)

    def test_fetch_no_key(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            self.assertFalse(opencode.has_credentials(env))
            with self.assertRaises(model.CollectorError) as ctx:
                opencode.fetch(opencode.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")

    def test_fetch_unauthorized(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            data = opencode.data_dir(env)
            data.mkdir(parents=True)
            (data / "auth.json").write_text((FIX / "opencode_auth.json").read_text())
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", opencode.URL, 401, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                opencode.fetch(opencode.cards(env)[0], env)
            self.assertIn("rejected", ctx.exception.message)

    def test_fetch_no_subscription(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            data = opencode.data_dir(env)
            data.mkdir(parents=True)
            (data / "auth.json").write_text((FIX / "opencode_auth.json").read_text())
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", opencode.URL, 403,
                         b'{"error": {"type": "EntitlementError"}}')
            with self.assertRaises(model.CollectorError) as ctx:
                opencode.fetch(opencode.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "empty")

    def test_unreadable_auth(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            data = opencode.data_dir(env)
            data.mkdir(parents=True)
            (data / "auth.json").write_text("{bad json")
            self.assertTrue(opencode.has_credentials(env))
            with self.assertRaises(model.CollectorError) as ctx:
                opencode.fetch(opencode.cards(env)[0], env)
            self.assertIn("auth.json", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
