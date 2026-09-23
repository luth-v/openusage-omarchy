"""Devin collector: two auth sources, remaining-flipped quotas."""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy import http as _http, model
from openusage_omarchy.providers import Env, devin

import support

FIX = Path(__file__).resolve().parent / "fixtures"


def load(name: str):
    return json.loads((FIX / name).read_text())


def status_url(server: str = devin.DEFAULT_SERVER) -> str:
    return f"{server}/{devin.SERVICE}/GetUserStatus"


def write_credentials(env, text: str) -> None:
    path = devin.credentials_path(env)
    path.parent.mkdir(parents=True)
    path.write_text(text)


def write_app_db(env, api_key: str) -> None:
    path = devin.app_db_path(env)
    path.parent.mkdir(parents=True)
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE ItemTable (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO ItemTable VALUES ('windsurfAuthStatus', ?)",
        (json.dumps({"apiKey": api_key}),),
    )
    conn.commit()
    conn.close()


class DevinTest(unittest.TestCase):
    def test_toml_strings(self):
        text = 'windsurf_api_key = "test-only-a"\napi_server_url = https://x.test/ # c\n'
        self.assertEqual(devin.read_toml_string(text, "windsurf_api_key"), "test-only-a")
        self.assertEqual(
            devin.read_toml_string(text, "api_server_url"), "https://x.test/")
        self.assertIsNone(devin.read_toml_string("other = 1\n", "windsurf_api_key"))
        self.assertIsNone(devin.read_toml_string("windsurf_api_key = \n", "windsurf_api_key"))
        self.assertIsNone(devin.read_toml_string("windsurf_api_key = \"abc\n", "windsurf_api_key"))
        self.assertEqual(
            devin.read_toml_string("windsurf_api_key='test-only-q'\n", "windsurf_api_key"),
            "test-only-q")

    def test_server_url_cleaning(self):
        self.assertEqual(
            devin.clean_server_url("https://x.test///"), "https://x.test")
        self.assertIsNone(devin.clean_server_url("http://x.test"))
        self.assertIsNone(devin.clean_server_url(None))
        self.assertIsNone(devin.clean_server_url("   "))

    def test_map_user_status(self):
        plan, lines = devin.map_user_status(load("devin_status.json")["userStatus"])
        self.assertEqual(plan, "Pro")
        self.assertEqual(lines["daily"].used, 30.0)
        self.assertEqual(lines["daily"].period_ms, devin.DAY_MS)
        self.assertIsNotNone(lines["daily"].resets_at)
        self.assertEqual(lines["weekly"].used, 60.0)
        extra = lines["extra"]
        assert isinstance(extra, model.Values)
        self.assertAlmostEqual(extra.values[0].number, 2.5)
        self.assertEqual(extra.values[0].kind, "dollars")

    def test_hidden_daily_falls_back_to_weekly(self):
        status = {"planStatus": {"planInfo": {"planName": "X", "hideDailyQuota": True},
                                 "dailyQuotaRemainingPercent": 80,
                                 "overageBalanceMicros": 0}}
        plan, lines = devin.map_user_status(status)
        self.assertNotIn("daily", lines)
        self.assertEqual(lines["weekly"].used, 20.0)
        self.assertAlmostEqual(lines["extra"].values[0].number, 0.0)

    def test_weekly_reset_without_percent_is_exhausted(self):
        status = {"planStatus": {"planInfo": {"planName": "X"},
                                 "weeklyQuotaResetAtUnix": 1788998400}}
        _, lines = devin.map_user_status(status)
        self.assertEqual(lines["weekly"].used, 100.0)

    def test_bad_shapes_raise(self):
        with self.assertRaises(ValueError):
            devin.map_user_status({"planStatus": {"planInfo": {}}})
        with self.assertRaises(ValueError):
            devin.map_user_status({"planStatus": {"weeklyQuotaRemainingPercent": True}})

    def test_fetch_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_credentials(env, 'windsurf_api_key = "test-only-a"\n')
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("POST", status_url(), load("devin_status.json"))
            self.assertTrue(devin.has_credentials(env))
            snap = devin.fetch(devin.cards(env)[0], env)
            self.assertEqual(snap.plan, "Pro")
            self.assertEqual(snap.metrics["daily"].used, 30.0)

    def test_custom_server(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_credentials(env, 'windsurf_api_key = "test-only-a"\n'
                                   'api_server_url = "https://x.test/"\n')
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("POST", status_url("https://x.test"),
                              load("devin_status.json"))
            snap = devin.fetch(devin.cards(env)[0], env)
            self.assertEqual(snap.plan, "Pro")

    def test_app_auth_fallback_on_401(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_credentials(env, 'windsurf_api_key = "test-only-a"\n')
            write_app_db(env, "test-only-app")
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("POST", status_url(), load("devin_status.json"))
            bodies: list[bytes] = []
            inner = env.http

            class _First401:
                def get(self, url, headers=None, timeout=10):
                    return inner.get(url, headers=headers, timeout=timeout)

                def post(self, url, body, headers=None, timeout=10):
                    bodies.append(body)
                    if len(bodies) == 1:
                        return _http.Response(status=401, body=b"{}")
                    return inner.post(url, body, headers=headers, timeout=timeout)

            sequenced = Env(http=_First401(), clock=env.clock, paths=env.paths)
            snap = devin.fetch(devin.cards(sequenced)[0], sequenced)
            self.assertEqual(snap.plan, "Pro")
            self.assertEqual(len(bodies), 2)
            self.assertIn("test-only-a", bodies[0].decode())
            self.assertIn("test-only-app", bodies[1].decode())

    def test_failures(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            self.assertFalse(devin.has_credentials(env))
            with self.assertRaises(model.CollectorError) as ctx:
                devin.fetch(devin.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")
            write_credentials(env, 'windsurf_api_key = "test-only-a"\n')
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("POST", status_url(), 401, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                devin.fetch(devin.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")
            env.http.add("POST", status_url(), 500, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                devin.fetch(devin.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "empty")


if __name__ == "__main__":
    unittest.main()
