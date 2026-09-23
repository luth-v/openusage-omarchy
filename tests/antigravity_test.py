"""Antigravity collector: token shapes, /proc discovery, quota pooling."""

import base64
import datetime as dt
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import model
from openusage_omarchy.providers import antigravity
from openusage_omarchy.providers.antigravity import auth as _auth
from openusage_omarchy.providers.antigravity import cloud as _cloud
from openusage_omarchy.providers.antigravity import ls as _ls
from openusage_omarchy.providers.antigravity import mapper as _mapper

import support

FIX = Path(__file__).resolve().parent / "fixtures"


def raw(name: str) -> bytes:
    return (FIX / name).read_bytes()


def load(name: str):
    return json.loads(raw(name).decode())


def shim_env(tmp: str, gemini: str | None) -> dict[str, str]:
    base = Path(tmp)
    shim_dir = support.install_shim(base)
    env = {"PATH": str(shim_dir), "SHIM_LOG": str(base / "shim.log")}
    if gemini is not None:
        env["SHIM_HIT_GEMINI"] = gemini
    return env


class AuthTest(unittest.TestCase):
    def test_extract_shapes(self):
        token = _auth.extract_token(raw("antigravity_keychain.json").decode())
        assert token is not None
        self.assertEqual(token.access_token, "test-only-access")
        self.assertEqual(token.refresh_token, "test-only-refresh")
        self.assertIsNotNone(token.expiry)
        wrapped = "go-keyring-base64:" + base64.b64encode(
            b'{"token": {"access_token": "test-only-w"}}').decode()
        self.assertEqual(_auth.extract_token(wrapped).access_token, "test-only-w")  # type: ignore[union-attr]
        self.assertEqual(
            _auth.extract_token("Bearer test-only-b").access_token,  # type: ignore[union-attr]
            "test-only-b")
        self.assertEqual(
            _auth.extract_token("test-only-bare").access_token,  # type: ignore[union-attr]
            "test-only-bare")
        self.assertEqual(
            _auth.extract_token('"test-only-str"').access_token,  # type: ignore[union-attr]
            "test-only-str")
        self.assertIsNone(_auth.extract_token('{"broken'))
        self.assertIsNone(_auth.extract_token(""))
        self.assertIsNone(_auth.extract_token("   "))

    def test_nested_oauth(self):
        token = _auth.token_from_object(
            {"oauth": {"access_token": "test-only-n", "refresh_token": "test-only-r"}})
        assert token is not None
        self.assertEqual(token.access_token, "test-only-n")
        self.assertIsNone(_auth.token_from_object({"nothing": 1}))

    def test_cache_round_trip(self):
        _auth.discard_cached_token()
        now = support.NOW
        _auth.cache_token("test-only-fresh", 3600, "test-only-r", now)
        self.assertEqual(
            _auth.load_cached_token("test-only-r", now), "test-only-fresh")
        self.assertIsNone(_auth.load_cached_token("test-only-other", now))
        late = now + dt.timedelta(seconds=7200)
        self.assertIsNone(_auth.load_cached_token("test-only-r", late))
        _auth.cache_token("test-only-fresh", 3600, "test-only-r", now)
        _auth.discard_cached_token("test-only-r")
        self.assertIsNone(_auth.load_cached_token("test-only-r", now))

    def test_usable(self):
        now = support.NOW
        self.assertTrue(_auth.is_usable(None, now))
        self.assertTrue(_auth.is_usable(now + dt.timedelta(seconds=61), now))
        self.assertFalse(_auth.is_usable(now + dt.timedelta(seconds=59), now))


class DiscoveryTest(unittest.TestCase):
    def test_match_process(self):
        self.assertTrue(_ls.match_process(["language_server", "--x"], "language_server"))
        self.assertTrue(_ls.match_process(
            ["/opt/ide/language_server_next", "--x"], "language_server"))
        self.assertTrue(_ls.match_process(["/usr/bin/agy", "--x"], "agy"))
        self.assertFalse(_ls.match_process(["agy-helper"], "agy"))
        self.assertFalse(_ls.match_process(["other"], "agy"))
        self.assertFalse(_ls.match_process([], "agy"))

    def test_extract_flag(self):
        args = ["bin", "--csrf_token", "abc", "--port=777"]
        self.assertEqual(_ls.extract_flag(args, "--csrf_token"), "abc")
        self.assertEqual(_ls.extract_flag(args, "--port"), "777")
        self.assertIsNone(_ls.extract_flag(args, "--missing"))

    def test_marker_rank(self):
        self.assertEqual(_ls.marker_rank(["a"], []), 0)
        self.assertEqual(
            _ls.marker_rank(["b", "--ide_name", "antigravity"], ["antigravity"]), 0)
        self.assertIsNone(
            _ls.marker_rank(["b", "--ide_name", "other"], ["antigravity"]))
        self.assertEqual(
            _ls.marker_rank(["/opt/antigravity/bin/x"], ["antigravity"]), 1)
        self.assertIsNone(_ls.marker_rank(["/opt/other/bin/x"], ["antigravity"]))

    def write_proc(self, root: Path, pid: int, argv: list[str],
                   listeners: dict[int, int] | None = None) -> None:
        proc = root / str(pid)
        (proc / "fd").mkdir(parents=True)
        (proc / "cmdline").write_bytes(
            b"\0".join(item.encode() for item in argv) + b"\0")
        if listeners:
            lines = ["  sl  local_address rem_address   st tx_queue rx_queue tr "
                     "tm->when retrnsmt   uid  timeout inode"]
            for fd_number, (port, inode) in enumerate(listeners.items()):
                lines.append(
                    f"   0: 0100007F:{port:04X} 00000000:0000 0A 00000000:00000000 "
                    f"00:00000000 00000000  1000        0 {inode} 1 0000000000000000 "
                    f"100 0 0 10 0")
                os.symlink(f"socket:[{inode}]", proc / "fd" / str(3 + fd_number))
            (root / "net").mkdir(exist_ok=True)
            (root / "net" / "tcp").write_text("\n".join(lines) + "\n")

    def test_discover_fake_proc(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proc"
            self.write_proc(root, 4242,
                            ["language_server", "--ide_name", "antigravity",
                             "--csrf_token", "test-only-csrf",
                             "--extension_server_port", "7777"],
                            listeners={51000: 9999})
            found = _ls.discover("language_server", ["antigravity"],
                                 "--csrf_token", "--extension_server_port",
                                 proc_root=str(root))
            assert found is not None
            self.assertEqual(found.pid, 4242)
            self.assertEqual(found.csrf, "test-only-csrf")
            self.assertEqual(found.ports, (51000,))
            self.assertEqual(found.extension_port, 7777)
            self.assertEqual(_ls.listening_ports(4242, str(root)), [51000])

    def test_discover_skips_portless(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "proc"
            self.write_proc(root, 100, ["agy"])
            self.assertIsNone(_ls.discover("agy", [], "", None, proc_root=str(root)))
            self.assertIsNone(_ls.discover("nope", [], "", None, proc_root=str(root)))


class MapperTest(unittest.TestCase):
    def test_quota_summary(self):
        lines = _mapper.parse_quota_summary(raw("antigravity_summary.json"))
        assert lines is not None
        self.assertEqual(lines["geminiPro"].used, 25.0)
        self.assertEqual(lines["geminiWeekly"].used, 50.0)
        self.assertEqual(lines["claude"].used, 0.0)
        self.assertEqual(lines["claudeWeekly"].used, 10.0)
        self.assertEqual(lines["geminiPro"].period_ms, _mapper.SESSION_MS)
        self.assertEqual(lines["geminiWeekly"].period_ms, _mapper.WEEK_MS)
        self.assertIsNotNone(lines["geminiPro"].resets_at)

    def test_summary_variants(self):
        bare = {"groups": [{"buckets": [
            {"bucketId": "gemini-5h", "remainingFraction": 0.5},
            {"bucketId": "gemini-image-5h", "remainingFraction": 0.1},
            {"bucketId": "3p-5h"},
        ]}]}
        with self.assertLogs("openusage_omarchy.plugin.antigravity", level="WARNING"):
            lines = _mapper.parse_quota_summary(json.dumps(bare).encode())
        assert lines is not None
        self.assertEqual(list(lines), ["geminiPro"])
        self.assertEqual(_mapper.parse_quota_summary(b'{"groups": []}'), {})
        self.assertIsNone(_mapper.parse_quota_summary(b"{}"))
        self.assertIsNone(_mapper.parse_quota_summary(b"broken"))
        self.assertIsNone(_mapper.parse_quota_summary(b'{"groups": [7]}'))

    def test_user_status(self):
        parsed = _mapper.parse_user_status(raw("antigravity_user_status.json"))
        assert parsed is not None
        plan, configs = parsed
        self.assertEqual(plan, "Pro")
        self.assertEqual(len(configs), 3)
        self.assertIsNone(_mapper.parse_user_status(b"{}"))
        lines = _mapper.build_lines(configs)
        self.assertEqual(lines["geminiPro"].used, 80.0)
        self.assertEqual(lines["claude"].used, 60.0)

    def test_legacy_sources(self):
        models = _mapper.parse_cloud_models(raw("antigravity_models.json"))
        self.assertEqual(len(models), 2)
        lines = _mapper.build_lines(models)
        self.assertEqual(lines["geminiPro"].used, 70.0)
        self.assertEqual(
            _mapper.parse_plan(raw("antigravity_load.json")), "Pro")
        self.assertEqual(
            _mapper.parse_project(raw("antigravity_load.json")),
            "test-only-project")
        buckets = _mapper.parse_quota_buckets(
            b'{"buckets": [{"modelId": "gemini-3-pro-preview", '
            b'"remainingFraction": 0.25}]}')
        self.assertEqual(len(buckets), 1)
        configs = _mapper.parse_command_configs(
            b'{"clientModelConfigs": [{"label": "Gemini X", '
            b'"quotaInfo": {"remainingFraction": 0.5}}]}')
        assert configs is not None
        self.assertEqual(len(configs), 1)
        self.assertIsNone(_mapper.parse_command_configs(b"{}"))

    def test_pool_helpers(self):
        self.assertEqual(_mapper.normalize_label("Gemini 3 Pro (High)"), "Gemini 3 Pro")
        self.assertEqual(_mapper.pool_metric("Gemini Flash"), "geminiPro")
        self.assertEqual(_mapper.pool_metric("GPT-OSS"), "claude")
        self.assertEqual(
            _mapper.format_plan("Gemini Code Assist in Google One AI Pro"), "Pro")
        self.assertEqual(_mapper.format_plan("Some Ultra Tier"), "Ultra")
        self.assertIsNone(_mapper.format_plan("   "))
        lines = _mapper.build_lines(
            [("x", "MODEL_CHAT_20706", 0.0, None), ("", "m", 0.0, None)])
        self.assertEqual(lines, {})


TEST_CLIENT = {
    _cloud.CLIENT_ID_ENV: "test-only-client",
    _cloud.CLIENT_SECRET_ENV: "test-only-secret",
}


class OAuthClientTest(unittest.TestCase):
    def test_env_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(
                _cloud.oauth_client(Path(tmp), TEST_CLIENT),
                ("test-only-client", "test-only-secret"))

    def test_private_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / _cloud.CLIENT_FILE
            path.write_text(json.dumps(
                {"client_id": "test-only-client", "client_secret": "test-only-secret"}))
            path.chmod(0o600)
            self.assertEqual(_cloud.oauth_client(Path(tmp), {}),
                             ("test-only-client", "test-only-secret"))
            path.chmod(0o644)
            self.assertIsNone(_cloud.oauth_client(Path(tmp), {}))

    def test_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_cloud.oauth_client(Path(tmp), {}))

    def test_no_bundled_client(self):
        source = Path(_cloud.__file__).read_text(encoding="utf-8")
        self.assertNotIn("GOC" + "SPX-", source)
        self.assertNotIn(".apps.googleusercontent.com", source)


class FetchTest(unittest.TestCase):
    def setUp(self):
        _auth.discard_cached_token()

    def tearDown(self):
        _auth.discard_cached_token()

    def test_cloud_round_trip(self):
        blob = raw("antigravity_keychain.json").decode()
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, blob)):
                assert isinstance(env.http, support.FakeHttp)
                base = _cloud.BASES[0]
                env.http.add("POST", base + _cloud.QUOTA_SUMMARY_PATH, 200,
                             raw("antigravity_summary.json"))
                env.http.add("POST", base + _cloud.LOAD_CODE_ASSIST_PATH, 200,
                             raw("antigravity_load.json"))
                self.assertTrue(antigravity.has_credentials(env))
                snap = antigravity.fetch(antigravity.cards(env)[0], env)
                self.assertEqual(snap.plan, "Pro")
                self.assertEqual(snap.metrics["geminiPro"].used, 25.0)
                self.assertEqual(snap.metrics["claudeWeekly"].used, 10.0)

    def test_legacy_models_fallback(self):
        blob = raw("antigravity_keychain.json").decode()
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, blob)):
                assert isinstance(env.http, support.FakeHttp)
                for base in _cloud.BASES:
                    env.http.add("POST", base + _cloud.QUOTA_SUMMARY_PATH, 404, b"{}")
                env.http.add("POST", _cloud.BASES[0] + _cloud.FETCH_MODELS_PATH,
                             200, raw("antigravity_models.json"))
                env.http.add("POST", _cloud.BASES[0] + _cloud.LOAD_CODE_ASSIST_PATH,
                             200, raw("antigravity_load.json"))
                snap = antigravity.fetch(antigravity.cards(env)[0], env)
                self.assertIn("geminiPro", snap.metrics)
                self.assertNotIn("geminiWeekly", snap.metrics)

    def test_expired_access_refreshes(self):
        blob = json.dumps({"token": {"access_token": "test-only-old",
                                     "refresh_token": "test-only-r",
                                     "expiry": "2000-01-01T00:00:00Z"}})
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, {**shim_env(tmp, blob), **TEST_CLIENT}):
                assert isinstance(env.http, support.FakeHttp)
                env.http.add_json("POST", _cloud.OAUTH_URL,
                                  {"access_token": "test-only-fresh",
                                   "expires_in": 3600})
                base = _cloud.BASES[0]
                env.http.add("POST", base + _cloud.QUOTA_SUMMARY_PATH, 200,
                             raw("antigravity_summary.json"))
                env.http.add("POST", base + _cloud.LOAD_CODE_ASSIST_PATH, 200,
                             raw("antigravity_load.json"))
                snap = antigravity.fetch(antigravity.cards(env)[0], env)
                self.assertEqual(snap.metrics["geminiPro"].used, 25.0)
                self.assertEqual(
                    _auth.load_cached_token("test-only-r", support.NOW),
                    "test-only-fresh")

    def test_expired_without_client_skips_refresh(self):
        blob = json.dumps({"token": {"access_token": "test-only-old",
                                     "refresh_token": "test-only-r",
                                     "expiry": "2000-01-01T00:00:00Z"}})
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, blob)):
                assert isinstance(env.http, support.FakeHttp)
                for key in TEST_CLIENT:
                    os.environ.pop(key, None)
                with self.assertRaises(model.CollectorError) as ctx:
                    antigravity.fetch(antigravity.cards(env)[0], env)
                self.assertEqual(ctx.exception.category, "auth")
                self.assertFalse(any(
                    call[1] == _cloud.OAUTH_URL for call in env.http.calls))

    def test_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, None)):
                self.assertFalse(antigravity.has_credentials(env))
                with self.assertRaises(model.CollectorError) as ctx:
                    antigravity.fetch(antigravity.cards(env)[0], env)
                self.assertEqual(ctx.exception.category, "auth")

    def test_failures(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, '{"broken"')):
                self.assertTrue(antigravity.has_credentials(env))
                with self.assertRaises(model.CollectorError) as ctx:
                    antigravity.fetch(antigravity.cards(env)[0], env)
                self.assertIn("invalid", ctx.exception.message)
        blob = raw("antigravity_keychain.json").decode()
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, blob)):
                assert isinstance(env.http, support.FakeHttp)
                for base in _cloud.BASES:
                    env.http.add("POST", base + _cloud.QUOTA_SUMMARY_PATH, 401, b"{}")
                env.http.add("POST", _cloud.OAUTH_URL, 400, b"{}")
                with self.assertRaises(model.CollectorError) as ctx:
                    antigravity.fetch(antigravity.cards(env)[0], env)
                self.assertEqual(ctx.exception.category, "auth")
                self.assertIn("expired", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
