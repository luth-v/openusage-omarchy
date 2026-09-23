"""Live install findings L1-L6 (first real run, 2026-09-23). One class each."""

import datetime as dt
import json
import logging
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import catalog, http as _http, layout, log, model, paths
from openusage_omarchy.daemon import main as _daemon
from openusage_omarchy.engine import cache, refresh as engine
from openusage_omarchy.providers import copilot
from openusage_omarchy.providers import grok as _grok
from openusage_omarchy.providers import opencode as _opencode
from openusage_omarchy.providers.copilot import auth as _copilot_auth
from openusage_omarchy.spend import opencode_scan as _oc_scan
from openusage_omarchy.spend import pricing_store as _store

import support


def _card(family="cursor"):
    return model.CardRef(card_id=family, family=family, label=family.title())


def _quota(family="cursor"):
    return model.Snapshot(
        card=_card(family), plan="Pro", fetched_at=support.NOW.isoformat(),
        metrics={"auto": model.Progress(metric_id="auto", used=40, limit=100)})


def _today():
    return model.Values(
        metric_id="today",
        values=(model.ScalarValue(number=1.5, kind="dollars", label="cost"),))


class _SpendStub:
    """Fast quota fetch, slow spend attach."""

    family = "cursor"

    def __init__(self, spend_delay=1.0):
        self.spend_delay = spend_delay
        self.attached = 0

    def cards(self, env):
        return [_card()]

    def fetch(self, card, env):
        return _quota()

    def has_credentials(self, env):
        return True

    def attach_spend(self, card, env, snap, now):
        time.sleep(self.spend_delay)
        self.attached += 1
        metrics = dict(snap.metrics)
        metrics["today"] = _today()
        return model.Snapshot(card=snap.card, plan=snap.plan,
                              fetched_at=snap.fetched_at, metrics=metrics)


def _make_daemon(env, collectors):
    daemon = _daemon.Daemon(env.paths)
    daemon.env = env
    daemon.collectors = collectors
    daemon.key_sources = daemon._read_key_sources()
    daemon.detected = {"cursor": True}
    daemon.session_id = "session-1"
    return daemon


def _join(daemon):
    for thread in daemon._spend_threads:
        thread.join(timeout=15)
    _store.Store.join_background()


class L1QuotaNeverWaitsOnSpendTest(unittest.TestCase):
    def test_slow_pricing_never_blocks_current(self):
        class SlowHttp(support.FakeHttp):
            def get(self, url, headers=None, timeout=10):
                time.sleep(3.0)
                return super().get(url, headers, timeout)

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            http = SlowHttp()
            lite = {"m": {"input_cost_per_token": 1e-6,
                           "output_cost_per_token": 2e-6}}
            http.add("GET", _store.LITELLM_URL, 200, json.dumps(lite).encode())
            http.add("GET", _store.MODELS_DEV_URL, 200, b"{}")
            http.add("GET", _store.SUPPLEMENT_URL, 200,
                     json.dumps({"pricing": {}, "alias_rules": []}).encode())
            store = _store.Store(env.paths.pricing_dir, http)
            try:
                started = time.monotonic()
                pricing = store.current()
                self.assertLess(time.monotonic() - started, 2.0)
                # Bundled data serves first; the fetch lands afterwards.
                self.assertGreater(len(pricing.primary.entries), 100)
                _store.Store.join_background(timeout=30)
                self.assertIn("m", _store.Store(
                    env.paths.pricing_dir, None).current().primary.entries)
            finally:
                _store.Store.join_background()

    def test_slow_spend_never_trips_quota_deadline(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            stub = _SpendStub(spend_delay=3.0)
            started = time.monotonic()
            batch = engine.refresh([stub], env, "s", deadline=0.5)
            self.assertLess(time.monotonic() - started, 2.0)
            result = batch.results[0]
            self.assertIsNone(result.error)
            assert result.snapshot is not None
            self.assertIn("auto", result.snapshot.metrics)
            self.assertNotIn("today", result.snapshot.metrics)
            # Overrun keeps quota; budget lets spend attach.
            poor = engine.attach_spend(batch, [stub], env, "s", deadline=0.2)
            assert poor.results[0].snapshot is not None
            self.assertNotIn("today", poor.results[0].snapshot.metrics)
            rich = engine.attach_spend(batch, [stub], env, "s", deadline=10)
            assert rich.results[0].snapshot is not None
            self.assertIn("today", rich.results[0].snapshot.metrics)
            self.assertEqual(rich.generation, batch.generation)

    def test_quota_publishes_before_spend(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = _make_daemon(env, [_SpendStub(spend_delay=1.0)])
            daemon._run_batch(force=True, families=None)
            try:
                first = json.loads(daemon.dirs.state_file.read_text())
                by_id = {card["cardId"]: card for card in first["cards"]}
                self.assertIn("auto", by_id["cursor"]["metrics"])
                self.assertNotIn("today", by_id["cursor"]["metrics"])
                self.assertEqual(first["refresh"]["inFlight"], [])
                self.assertIsNotNone(first["refresh"]["nextAt"])
                self.assertIsNotNone(first["refresh"]["lastBatchEndedAt"])
                _join(daemon)
                second = json.loads(daemon.dirs.state_file.read_text())
                by_id = {card["cardId"]: card for card in second["cards"]}
                self.assertIn("today", by_id["cursor"]["metrics"])
            finally:
                _join(daemon)

    def test_spend_failure_keeps_quota(self):
        class Broken(_SpendStub):
            def attach_spend(self, card, env, snap, now):
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            batch = engine.refresh([Broken(spend_delay=0)], env, "s")
            rich = engine.attach_spend(batch, [Broken(spend_delay=0)], env, "s")
            assert rich.results[0].snapshot is not None
            self.assertIn("auto", rich.results[0].snapshot.metrics)


class L2BatchAlwaysSettlesTest(unittest.TestCase):
    def test_timeout_batch_clears_inflight_and_schedules(self):
        class Slow:
            family = "cursor"

            def cards(self, env):
                return [_card()]

            def fetch(self, card, env):
                time.sleep(1.0)
                return _quota()

            def has_credentials(self, env):
                return True

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = _make_daemon(env, [Slow()])
            real = engine.refresh
            with patch("openusage_omarchy.engine.refresh.refresh",
                       side_effect=lambda *a, **k: real(*a, deadline=0.2, **k)):
                daemon._run_batch(force=True, families=None)
            try:
                state = json.loads(daemon.dirs.state_file.read_text())
                self.assertEqual(state["refresh"]["inFlight"], [])
                self.assertIsNotNone(state["refresh"]["nextAt"])
                self.assertIsNotNone(state["refresh"]["lastBatchEndedAt"])
                self.assertIsNotNone(daemon.next_at)
                by_id = {card["cardId"]: card for card in state["cards"]}
                self.assertEqual(by_id["cursor"]["error"]["category"], "timeout")
            finally:
                _join(daemon)
                time.sleep(1.2)  # let the abandoned fetch drain

    def test_refresh_exception_still_publishes(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = _make_daemon(env, [_SpendStub(spend_delay=0)])
            with patch("openusage_omarchy.engine.refresh.refresh",
                       side_effect=RuntimeError("boom")):
                daemon._run_batch(force=True, families=None)
            try:
                state = json.loads(daemon.dirs.state_file.read_text())
                self.assertEqual(state["refresh"]["inFlight"], [])
                self.assertIsNotNone(state["refresh"]["nextAt"])
                self.assertIsNotNone(state["refresh"]["lastBatchEndedAt"])
            finally:
                _join(daemon)

    def test_broken_cache_never_fails_batch(self):
        class Fail:
            family = "cursor"

            def cards(self, env):
                return [_card()]

            def fetch(self, card, env):
                raise model.CollectorError("transport", "offline")

            def has_credentials(self, env):
                return True

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with patch("openusage_omarchy.engine.cache.read",
                       side_effect=OSError("boom")):
                batch = engine.refresh([Fail()], env, "s")
            result = batch.results[0]
            self.assertIsNone(result.snapshot)
            assert result.error is not None
            self.assertEqual(result.error.category, "transport")
            self.assertIsNotNone(batch.ended_at)


class L3LateResultsDropAndRetryTest(unittest.TestCase):
    def test_timeout_drops_but_next_pass_recovers(self):
        # Upstream-equivalent: a timed-out provider's late snapshot is
        # dropped (never published partial), and the next scheduled batch
        # retries it. See WidgetDataStore.ProviderRefreshDeadline.
        calls = []

        class Flaky:
            family = "cursor"

            def cards(self, env):
                return [_card()]

            def fetch(self, card, env):
                calls.append(1)
                if len(calls) == 1:
                    time.sleep(1.0)
                    return _quota()
                snap = _quota()
                metrics = dict(snap.metrics)
                metrics["auto"] = model.Progress(
                    metric_id="auto", used=99, limit=100)
                return model.Snapshot(card=snap.card, plan=snap.plan,
                                      fetched_at=snap.fetched_at,
                                      metrics=metrics)

            def has_credentials(self, env):
                return True

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            first = engine.refresh([Flaky()], env, "s", deadline=0.2)
            assert first.results[0].error is not None
            self.assertEqual(first.results[0].error.category, "timeout")
            self.assertIsNone(first.results[0].snapshot)
            time.sleep(1.2)  # the late thread finishes; it must not publish
            self.assertIsNone(cache.read(
                env.paths.snapshots_dir, _card(), support.NOW))
            second = engine.refresh([Flaky()], env, "s", deadline=5)
            assert second.results[0].snapshot is not None
            self.assertIsNone(second.results[0].error)
            self.assertEqual(
                second.results[0].snapshot.metrics["auto"].used, 99)


class L4DetectionFindsLoginsTest(unittest.TestCase):
    def _db(self, path, hosted=True):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE message (time_created INTEGER, data TEXT)")
        if hosted:
            data = {"role": "assistant", "providerID": "opencode",
                    "cost": 0.25, "tokens": {"total": 15},
                    "modelID": "test-only-m"}
            conn.execute("INSERT INTO message VALUES (?,?)",
                         (1_786_000_000_000, json.dumps(data)))
        conn.commit()
        conn.close()

    def test_opencode_db_usage_detects_without_key(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            data = _opencode.data_dir(env)
            data.mkdir(parents=True)
            self._db(data / "opencode-test-only.db", hosted=True)
            self.assertTrue(_opencode.has_credentials(env))

    def test_opencode_empty_db_without_key_stays_off(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            data = _opencode.data_dir(env)
            data.mkdir(parents=True)
            self._db(data / "opencode-test-only.db", hosted=False)
            self.assertFalse(_opencode.has_credentials(env))

    def test_opencode_unreadable_dir_counts_as_footprint(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            data = _opencode.data_dir(env)
            data.mkdir(parents=True)
            try:
                data.chmod(0o000)
                self.assertTrue(_oc_scan.has_hosted_usage(data))
                self.assertTrue(_opencode.has_credentials(env))
            finally:
                data.chmod(0o700)

    def test_grok_keyed_entry_detects(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = Path(tmp) / "home" / ".grok"
            home.mkdir(parents=True)
            (home / "auth.json").write_text(json.dumps({
                "https://test-only::client": {
                    "key": "test-only-access",
                    "refresh_token": "test-only-refresh",
                    "expires_at": "2027-01-01T00:00:00.000Z"}}))
            self.assertTrue(_grok.has_credentials(env))

    def test_copilot_hosts_token_detects(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            path = _copilot_auth.gh_hosts_path(env)
            path.parent.mkdir(parents=True)
            path.write_text("github.com:\n    oauth_token: test-only-t\n")
            self.assertTrue(copilot.has_credentials(env))
            # No token anywhere (file without one, empty keyring): off.
            path.write_text("github.com:\n    user: test-only-u\n"
                            "    git_protocol: https\n")
            self.assertFalse(copilot.has_credentials(env))

    def test_first_run_switches_to_exactly_detected(self):
        table = catalog.cached()
        cards = [model.CardRef(item.provider_id, item.provider_id,
                               item.display_name) for item in table.providers]
        found = {"grok": True, "opencode": True, "copilot": True}
        self.assertEqual(layout.enabled_card_ids(None, found, table, cards),
                         {"grok", "opencode", "copilot"})
        self.assertEqual(layout.enabled_card_ids(None, {}, table, cards),
                         {"claude", "codex", "cursor"})


class L5UserAgentTest(unittest.TestCase):
    class _Reply:
        status = 200

        def read(self):
            return b"{}"

        def getheaders(self):
            return []

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def _capture(self, headers):
        seen = {}

        def fake_open(req, timeout=None):
            seen.update({str(key).lower(): value
                         for key, value in req.headers.items()})
            return L5UserAgentTest._Reply()

        with patch("urllib.request.urlopen", side_effect=fake_open):
            _http.Http().get("https://example.test/x", headers=headers)
        return seen

    def test_default_user_agent_is_versioned(self):
        seen = self._capture(None)
        self.assertEqual(
            seen.get("user-agent"),
            f"openusage-omarchy/{catalog.manifest_version()}")

    def test_explicit_user_agent_is_preserved(self):
        seen = self._capture({"User-Agent": "claude-cli/2.1.280 (external, cli)"})
        self.assertEqual(seen.get("user-agent"),
                         "claude-cli/2.1.280 (external, cli)")


class L6PrivateFilesTest(unittest.TestCase):
    def test_harden_tightens_dirs_and_files(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            dirs = env.paths
            for directory in (dirs.state_dir, dirs.cache_dir):
                directory.mkdir(parents=True, exist_ok=True)
                directory.chmod(0o755)
            nested = dirs.scan_dir / "test-only-ns"
            nested.mkdir(parents=True, exist_ok=True)
            nested.chmod(0o755)
            files = [dirs.state_file, dirs.layout_file, dirs.log_file,
                     dirs.pricing_dir / "test-only.json",
                     dirs.snapshots_dir / "test-only.json",
                     nested / "test-only.json"]
            for path in files:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("{}\n")
                path.chmod(0o644)
            paths.harden(dirs)
            for directory in (dirs.state_dir, dirs.cache_dir,
                              dirs.snapshots_dir, dirs.pricing_dir,
                              dirs.scan_dir, nested):
                self.assertEqual(directory.stat().st_mode & 0o777, 0o700,
                                 str(directory))
            for path in files:
                self.assertEqual(path.stat().st_mode & 0o777, 0o600,
                                 str(path))

    def test_runtime_files_retighten_after_rewrite(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            env.paths.layout_file.parent.mkdir(parents=True, exist_ok=True)
            env.paths.layout_file.write_text("{}\n")
            env.paths.layout_file.chmod(0o644)
            paths.harden_runtime_files(env.paths)
            self.assertEqual(
                env.paths.layout_file.stat().st_mode & 0o777, 0o600)

    def test_log_setup_writes_private_log(self):
        root = logging.getLogger("openusage_omarchy")
        saved_handlers, saved_level = list(root.handlers), root.level
        with tempfile.TemporaryDirectory() as tmp:
            try:
                target = Path(tmp) / "test-only.log"
                target.write_text("old\n")
                target.chmod(0o644)
                log.setup("info", target)
                self.assertEqual(target.stat().st_mode & 0o777, 0o600)
            finally:
                for handler in list(root.handlers):
                    try:
                        handler.close()
                    except (OSError, ValueError):
                        pass
                    root.removeHandler(handler)
                for handler in saved_handlers:
                    root.addHandler(handler)
                root.setLevel(saved_level)


if __name__ == "__main__":
    unittest.main()
