"""Every provider's synthetic mapper output passes the engine catalog gate."""

import json
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy import catalog, model
from openusage_omarchy.providers import (antigravity, claude, codex, copilot,
    cursor, devin, grok, ollama, opencode, openrouter, zai)
from openusage_omarchy.providers.antigravity import mapper as ag_mapper
from openusage_omarchy.providers.claude import auth as claude_auth, mapper as claude_mapper
from openusage_omarchy.providers.codex import mapper as codex_mapper
from openusage_omarchy.providers.copilot import mapper as copilot_mapper

import support

FIX = Path(__file__).parent / "fixtures"


def raw(name):
    return (FIX / name).read_bytes()


def obj(name):
    return json.loads(raw(name))


class CatalogEmissionTest(unittest.TestCase):
    def test_all_mapper_fixtures(self):
        table = catalog.cached()
        mapped = {}
        mapped["claude"] = claude_mapper.map_usage(
            raw("claude_usage.json"), claude_auth.OAuth(), support.NOW)[0]
        mapped["codex"] = codex_mapper.map_usage(
            raw("codex_usage.json"), None, None, None, support.NOW)[0]
        mapped["cursor"] = cursor.map_usage(obj("cursor_usage.json"), "pro")[0]
        mapped["antigravity"] = ag_mapper.parse_quota_summary(
            raw("antigravity_summary.json"))
        mapped["copilot"] = copilot_mapper.map_body(obj("copilot_usage.json"))[1]
        mapped["devin"] = devin.map_user_status(obj("devin_status.json")["userStatus"])[1]
        mapped["ollama"] = ollama.map_usage(
            raw("ollama_usage.json"), raw("ollama_account.json"))[1]
        mapped["opencode"] = opencode.parse_windows(obj("opencode_usage.json"))
        mapped["openrouter"] = {
            **openrouter.credits_lines(openrouter.data_object(raw("openrouter_credits.json"))),
            **openrouter.key_metrics(openrouter.data_object(raw("openrouter_key.json")))[1],
        }
        mapped["zai"] = zai.map_quota(raw("zai_quota.json"))
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            home = env.paths.home / ".grok"
            home.mkdir(parents=True)
            (home / "auth.json").write_bytes(raw("grok_auth.json"))
            env.http.add_json("GET", grok.BILLING_URL, obj("grok_billing.json"))
            env.http.add_json("GET", grok.SETTINGS_URL, obj("grok_settings.json"))
            mapped["grok"] = grok.fetch(grok.cards(env)[0], env).metrics
        self.assertEqual(set(mapped), set(table.families()))
        for family, metrics in mapped.items():
            self.assertTrue(metrics, family)
            snap = model.Snapshot(model.CardRef(family, family, family), None,
                                  support.NOW.isoformat(), metrics)
            checked = catalog.check_snapshot(snap, table)
            self.assertEqual(set(checked.metrics), set(metrics), family)

    def test_unknown_metric_is_dropped(self):
        snap = model.Snapshot(model.CardRef("codex", "codex", "Codex"), None,
                              support.NOW.isoformat(), {
                                  "session": model.Progress("session", 1, 100),
                                  "typo": model.Progress("typo", 1, 100),
                              })
        with self.assertLogs("openusage_omarchy.catalog", level="WARNING"):
            checked = catalog.check_snapshot(snap)
        self.assertEqual(set(checked.metrics), {"session"})


if __name__ == "__main__":
    unittest.main()
