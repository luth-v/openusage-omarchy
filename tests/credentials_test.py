"""CAS write-back stays private and never creates foreign lock files."""

import json
import stat
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy import credentials

import support


class CredentialCasTest(unittest.TestCase):
    def test_lock_is_private_and_original_mode_survives(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            foreign = Path(tmp) / "foreign"
            foreign.mkdir()
            target = foreign / "auth.json"
            target.write_text(json.dumps({"token": "test-only-old"}))
            target.chmod(0o600)
            self.assertTrue(credentials.cas_update_json(
                target, lambda data: {**data, "token": "test-only-new"}, "test"))
            self.assertEqual(json.loads(target.read_text())["token"], "test-only-new")
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)
            self.assertEqual(list(foreign.iterdir()), [target])
            locks = list((env.paths.runtime_dir / "locks").iterdir())
            self.assertEqual(len(locks), 1)
            self.assertEqual(stat.S_IMODE(locks[0].stat().st_mode), 0o600)

    def test_changed_generation_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp):
            target = Path(tmp) / "auth.json"
            target.write_text(json.dumps({"token": "test-only-old"}))
            def rotate(data):
                target.write_text(json.dumps({"token": "test-only-other"}))
                return {**data, "token": "test-only-new"}
            self.assertFalse(credentials.cas_update_json(target, rotate, "test"))
            self.assertEqual(json.loads(target.read_text())["token"], "test-only-other")


if __name__ == "__main__":
    unittest.main()
