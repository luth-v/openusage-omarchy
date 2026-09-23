"""CLI exit codes and the daemon serve loop over a throwaway env."""

import io
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import cli
from openusage_omarchy import atomic

import support

ROOT = Path(__file__).resolve().parent.parent


class CliTest(unittest.TestCase):
    def run_cli(self, argv, env):
        out = io.StringIO()
        with redirect_stdout(out):
            code = cli.run(argv, env)
        return code, out.getvalue()

    def test_bad_args_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with patch.object(sys, "stderr", io.StringIO()):
                code, _ = self.run_cli(["a", "b", "c"], env)
                self.assertEqual(code, 2)
                code, _ = self.run_cli(["--nope"], env)
                self.assertEqual(code, 2)

    def test_unknown_provider_exit_2(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with patch.object(sys, "stderr", io.StringIO()):
                code, _ = self.run_cli(["nope"], env)
            self.assertEqual(code, 2)

    def test_default_enabled_cards_without_login_exit_4(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            code, text = self.run_cli([], env)
            self.assertEqual(code, 4)
            envelope = json.loads(text)
            self.assertEqual(envelope["schema"], "openusage.limits.v1")
            self.assertEqual(envelope["providers"], {})
            self.assertEqual({item["providerId"] for item in envelope["errors"]},
                             {"claude", "codex", "cursor"})

    def test_no_id_follows_saved_enablement(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            atomic.write_json_atomic(env.paths.layout_file, {
                "schema": "openusage-omarchy.layout.v1",
                "firstRunCompleted": True,
                "cards": {"claude": {"enabled": False},
                          "codex": {"enabled": False},
                          "cursor": {"enabled": False}}})
            with patch("openusage_omarchy.cli._refresh.refresh") as refresh:
                from openusage_omarchy.engine.refresh import Batch
                refresh.return_value = Batch(generation=1)
                code, _ = self.run_cli([], env)
            self.assertEqual(code, 0)
            self.assertEqual(refresh.call_args.kwargs["enabled_ids"], set())

    def test_explicit_id_without_login_exit_4(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            code, text = self.run_cli(["cursor"], env)
            self.assertEqual(code, 4)
            envelope = json.loads(text)
            self.assertEqual(envelope["providers"], {})
            self.assertEqual(envelope["errors"][0]["providerId"], "cursor")

    def test_force_flag_accepted(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            code, _ = self.run_cli(["--force"], env)
            self.assertEqual(code, 4)

    def test_help(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cli.main(["--help"]), 0)
            with patch.object(sys, "stderr", io.StringIO()):
                self.assertEqual(cli.main(["--bogus"]), 2)

    def test_launcher_works_through_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = Path(tmp) / "openusage-omarchy"
            link.symlink_to(ROOT / "bin" / "openusage-omarchy")
            child_env = {
                "PATH": os.defpath,
                "HOME": str(Path(tmp) / "home"),
                "XDG_STATE_HOME": str(Path(tmp) / "state"),
                "XDG_CACHE_HOME": str(Path(tmp) / "cache"),
                "XDG_CONFIG_HOME": str(Path(tmp) / "config"),
                "XDG_RUNTIME_DIR": str(Path(tmp) / "run"),
            }
            child = subprocess.run([str(link), "--help"], capture_output=True,
                                   timeout=10, env=child_env)
            self.assertEqual(child.returncode, 0, child.stderr.decode())
            self.assertIn(b"openusage-omarchy", child.stdout)

    def test_serve_writes_state_then_exits_on_eof(self):
        import socket

        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            child_env = {
                "PATH": os.defpath,
                "HOME": str(home),
                "XDG_STATE_HOME": str(Path(tmp) / "state"),
                "XDG_CACHE_HOME": str(Path(tmp) / "cache"),
                "XDG_CONFIG_HOME": str(Path(tmp) / "config"),
                "XDG_DATA_HOME": str(Path(tmp) / "data"),
                "XDG_RUNTIME_DIR": str(Path(tmp) / "run"),
                "GROK_HOME": str(home / ".grok"),
            }
            # Hold the API port so the child takes the feature-off path
            # deterministically (a live daemon would force the same path).
            hold = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                hold.bind(("127.0.0.1", 6736))
            except OSError:
                pass  # already taken: the child still reports off
            try:
                proc = subprocess.run(
                    [str(ROOT / "bin" / "openusage-omarchy"), "serve"],
                    stdin=subprocess.DEVNULL,
                    capture_output=True,
                    timeout=60,
                    env=child_env,
                )
            finally:
                hold.close()
            self.assertEqual(proc.returncode, 0, proc.stderr.decode()[-2000:])
            state_path = Path(tmp) / "state" / "openusage-omarchy" / "state.json"
            state = json.loads(state_path.read_text())
            self.assertEqual(state["schema"], "openusage-omarchy.state.v1")
            self.assertEqual(len(state["cards"]), 11)
            self.assertEqual(state["daemon"]["apiListening"], False)
            mode = stat.S_IMODE(state_path.stat().st_mode)
            self.assertEqual(mode, 0o600)


if __name__ == "__main__":
    unittest.main()
