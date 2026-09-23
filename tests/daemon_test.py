"""Daemon key wiring: setKey/deleteKey store keys and refresh one family."""

import json
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from openusage_omarchy import model, secrets
from openusage_omarchy.daemon import commands, main, publish

import support


class DaemonKeysTest(unittest.TestCase):
    def make_daemon(self, env):
        daemon = main.Daemon(env.paths)
        daemon.env = env  # FakeHttp: no network in _run_batch
        daemon.key_sources = daemon._read_key_sources()
        daemon.detected = dict.fromkeys(
            [item.provider_id for item in daemon.table.providers], False)
        return daemon

    def test_read_key_sources(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            self.assertEqual(daemon.key_sources["openrouter"], "none")
            secrets.set_key("openrouter", "test-only-k", env.paths)
            daemon.key_sources = daemon._read_key_sources()
            self.assertEqual(daemon.key_sources["openrouter"], "file")
            self.assertEqual(daemon.key_sources["cursor"], "none")

    def test_set_and_delete_key(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            daemon._change_key(commands.SetKey(
                provider="zai", value="test-only-k"))
            self.assertEqual(
                secrets.get_key("zai", env.paths), "test-only-k")
            self.assertEqual(daemon.key_sources["zai"], "file")
            self.assertTrue(daemon.detected["zai"])
            daemon._change_key(commands.DeleteKey(provider="zai"))
            self.assertIsNone(secrets.get_key("zai", env.paths))
            self.assertFalse(daemon.detected["zai"])

    def test_state_carries_key_presence(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            secrets.set_key("openrouter", "test-only-k", env.paths)
            daemon.key_sources = daemon._read_key_sources()
            state = publish.build(
                daemon.table, None, daemon.detected, "session-1", "0.0",
                support.NOW, [], None, secrets=dict(daemon.key_sources))
            self.assertEqual(state["secrets"]["openrouter"], "file")
            self.assertEqual(state["secrets"]["zai"], "none")
            plain = publish.build(
                daemon.table, None, daemon.detected, "session-1", "0.0",
                support.NOW, [], None)
            self.assertEqual(plain["secrets"]["openrouter"], "none")


class DaemonClaimTest(unittest.TestCase):
    def make_daemon(self, env):
        daemon = main.Daemon(env.paths)
        daemon.env = env
        daemon.key_sources = daemon._read_key_sources()
        daemon.detected = dict.fromkeys(
            [item.provider_id for item in daemon.table.providers], False)
        card = model.CardRef(card_id="codex", family="codex", label="Codex")
        daemon.collectors = [SimpleNamespace(
            family="codex", cards=lambda env: [card])]
        return daemon

    def live_cred(self):
        tokens = SimpleNamespace(access_token="test-only-t",
                                 account_id="test-only-a")
        return SimpleNamespace(usable=True,
                               auth=SimpleNamespace(tokens=tokens))

    def test_claim_outcomes_map_to_status_and_message(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            cases = {
                "success": ("ok", "Reset claimed. Enjoy!"),
                "nothingToReset": (
                    "not_needed", "Your usage doesn't need a reset yet"),
                "noCredit": (
                    "unavailable", "That reset is no longer available"),
                "failed": ("error", "Couldn't reset usage. Please try again."),
            }
            for outcome, (status, message) in cases.items():
                with (
                    patch("openusage_omarchy.providers.codex.reset_claim.claim_for_card",
                          return_value=outcome) as claimed,
                    patch.object(daemon, "_run_batch") as refreshed,
                ):
                    daemon._claim_reset("codex", None, "test-only-request")
                    claimed.assert_called_once()
                    refreshed.assert_called_once_with(
                        force=True, families={"codex"})
                found = daemon._last_claims["codex"]
                self.assertEqual(found["status"], status)
                self.assertEqual(found["message"], message)
                self.assertTrue(found["at"])

    def test_claim_unknown_card_records_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            with patch.object(daemon, "_run_batch") as refreshed:
                daemon._claim_reset("codex:nope", None, None)
                refreshed.assert_not_called()
            self.assertEqual(daemon._last_claims, {})

    def test_claim_without_credentials_records_error(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            with (
                patch("openusage_omarchy.providers.codex.reset_claim.claim_for_card",
                      return_value="failed"),
                patch.object(daemon, "_run_batch") as refreshed,
            ):
                daemon._claim_reset("codex", None, None)
                refreshed.assert_called_once_with(
                    force=True, families={"codex"})
            found = daemon._last_claims["codex"]
            self.assertEqual(found["status"], "error")
            self.assertEqual(
                found["message"], "Couldn't reset usage. Please try again.")

    def test_state_carries_last_claim(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            claimed = {"status": "ok", "message": "Reset claimed. Enjoy!",
                       "at": support.NOW.isoformat()}
            state = publish.build(
                daemon.table, None, daemon.detected, "session-1", "0.0",
                support.NOW, [], None,
                last_claims={"codex": claimed})
            by_id = {card["cardId"]: card for card in state["cards"]}
            self.assertEqual(by_id["codex"]["lastClaim"], claimed)
            self.assertIsNone(by_id["claude"]["lastClaim"])
            plain = publish.build(
                daemon.table, None, daemon.detected, "session-1", "0.0",
                support.NOW, [], None)
            by_id = {card["cardId"]: card for card in plain["cards"]}
            self.assertIsNone(by_id["codex"]["lastClaim"])


class DaemonMergeTest(unittest.TestCase):
    """Family batches merge: other providers keep last-good rows."""

    def make_daemon(self, env):
        daemon = main.Daemon(env.paths)
        daemon.env = env
        daemon.key_sources = daemon._read_key_sources()
        daemon.detected = dict.fromkeys(
            [item.provider_id for item in daemon.table.providers], False)
        return daemon

    def test_family_batch_keeps_other_cards(self):
        from openusage_omarchy.engine.refresh import Batch, CardResult

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            claude = model.CardRef(card_id="claude", family="claude",
                                   label="Claude")
            codex = model.CardRef(card_id="codex", family="codex",
                                  label="Codex")
            old_snap = model.Snapshot(
                card=claude, plan="Pro",
                fetched_at=support.NOW.isoformat(), metrics={})
            new_snap = model.Snapshot(
                card=codex, plan="Pro",
                fetched_at=support.NOW.isoformat(), metrics={})
            daemon.last_batch = Batch(
                generation=1,
                results=[CardResult(card=claude, snapshot=old_snap,
                                    error=None, from_cache=True,
                                    fetched_at=support.NOW),
                         CardResult(card=codex, snapshot=old_snap,
                                    error=None, from_cache=True,
                                    fetched_at=support.NOW)],
                started_at=support.NOW, ended_at=support.NOW)
            fresh = Batch(
                generation=2,
                results=[CardResult(card=codex, snapshot=new_snap,
                                    error=None, from_cache=False,
                                    fetched_at=support.NOW)],
                started_at=support.NOW, ended_at=support.NOW)
            daemon.next_at = support.NOW
            with patch("openusage_omarchy.engine.refresh.refresh",
                       return_value=fresh):
                daemon._run_batch(force=True, families={"codex"})
            self.assertEqual(daemon.next_at, support.NOW)
            assert daemon.last_batch is not None
            by_id = {item.card.card_id: item
                     for item in daemon.last_batch.results}
            self.assertEqual(set(by_id), {"claude", "codex"})
            self.assertIs(by_id["claude"].snapshot, old_snap)
            self.assertIs(by_id["codex"].snapshot, new_snap)
            state = json.loads(daemon.dirs.state_file.read_text(
                encoding="utf-8"))
            cards = {card["cardId"]: card for card in state["cards"]}
            self.assertEqual(cards["claude"]["plan"], "Pro")
            self.assertEqual(cards["codex"]["plan"], "Pro")

    def test_disabled_card_is_not_sent_to_refresh(self):
        from openusage_omarchy.engine.refresh import Batch

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            daemon.detected = {"claude": True, "ollama": True}
            daemon.collectors = [SimpleNamespace(
                family="ollama", cards=lambda unused: [model.CardRef(
                    "ollama", "ollama", "Ollama")])]
            with patch("openusage_omarchy.engine.refresh.refresh",
                       return_value=Batch(generation=1)) as refresh:
                daemon._run_batch(force=False, families=None)
            self.assertEqual(refresh.call_args.kwargs["enabled_ids"], set())

    def test_explicit_refresh_works_before_layout_write_finishes(self):
        from openusage_omarchy.engine.refresh import Batch

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = self.make_daemon(env)
            daemon.collectors = [SimpleNamespace(
                family="ollama", cards=lambda unused: [model.CardRef(
                    "ollama", "ollama", "Ollama")])]
            in_flight = []
            def fetched(*args, **kwargs):
                in_flight.extend(daemon.in_flight)
                return Batch(generation=1)
            with patch("openusage_omarchy.engine.refresh.refresh",
                       side_effect=fetched) as refresh:
                daemon._run_batch(force=True, families={"ollama"},
                                  requested_card_id="ollama")
            self.assertEqual(refresh.call_args.kwargs["enabled_ids"], {"ollama"})
            self.assertEqual(in_flight, ["ollama"])


class CadenceTest(unittest.TestCase):
    def test_shell_setting_change_reconciles_without_command(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = main.Daemon(env.paths)
            path = env.paths.shell_json
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps({"plugins": [{
                "id": "luth-v.openusage-omarchy", "logLevel": "Debug",
                "shortcut": "Super+O"}]}))
            with (patch("openusage_omarchy.daemon.main._shortcut.reconcile") as bind,
                  patch("openusage_omarchy.daemon.main.log.set_level") as level,
                  patch("openusage_omarchy.daemon.main._update.reconcile_hook")):
                daemon._reconcile_if_changed()
            bind.assert_called_once_with(env.paths, "Super+O")
            level.assert_called_once_with("Debug")
            self.assertFalse(daemon.settings.changed())

    def test_command_does_not_restart_full_refresh_clock(self):
        import datetime as dt
        import queue

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            daemon = main.Daemon(env.paths)
            moment = [support.NOW]
            timeouts = []
            calls = []

            def batch(force, families):
                calls.append(families)
                if families is None:
                    daemon.next_at = moment[0] + dt.timedelta(seconds=300)

            class Inbox:
                count = 0

                def get(self, timeout):
                    timeouts.append(timeout)
                    self.count += 1
                    if self.count == 1:
                        moment[0] += dt.timedelta(seconds=10)
                        return commands.CheckUpdate()
                    if self.count == 2:
                        return None
                    raise queue.Empty

            daemon._commands = Inbox()
            with (patch.object(main, "_utcnow", side_effect=lambda: moment[0]),
                  patch.object(daemon, "_run_batch", side_effect=batch),
                  patch.object(daemon, "_maybe_update_check"),
                  patch.object(daemon, "_reconcile_if_changed")):
                daemon._worker()
            self.assertEqual(calls, [None])
            self.assertEqual(timeouts, [5.0, 5.0])
            self.assertEqual((daemon.next_at - moment[0]).total_seconds(), 290)


if __name__ == "__main__":
    unittest.main()
