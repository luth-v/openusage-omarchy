"""New-collector seams: emitted ids exist in the catalog, detect stays quiet."""

import tempfile
import unittest

from openusage_omarchy import catalog
from openusage_omarchy.engine import detect
from openusage_omarchy.providers import (
    antigravity, copilot, devin, ollama, openrouter, registry, zai,
)

import support

NEW = (antigravity, copilot, devin, ollama, openrouter, zai)


class CollectorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = catalog.cached()

    def test_registry_covers_all_eleven(self):
        self.assertEqual(
            [module.family for module in registry()],
            ["claude", "codex", "cursor", "antigravity", "copilot", "devin",
             "grok", "ollama", "opencode", "openrouter", "zai"],
        )

    def test_empty_machine_detects_nothing(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            found = detect.detect_all(registry(), env)
            self.assertEqual(len(found), 11)
            self.assertFalse(any(found.values()))

    def test_detection_survives_broken_collectors(self):
        class _Broken:
            family = "broken"

            def has_credentials(self, env):
                raise RuntimeError("boom")

        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            self.assertEqual(
                detect.detect_all([_Broken()], env), {"broken": False})


if __name__ == "__main__":
    unittest.main()
