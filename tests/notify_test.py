"""Notification milestone logic. Ports the upstream PaceNotification rules."""

import datetime as dt
import tempfile
import unittest
import subprocess
import sys
from unittest.mock import patch

from openusage_omarchy import model, notify

import support

NOW = support.NOW
RESET = "2026-09-23T14:00:00+00:00"
ON = {"underTenPercent": True, "healthyToClose": True,
      "closeToRunningOut": True}
OFF = {"underTenPercent": False, "healthyToClose": False,
       "closeToRunningOut": False}


def primed(**kwargs):
    args = {"primed": True, "previous_bucket": "healthy",
            "was_under_ten": False, "resets_at": RESET, "fired": set()}
    args.update(kwargs)
    return notify.NotificationState(**args)


class TransitionsTest(unittest.TestCase):
    def test_launch_baseline_never_fires(self):
        fire, nxt = notify.transitions("runningOut", 0.01, RESET,
                                       notify.NotificationState(), ON)
        self.assertEqual(fire, [])
        self.assertTrue(nxt.primed)
        self.assertEqual(nxt.previous_bucket, "runningOut")
        self.assertTrue(nxt.was_under_ten)

    def test_under_ten_edge_fires_once(self):
        fire, nxt = notify.transitions("level", 0.05, RESET, primed(), ON)
        self.assertEqual(fire, ["underTenPercent"])
        nxt.fired.add("underTenPercent")
        fire, nxt = notify.transitions("level", 0.04, RESET, nxt, ON)
        self.assertEqual(fire, [])

    def test_recovery_rearms_under_ten(self):
        first = primed(was_under_ten=True,
                       fired={"underTenPercent"})
        fire, nxt = notify.transitions("level", 0.5, RESET, first, ON)
        self.assertEqual(fire, [])
        self.assertNotIn("underTenPercent", nxt.fired)
        fire, _ = notify.transitions("level", 0.05, RESET, nxt, ON)
        self.assertEqual(fire, ["underTenPercent"])

    def test_healthy_to_close_edge(self):
        fire, nxt = notify.transitions("closeToLimit", 0.5, RESET, primed(), ON)
        self.assertEqual(fire, ["healthyToClose"])
        self.assertEqual(nxt.previous_bucket, "close")

    def test_blue_to_red_fires_run_out_only(self):
        fire, _ = notify.transitions("runningOut", 0.5, RESET, primed(), ON)
        self.assertEqual(fire, ["closeToRunningOut"])

    def test_close_to_running_out_edge(self):
        prev = primed(previous_bucket="close")
        fire, _ = notify.transitions("runningOut", 0.5, RESET, prev, ON)
        self.assertEqual(fire, ["closeToRunningOut"])

    def test_step_down_fires_both_stages_across_passes(self):
        fire, nxt = notify.transitions("closeToLimit", 0.5, RESET, primed(), ON)
        self.assertEqual(fire, ["healthyToClose"])
        nxt.fired.add("healthyToClose")
        fire, _ = notify.transitions("runningOut", 0.5, RESET, nxt, ON)
        self.assertEqual(fire, ["closeToRunningOut"])

    def test_improvement_clears_fired_flags(self):
        prev = primed(previous_bucket="runningOut",
                      fired={"closeToRunningOut"})
        fire, nxt = notify.transitions("healthy", 0.5, RESET, prev, ON)
        self.assertEqual(fire, [])
        self.assertNotIn("closeToRunningOut", nxt.fired)

    def test_no_data_suppresses_everything(self):
        prev = primed()
        fire, nxt = notify.transitions("noData", 0.0, RESET, prev, ON)
        self.assertEqual(fire, [])
        self.assertEqual(nxt.previous_bucket, "healthy")

    def test_level_suppresses_pace_but_not_almost_out(self):
        fire, _ = notify.transitions("level", 0.05, RESET, primed(), ON)
        self.assertEqual(fire, ["underTenPercent"])

    def test_toggle_off_leaves_edge_unconsumed(self):
        fire, nxt = notify.transitions("runningOut", 0.5, RESET, primed(), OFF)
        self.assertEqual(fire, [])
        self.assertEqual(nxt.previous_bucket, "healthy")
        fire, _ = notify.transitions("runningOut", 0.5, RESET, nxt, ON)
        self.assertEqual(fire, ["closeToRunningOut"])

    def test_new_window_clears_dedup(self):
        prev = primed(fired={"underTenPercent", "closeToRunningOut"},
                      previous_bucket="runningOut", was_under_ten=True)
        later = "2026-09-24T14:00:00+00:00"
        fire, nxt = notify.transitions("runningOut", 0.01, later, prev, ON)
        self.assertEqual(nxt.fired, set())
        self.assertEqual(nxt.previous_bucket, "runningOut")
        self.assertTrue(nxt.was_under_ten)
        self.assertIn("underTenPercent", fire)
        self.assertIn("closeToRunningOut", fire)

    def test_jitter_does_not_advance_window(self):
        prev = primed(fired={"healthyToClose"})
        same = "2026-09-23T14:00:00+00:00"
        self.assertFalse(notify.reset_window_advanced(same, RESET))
        fire, nxt = notify.transitions("closeToLimit", 0.5, same, prev, ON)
        self.assertEqual(fire, [])


class MeterStateTest(unittest.TestCase):
    def test_spent(self):
        metric = model.Progress(metric_id="session", used=100, limit=100)
        self.assertEqual(notify.meter_state(metric, "codex", NOW), "spent")

    def test_pace_verdicts(self):
        reset = (NOW + dt.timedelta(hours=3)).isoformat()
        period = 5 * 3600 * 1000
        calm = model.Progress(metric_id="session", used=10, limit=100,
                              resets_at=reset, period_ms=period)
        self.assertEqual(notify.meter_state(calm, "codex", NOW), "healthy")
        hot = model.Progress(metric_id="session", used=60, limit=100,
                             resets_at=reset, period_ms=period)
        self.assertEqual(notify.meter_state(hot, "codex", NOW), "runningOut")

    def test_no_window_is_level(self):
        metric = model.Progress(metric_id="x", used=95, limit=100)
        self.assertEqual(notify.meter_state(metric, "codex", NOW), "level")

    def test_fresh_claude_session_is_level(self):
        metric = model.Progress(metric_id="session", used=0, limit=100)
        self.assertEqual(notify.meter_state(metric, "claude", NOW), "level")


class EvaluateTest(unittest.TestCase):
    def test_shutdown_terminates_live_waiter(self):
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                                 stdin=subprocess.DEVNULL,
                                 stdout=subprocess.DEVNULL,
                                 stderr=subprocess.DEVNULL)
        try:
            notify.startup()
            with notify._waiters_lock:
                notify._waiters.add(child)
            notify.shutdown()
            self.assertIsNotNone(child.poll())
        finally:
            if child.poll() is None:
                child.kill()
                child.wait()
            notify.startup()

    def metric(self, key="codex:session", state="runningOut", fraction=0.4):
        return notify.MetricInput(key=key, provider="codex", title="Session",
                                  state=state, fraction=fraction,
                                  resets_at=RESET)

    def test_prunes_absent_metrics(self):
        stored = {"gone:x": notify.NotificationState(primed=True)}
        _, keep = notify.evaluate([self.metric()], ON, stored)
        self.assertNotIn("gone:x", keep)
        self.assertIn("codex:session", keep)

    def test_commit_marks_only_on_delivery(self):
        prev = {"codex:session": primed()}
        _, keep = notify.evaluate([self.metric()], ON, prev)
        fired = [(self.metric(), "closeToRunningOut")]
        notify.commit(fired, keep, prev, False)
        self.assertNotIn("closeToRunningOut", keep["codex:session"].fired)
        self.assertEqual(keep["codex:session"].previous_bucket, "healthy")
        notify.commit(fired, keep, prev, True)
        self.assertIn("closeToRunningOut", keep["codex:session"].fired)

    def test_state_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            stored = {"codex:session": primed(fired={"healthyToClose"})}
            notify.save_state(env.paths, stored)
            back = notify.load_state(env.paths)
            self.assertEqual(back["codex:session"].fired, {"healthyToClose"})
            self.assertTrue(back["codex:session"].primed)

    def test_post_groups_into_one_call(self):
        alerts = [(self.metric(), "underTenPercent"),
                  (self.metric(), "closeToRunningOut")]
        with patch("openusage_omarchy.notify.shutil.which", return_value="/x"):
            with patch("openusage_omarchy.notify.subprocess.Popen") as popen:
                proc = popen.return_value
                proc.communicate.return_value = ("", "")
                proc.returncode = 0
                self.assertTrue(notify.post(alerts, lambda pid: "Codex"))
                self.assertEqual(popen.call_count, 1)
                args = popen.call_args[0][0]
                self.assertIn("--action=default=Open", args)
                self.assertIn("--wait", args)
                body = args[-1]
                self.assertIn("Almost Out", body)
                self.assertIn("Will Run Out", body)

    def test_post_without_notify_send_skips(self):
        with patch("openusage_omarchy.notify.shutil.which", return_value=None):
            with patch("openusage_omarchy.notify.subprocess.Popen") as popen:
                self.assertFalse(notify.post([(self.metric(), "underTenPercent")],
                                             lambda pid: "Codex"))
                popen.assert_not_called()

    def test_post_quick_action_opens_dashboard(self):
        with patch("openusage_omarchy.notify.shutil.which", return_value="/x"):
            with patch("openusage_omarchy.notify.subprocess.Popen") as popen:
                proc = popen.return_value
                proc.communicate.return_value = ("default\n", "")
                proc.returncode = 0
                with patch("openusage_omarchy.notify._open_dashboard",
                           return_value=True) as opener:
                    self.assertTrue(notify.post(
                        [(self.metric(), "underTenPercent")],
                        lambda pid: "Codex"))
                    opener.assert_called_once_with()

    def test_post_quick_failure_returns_false(self):
        with patch("openusage_omarchy.notify.shutil.which", return_value="/x"):
            with patch("openusage_omarchy.notify.subprocess.Popen") as popen:
                proc = popen.return_value
                proc.communicate.return_value = ("", "no server")
                proc.returncode = 1
                self.assertFalse(notify.post(
                    [(self.metric(), "underTenPercent")], lambda pid: "Codex"))

    def test_post_slow_close_spawns_bounded_worker(self):
        import subprocess as _sp
        with patch("openusage_omarchy.notify.shutil.which", return_value="/x"):
            with patch("openusage_omarchy.notify.subprocess.Popen") as popen:
                proc = popen.return_value
                proc.communicate.side_effect = _sp.TimeoutExpired("notify", 0.5)
                with patch("openusage_omarchy.notify.threading.Thread") as thread:
                    self.assertTrue(notify.post(
                        [(self.metric(), "underTenPercent")],
                        lambda pid: "Codex"))
                    thread.assert_called_once()
                    _, kwargs = thread.call_args
                    self.assertTrue(kwargs.get("daemon"))
                    thread.return_value.start.assert_called_once_with()

    def test_wait_and_open_runs_ipc_on_tap(self):
        with patch("openusage_omarchy.notify._open_dashboard",
                   return_value=True) as opener:
            proc = unittest.mock.MagicMock()
            proc.communicate.return_value = ("default\n", "")
            proc.returncode = 0
            self.assertTrue(notify._wait_and_open(proc))
            opener.assert_called_once_with()

    def test_wait_and_open_ignores_dismiss(self):
        with patch("openusage_omarchy.notify._open_dashboard") as opener:
            proc = unittest.mock.MagicMock()
            proc.communicate.return_value = ("", "")
            proc.returncode = 0
            self.assertTrue(notify._wait_and_open(proc))
            opener.assert_not_called()

    def test_build_args_carries_action_and_wait(self):
        args = notify._build_args("hi")
        self.assertIn("--action=default=Open", args)
        self.assertIn("--wait", args)
        self.assertEqual(args[0], "notify-send")

    def test_open_dashboard_missing_shell_is_false(self):
        with patch("openusage_omarchy.notify.shutil.which", return_value=None):
            self.assertFalse(notify._open_dashboard())


if __name__ == "__main__":
    unittest.main()
