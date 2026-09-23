"""Key store: keyring first, 0600 file next, env last. Never argv or logs."""

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from openusage_omarchy import secrets

import support


def shim_env(tmp: str, **extra: str) -> dict[str, str]:
    base = Path(tmp)
    shim_dir = support.install_shim(base)
    env = {
        "PATH": str(shim_dir),
        "SHIM_LOG": str(base / "shim.log"),
    }
    env.update(extra)
    return env


class SecretsTest(unittest.TestCase):
    def test_keyring_wins(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, SHIM_HIT_OPENROUTER="1")):
                self.assertEqual(
                    secrets.get_key("openrouter", env.paths),
                    "test-only-shim-openrouter")
                self.assertEqual(
                    secrets.key_source("openrouter", env.paths), "keyring")

    def test_file_beats_env(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, {**shim_env(tmp, SHIM_STORE_EXIT="1"),
                                              "OPENROUTER_API_KEY": "test-only-env"}):
                secrets.set_key("openrouter", "test-only-file", env.paths)
                self.assertEqual(
                    secrets.get_key("openrouter", env.paths), "test-only-file")
                self.assertEqual(
                    secrets.key_source("openrouter", env.paths), "file")

    def test_env_last_resort(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, {**shim_env(tmp),
                                              "ZAI_API_KEY": "test-only-env"}):
                self.assertEqual(
                    secrets.get_key("zai", env.paths), "test-only-env")
                self.assertEqual(secrets.key_source("zai", env.paths), "env")

    def test_legacy_glm_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, {**shim_env(tmp),
                                              "GLM_API_KEY": "test-only-legacy"}):
                self.assertEqual(
                    secrets.get_key("zai", env.paths), "test-only-legacy")

    def test_none_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp)):
                self.assertIsNone(secrets.get_key("zai", env.paths))
                self.assertEqual(secrets.key_source("zai", env.paths), "none")

    def test_store_uses_stdin_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp)):
                secrets.set_key("openrouter", "test-only-typed-key", env.paths)
                log = (Path(tmp) / "shim.log").read_text()
                self.assertNotIn("test-only-typed-key", log)
                self.assertIn(
                    f"store_stdin_len={len('test-only-typed-key')}", log)
                self.assertIn("'store'", log)

    def test_store_falls_back_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, SHIM_STORE_EXIT="1")):
                secrets.set_key("zai", "test-only-file-key", env.paths)
                path = secrets.keys_path(env.paths)
                self.assertEqual(
                    json.loads(path.read_text())["zai"], "test-only-file-key")
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
                self.assertEqual(
                    stat.S_IMODE(path.parent.stat().st_mode), 0o700)

    def test_no_tool_uses_file(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            secrets.set_key("openrouter", "test-only-k", env.paths)
            self.assertEqual(
                secrets.get_key("openrouter", env.paths), "test-only-k")

    def test_delete_clears_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            with support.test_env(tmp) as env, \
                    patch.dict(os.environ, shim_env(tmp, SHIM_STORE_EXIT="1")):
                secrets.set_key("zai", "test-only-k", env.paths)
                secrets.delete_key("zai", env.paths)
                self.assertIsNone(secrets.get_key("zai", env.paths))
                log = (Path(tmp) / "shim.log").read_text()
                self.assertIn("'clear'", log)

    def test_empty_key_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with self.assertRaises(secrets.SecretsError):
                secrets.set_key("zai", "   ", env.paths)

    def test_unknown_provider_rejected(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            for call in (
                lambda: secrets.get_key("cursor", env.paths),
                lambda: secrets.key_source("cursor", env.paths),
                lambda: secrets.set_key("cursor", "x", env.paths),
                lambda: secrets.delete_key("cursor", env.paths),
            ):
                with self.assertRaises(ValueError):
                    call()


if __name__ == "__main__":
    unittest.main()
