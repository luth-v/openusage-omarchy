"""Python enablement follows the same fixtures as Layout.js."""

import json
import unittest
from pathlib import Path

from openusage_omarchy import catalog, layout, model
from openusage_omarchy.engine import detect

import tempfile
from types import SimpleNamespace

import support


class EnablementTest(unittest.TestCase):
    def test_shared_defaults_and_first_run(self):
        table = catalog.cached()
        fixture = Path(__file__).parent / "fixtures" / "enablement.json"
        for case in json.loads(fixture.read_text()):
            cards = [model.CardRef(p.provider_id, p.provider_id, p.display_name)
                     for p in table.providers]
            got = layout.enabled_card_ids(case["layout"], case["detected"],
                                          table, cards)
            self.assertEqual(got, set(case["enabled"]))

    def test_account_card_inherits_family_until_overridden(self):
        table = catalog.cached()
        cards = [model.CardRef("codex:a", "codex", "A")]
        saved = {"schema": "openusage-omarchy.layout.v1",
                 "firstRunCompleted": True,
                 "cards": {"codex": {"enabled": False}}}
        self.assertEqual(layout.enabled_card_ids(saved, {"codex": True},
                                                 table, cards), set())
        saved["cards"]["codex:a"] = {"enabled": True}
        self.assertEqual(layout.enabled_card_ids(saved, {"codex": True},
                                                 table, cards), {"codex:a"})

    def test_disabled_provider_credentials_are_not_probed(self):
        table = catalog.cached()
        saved = {"schema": "openusage-omarchy.layout.v1",
                 "firstRunCompleted": True,
                 "cards": {"codex": {"enabled": False},
                           "ollama": {"enabled": False}}}
        allowed = layout.detection_families(saved, table)
        self.assertNotIn("codex", allowed)
        self.assertNotIn("ollama", allowed)
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            calls = []
            collectors = [SimpleNamespace(
                family="codex",
                has_credentials=lambda unused: calls.append("codex") or True)]
            self.assertEqual(detect.detect_all(collectors, env, allowed),
                             {"codex": False})
            self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
