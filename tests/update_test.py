"""Update checks: version compare, channels, backoff, hook, installable."""

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import paths, update

import support

NOW = support.NOW


def releases():
    return [
        {"tag_name": "v0.3.0-beta.1", "prerelease": True, "draft": False},
        {"tag_name": "v0.2.0", "prerelease": False, "draft": False},
        {"tag_name": "v0.2.1-draft", "prerelease": False, "draft": True},
        {"tag_name": "v0.1.0", "prerelease": False, "draft": False},
    ]


class VersionTest(unittest.TestCase):
    def test_parse(self):
        self.assertEqual(update.parse_version("v0.9.0-beta.1"), (0, 9, 0))
        self.assertEqual(update.parse_version("1.2"), (1, 2))
        self.assertEqual(update.parse_version("nope"), (0,))

    def test_is_newer(self):
        self.assertTrue(update.is_newer("v0.2.0", "0.1.0"))
        self.assertTrue(update.is_newer("0.2", "0.1.9"))
        self.assertFalse(update.is_newer("v0.1.0", "0.1.0"))
        self.assertFalse(update.is_newer("v0.1.0", "0.2.0"))

    def test_select_latest(self):
        self.assertEqual(update.select_latest(releases(), False), "v0.2.0")
        self.assertEqual(update.select_latest(releases(), True), "v0.3.0-beta.1")
        self.assertIsNone(update.select_latest([], False))


class CheckTest(unittest.TestCase):
    def test_check_sets_latest(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            env.http.add_json("GET", update.RELEASES_URL, releases())
            state = update.UpdateState(installable=True)
            update.run_check(env.http, state, "0.1.0", False, NOW, force=True)
            self.assertEqual(state.latest, "v0.2.0")
            self.assertEqual(state.channel, "stable")
            self.assertEqual(state.checked_at, NOW.isoformat())
            self.assertIsNone(state.not_before)

    def test_current_clears_latest(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            env.http.add_json("GET", update.RELEASES_URL, releases())
            state = update.UpdateState(latest="v0.2.0", installable=True)
            update.run_check(env.http, state, "0.2.0", False, NOW, force=True)
            self.assertIsNone(state.latest)

    def test_rate_limit_backs_off(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            env.http.add("GET", update.RELEASES_URL, 403, b"{}",
                         {"Retry-After": "120"})
            state = update.UpdateState(installable=True)
            update.run_check(env.http, state, "0.1.0", False, NOW, force=True)
            self.assertIsNone(state.latest)
            self.assertIsNotNone(state.not_before)
            self.assertFalse(update.due(state, True, NOW))

    def test_hourly_due(self):
        fresh = update.UpdateState(checked_at=NOW.isoformat())
        self.assertFalse(update.due(fresh, True, NOW))
        self.assertFalse(update.due(fresh, False, NOW))
        old = update.UpdateState(
            checked_at=(NOW - dt.timedelta(hours=2)).isoformat())
        self.assertTrue(update.due(old, True, NOW))
        self.assertFalse(update.due(old, False, NOW))

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            state = update.UpdateState(latest="v0.2.0", channel="beta",
                                       checked_at=NOW.isoformat(),
                                       snoozed="v0.2.0", installable=True)
            update.save_state(env.paths, state)
            back = update.load_state(env.paths, True)
            self.assertEqual(back.latest, "v0.2.0")
            self.assertEqual(back.channel, "beta")
            self.assertEqual(back.snoozed, "v0.2.0")

    def test_transport_error_keeps_state(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            state = update.UpdateState(installable=True)
            update.run_check(env.http, state, "0.1.0", False, NOW, force=True)
            self.assertIsNone(state.latest)
            self.assertIsNone(state.checked_at)

    def test_successful_check_rearms_snooze(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            env.http.add_json("GET", update.RELEASES_URL, releases())
            state = update.UpdateState(snoozed="v0.2.0", installable=True)
            update.run_check(env.http, state, "0.1.0", False, NOW, force=True)
            self.assertEqual(state.latest, "v0.2.0")
            self.assertIsNone(state.snoozed)


class HookTest(unittest.TestCase):
    def test_write_and_remove(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            target = env.paths.hook_file
            update.reconcile_hook(env.paths, True, True)
            text = target.read_text(encoding="utf-8")
            self.assertIn("omarchy plugin update luth-v.openusage-omarchy --yes",
                          text)
            self.assertTrue(target.stat().st_mode & 0o111)
            update.reconcile_hook(env.paths, False, True)
            self.assertFalse(target.exists())

    def test_non_git_install_never_hooks(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            update.reconcile_hook(env.paths, True, False)
            self.assertFalse(env.paths.hook_file.exists())

    def test_installable_probes_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(update.is_installable(root))
            (root / ".git").mkdir()
            self.assertTrue(update.is_installable(root))

    def test_install_runs_updater(self):
        with patch("openusage_omarchy.update.subprocess.Popen") as run:
            self.assertTrue(update.install())
            self.assertEqual(
                run.call_args[0][0],
                ["omarchy", "plugin", "update",
                 "luth-v.openusage-omarchy", "--yes"])
            options = run.call_args.kwargs
            self.assertTrue(options["start_new_session"])
            self.assertEqual(options["stdin"], update.subprocess.DEVNULL)
            self.assertEqual(options["stdout"], update.subprocess.DEVNULL)
            self.assertEqual(options["stderr"], update.subprocess.STDOUT)


if __name__ == "__main__":
    unittest.main()
