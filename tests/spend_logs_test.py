"""Spend from agent logs: Claude, Codex, Grok, Cursor CSV."""

import json
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy.providers.claude import logs as _claude_logs
from openusage_omarchy.providers.codex import logs as _codex_logs
from openusage_omarchy.providers.cursor import usage_csv as _csv
from openusage_omarchy.spend import pricing as _pricing
from openusage_omarchy.spend import grok_scan as _grok
from openusage_omarchy.spend import price_catalog as _cat
from openusage_omarchy.spend import supplement as _supp
from openusage_omarchy.spend.rates import ModelRates

import support

NOW = support.NOW


def _dump(obj):
    return json.dumps(obj, separators=(",", ":"))


def _price(model_id="test-only-model", *, input_per_m=1.0, output_per_m=2.0):
    cat = _cat.PricingCatalog(entries={
        model_id: ModelRates(input_per_m=input_per_m, output_per_m=output_per_m,
                             cache_write_per_m=1.0, cache_read_per_m=0.1)})
    return _pricing.ModelPricing(_supp.Supplement(), cat, _cat.PricingCatalog())


class ClaudeLogsTest(unittest.TestCase):
    def test_parse_and_dedup(self):
        lines = [
            _dump({
                "message": {"id": "test-only-msg", "model": "test-only-model",
                            "usage": {"input_tokens": 10, "output_tokens": 5}},
                "timestamp": "2026-09-23T01:00:00Z",
                "requestId": "test-only-req", "version": "1.0.0"}).encode(),
            _dump({
                "message": {"id": "test-only-msg", "model": "test-only-model",
                            "usage": {"input_tokens": 3, "output_tokens": 1}},
                "timestamp": "2026-09-23T02:00:00Z",
                "requestId": "test-only-req", "version": "1.0.0"}).encode(),
        ]
        entries = _claude_logs.parse_records(lines)
        self.assertEqual(len(entries), 2)
        deduped = _claude_logs.dedup(entries)
        self.assertEqual(len(deduped), 1)
        self.assertEqual(deduped[0]["input"], 10)

    def test_aggregate_carried_vs_estimated(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            base = env.paths.home / ".claude" / "projects" / "test-only-p"
            base.mkdir(parents=True)
            carried = {"message": {"id": "test-only-a", "model": "test-only-model",
                                   "usage": {"input_tokens": 10, "output_tokens": 5,
                                             "cache_creation_input_tokens": 2,
                                             "cache_read_input_tokens": 1}},
                       "timestamp": "2026-09-23T01:00:00Z",
                       "requestId": "test-only-a",
                       "costUSD": 0.25, "version": "1.0.0"}
            estimated = {"message": {"id": "test-only-b", "model": "test-only-model",
                                     "usage": {"input_tokens": 100, "output_tokens": 50}},
                         "timestamp": "2026-09-23T02:00:00Z",
                         "requestId": "test-only-b", "version": "1.0.0"}
            outdated = dict(estimated)
            outdated["message"] = dict(estimated["message"])
            outdated["message"]["id"] = "test-only-c"
            outdated["requestId"] = "test-only-c"
            outdated["version"] = "test-only-old"
            (base / "a.jsonl").write_text("\n".join(
                _dump(item) for item in (carried, estimated, outdated)) + "\n")
            scan = _claude_logs.scan(env.paths.home, env.paths.scan_dir, 0, _price())
            assert scan is not None
            today = next(entry for entry in scan.series.daily if entry.date == "2026-09-23")
            # 0.25 carried + (100/1M*1 + 50/1M*2)=0.0002; outdated dropped.
            self.assertAlmostEqual(today.cost_usd, 0.2502, places=4)

    def test_unknown_model_tracked(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            base = env.paths.home / ".claude" / "projects" / "test-only-p"
            base.mkdir(parents=True)
            (base / "a.jsonl").write_text(_dump({
                "message": {"id": "test-only-a", "model": "test-only-unknown",
                            "usage": {"input_tokens": 10, "output_tokens": 5}},
                "timestamp": "2026-09-23T01:00:00Z",
                "requestId": "test-only-a", "version": "1.0.0"}) + "\n")
            scan = _claude_logs.scan(env.paths.home, env.paths.scan_dir, 0, _price())
            assert scan is not None
            self.assertIn("test-only-unknown", scan.unknown_by_day["2026-09-23"])


class CodexLogsTest(unittest.TestCase):
    def _write(self, path, events):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(_dump(item) for item in events) + "\n")

    def _token_event(self, inp, cached, output, model="test-only-model"):
        return {"timestamp": "2026-09-23T01:00:00Z", "type": "event_msg",
                "payload": {"type": "token_count",
                            "info": {"total_token_usage": {
                                "input_tokens": inp, "cached_input_tokens": cached,
                                "output_tokens": output},
                                "model": model}}}

    def test_deltas_and_duplicate_totals(self):
        events = _claude_logs.parse_records([])  # touch import, no-op
        _ = events
        records = [
            _dump({"type": "turn_context",
                        "payload": {"model": "test-only-model"}}).encode(),
            _dump(self._token_event(10, 2, 5)).encode(),
            # Same totals repeat: skipped.
            _dump(self._token_event(10, 2, 5)).encode(),
        ]
        parsed = _codex_logs.parse_records(records)
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]["input"], 10)
        scan = _codex_logs.aggregate(parsed, 0, _price())
        today = next(entry for entry in scan.series.daily if entry.date == "2026-09-23")
        self.assertEqual(today.total_tokens, 15)

    def test_scan_reads_session_files(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            path = env.paths.home / ".codex" / "sessions" / "a.jsonl"
            self._write(path, [
                {"type": "turn_context", "payload": {"model": "test-only-model"}},
                self._token_event(100, 0, 0),
            ])
            scan = _codex_logs.scan(env.paths.home, env.paths.scan_dir, 0, _price())
            assert scan is not None
            today = next(entry for entry in scan.series.daily if entry.date == "2026-09-23")
            self.assertEqual(today.total_tokens, 100)

    def test_auto_fallback_names(self):
        self.assertEqual(_codex_logs.auto_fallback("2026-09-23T00:00:00Z"),
                         "gpt-5.6-luna")
        self.assertEqual(_codex_logs.auto_fallback("not-a-date"), "gpt-5")


class GrokScanTest(unittest.TestCase):
    def _record(self, event_id, model="test-only-model", ticks=2500000000):
        ms = int(NOW.timestamp() * 1000)
        return _dump({
            "update": {"sessionUpdate": "turn_completed",
                       "usage": {"modelUsage": {model: {
                           "inputTokens": 10, "cachedReadTokens": 2,
                           "cacheCreationTokens": 1, "outputTokens": 5,
                           "costUsdTicks": ticks}}}},
            "_meta": {"agentTimestampMs": ms, "eventId": event_id}}).encode()

    def test_dedup_and_unknown(self):
        records = [self._record("test-only-r"), self._record("test-only-r"),
                   self._record("test-only-x", model="test-only-missing", ticks=-1)]
        entries = _grok.parse_records(records)
        self.assertEqual(len(entries), 3)
        deduped = _grok.dedup(entries)
        self.assertEqual(len(deduped), 2)
        scan = _grok.aggregate(deduped, 0, _price())
        today = next(entry for entry in scan.series.daily if entry.date == "2026-09-23")
        # Carried 0.25 for known; estimated for missing (10+5 tokens).
        self.assertGreater(today.total_tokens, 0)
        self.assertIn("test-only-missing", scan.unknown_by_day["2026-09-23"])


class CursorCsvTest(unittest.TestCase):
    CSV = ("Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),"
           "Cache Read,Output Tokens\n"
           "2026-09-23T01:00:00Z,test-only-model,0,100,0,50\n"
           "2026-09-23T02:00:00Z,test-only-model,0,100,0,50\n"
           "bad-row\n")

    def test_parse_rejects_malformed(self):
        rows, rejected = _csv.parse_csv(self.CSV, _price())
        self.assertEqual(len(rows), 2)
        self.assertEqual(rejected, 1)

    def test_missing_columns_raises(self):
        with self.assertRaises(_csv.CsvError):
            _csv.parse_csv("Date,Model\n2026-09-23,m\n", _price())

    def test_aggregation_groups_fast_family(self):
        pricing = _price("gpt-5.2")
        # Cover fast variant via supplement multiplier.
        pricing.supplement.fast_multipliers["gpt-5.2"] = 2.0
        text = ("Date,Model,Input (w/ Cache Write),Input (w/o Cache Write),"
                "Cache Read,Output Tokens\n"
                "2026-09-23T01:00:00Z,gpt-5.2,0,100,0,50\n"
                "2026-09-23T02:00:00Z,gpt-5.2-fast,0,100,0,50\n")
        rows, _ = _csv.parse_csv(text, pricing)
        self.assertEqual(len(rows), 2)
        scan = _csv.to_scan_with_pricing(rows, pricing)
        entry = scan.model_usage.daily[0].models[0]
        self.assertEqual(entry.model, "gpt-5.2")
        self.assertEqual(entry.total_tokens, 300)


if __name__ == "__main__":
    unittest.main()
