"""Engine: freshness, stale-while-revalidate, deadline, session rules."""

import datetime as dt
import tempfile
import time
import unittest

from openusage_omarchy import model
from openusage_omarchy.engine import cache, refresh as engine

import support


def card(family: str = "cursor") -> model.CardRef:
    return model.CardRef(card_id=family, family=family, label=family.title())


def snap(family: str = "cursor", used: float = 40) -> model.Snapshot:
    return model.Snapshot(
        card=card(family),
        plan="Pro",
        fetched_at=support.NOW.isoformat(),
        metrics={"auto": model.Progress(metric_id="auto", used=used, limit=100)},
    )


class StubCollector:
    family = "cursor"

    def __init__(self, action=None) -> None:
        self.action = action or (lambda c, e: snap())
        self.calls = 0

    def cards(self, env):
        return [card()]

    def fetch(self, card, env):
        self.calls += 1
        return self.action(card, env)

    def has_credentials(self, env):
        return True


class EngineTest(unittest.TestCase):
    def test_fresh_cache_skips_fetch(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            cache.write(env.paths.snapshots_dir, snap(), "session-1", support.NOW)
            stub = StubCollector()
            batch = engine.refresh([stub], env, "session-1")
            self.assertEqual(stub.calls, 0)
            self.assertTrue(batch.results[0].from_cache)
            self.assertIsNone(batch.results[0].error)

    def test_old_session_refetches(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            cache.write(env.paths.snapshots_dir, snap(), "session-1", support.NOW)
            stub = StubCollector()
            batch = engine.refresh([stub], env, "session-2")
            self.assertEqual(stub.calls, 1)
            self.assertFalse(batch.results[0].from_cache)

    def test_force_bypasses_freshness(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            cache.write(env.paths.snapshots_dir, snap(), "session-1", support.NOW)
            stub = StubCollector()
            batch = engine.refresh([stub], env, "session-1", force=True)
            self.assertEqual(stub.calls, 1)
            self.assertFalse(batch.results[0].from_cache)

    def test_failure_keeps_last_good(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            cache.write(env.paths.snapshots_dir, snap(used=33), "old", support.NOW)

            def fail(card, env):
                raise model.CollectorError("transport", "offline")

            batch = engine.refresh([StubCollector(fail)], env, "new")
            result = batch.results[0]
            assert result.snapshot is not None
            self.assertTrue(result.from_cache)
            self.assertEqual(result.snapshot.metrics["auto"].used, 33)
            assert result.error is not None
            self.assertEqual(result.error.category, "transport")

    def test_failure_without_cache_has_no_data(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            def fail(card, env):
                raise model.CollectorError("auth", "nope")

            batch = engine.refresh([StubCollector(fail)], env, "new")
            result = batch.results[0]
            self.assertIsNone(result.snapshot)
            assert result.error is not None
            self.assertEqual(result.error.category, "auth")

    def test_deadline_drops_late_result(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            def slow(card, env):
                time.sleep(1.0)
                return snap(used=99)

            started = time.monotonic()
            batch = engine.refresh([StubCollector(slow)], env, "new", deadline=0.2)
            self.assertLess(time.monotonic() - started, 0.6)
            result = batch.results[0]
            self.assertIsNone(result.snapshot)
            assert result.error is not None
            self.assertEqual(result.error.category, "timeout")
            time.sleep(1.2)  # let the late thread finish; it must not publish
            self.assertIsNone(cache.read(env.paths.snapshots_dir, card(), support.NOW))

    def test_stale_cache_refetches(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = support.NOW - dt.timedelta(seconds=600)
            with support.test_env(tmp, now=old) as env:
                cache.write(env.paths.snapshots_dir, snap(), "session-1", old)
            with support.test_env(tmp) as env:
                stub = StubCollector()
                batch = engine.refresh([stub], env, "session-1")
                self.assertEqual(stub.calls, 1)
                self.assertFalse(batch.results[0].from_cache)

    def test_wrong_account_cache_miss(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            stored = model.Snapshot(
                card=model.CardRef(card_id="codex:aa", family="codex",
                                   label="Codex", account_key="one"),
                plan="Plus",
                fetched_at=support.NOW.isoformat(),
                metrics={},
            )
            cache.write(env.paths.snapshots_dir, stored, "session-1", support.NOW)
            other = model.CardRef(card_id="codex:aa", family="codex",
                                  label="Codex", account_key="two")
            self.assertIsNone(cache.read(env.paths.snapshots_dir, other, support.NOW))
            empty = model.CardRef(card_id="codex:aa", family="codex", label="Codex")
            entry = cache.read(env.paths.snapshots_dir, empty, support.NOW)
            self.assertIsNotNone(entry)

    def test_snapshot_file_mode(self):
        import os

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            cache.write(env.paths.snapshots_dir, snap(), "s", support.NOW)
            path = cache.snapshot_path(env.paths.snapshots_dir, "cursor")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
