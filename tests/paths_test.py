"""XDG paths and the forbidden-path guard."""

import unittest
import tempfile
import os
from pathlib import Path

from openusage_omarchy import paths


class PathsTest(unittest.TestCase):
    def test_xdg_resolution(self):
        env = {
            "HOME": "/tmp/ou-home",
            "XDG_STATE_HOME": "/tmp/ou-state",
            "XDG_CACHE_HOME": "/tmp/ou-cache",
            "XDG_CONFIG_HOME": "/tmp/ou-config",
            "XDG_DATA_HOME": "/tmp/ou-data",
            "XDG_RUNTIME_DIR": "/tmp/ou-run",
        }
        dirs = paths.Paths.from_env(env)
        self.assertEqual(dirs.state_dir, Path("/tmp/ou-state/openusage-omarchy"))
        self.assertEqual(dirs.cache_dir, Path("/tmp/ou-cache/openusage-omarchy"))
        self.assertEqual(dirs.config_dir, Path("/tmp/ou-config/openusage-omarchy"))
        self.assertEqual(dirs.data_dir, Path("/tmp/ou-data/openusage-omarchy"))
        self.assertEqual(dirs.runtime_dir, Path("/tmp/ou-run/openusage-omarchy"))
        self.assertEqual(dirs.snapshots_dir, dirs.cache_dir / "snapshots")
        self.assertEqual(dirs.shell_json, Path("/tmp/ou-config/omarchy/shell.json"))

    def test_defaults(self):
        dirs = paths.Paths.from_env({"HOME": "/tmp/ou-home"})
        self.assertEqual(dirs.state_dir, Path("/tmp/ou-home/.local/state/openusage-omarchy"))
        self.assertEqual(dirs.config_dir, Path("/tmp/ou-home/.config/openusage-omarchy"))

    def test_forbidden_writes_refused(self):
        home = Path("/tmp/ou-home")
        for raw in (
            ".local/state/openusage/x.json",
            ".config/openusage/x.json",
            ".local/bin/openusage",
            ".config/hypr/x.conf",
        ):
            with self.assertRaises(ValueError, msg=raw):
                paths.assert_writable(home / raw, home)
        with self.assertRaises(ValueError):
            paths.assert_writable(Path("/usr/share/omarchy/x"), home)

    def test_allowed_writes(self):
        home = Path("/tmp/ou-home")
        for raw in (
            ".local/state/openusage-omarchy/state.json",
            ".cache/openusage-omarchy/snapshots/cursor.json",
            ".config/openusage-omarchy/config.json",
        ):
            self.assertEqual(paths.assert_writable(home / raw, home), home / raw)

    def test_runtime_root_rejects_public_or_symlinked_parent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime = root / "run" / "openusage-omarchy"
            paths.ensure_runtime_dir(runtime)
            self.assertEqual(runtime.stat().st_mode & 0o777, 0o700)
            os.chmod(runtime.parent, 0o755)
            with self.assertRaises(OSError):
                paths.ensure_runtime_dir(runtime)
            runtime.parent.chmod(0o700)
            link = root / "linked"
            link.symlink_to(runtime.parent, target_is_directory=True)
            with self.assertRaises(OSError):
                paths.ensure_runtime_dir(link / "openusage-omarchy")


if __name__ == "__main__":
    unittest.main()
