"""Spend: Pi, OpenCode, Codex pricing, Antigravity, publish."""

import datetime as dt
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy import catalog as _catalog
from openusage_omarchy import model
from openusage_omarchy.daemon import publish as _publish
from openusage_omarchy.engine.refresh import Batch, CardResult
from openusage_omarchy.spend import (
    antigravity_proto as _proto,
    antigravity_scan as _anti,
    codex_pricing as _codex_price,
    opencode_codex as _oc_codex,
    opencode_scan as _oc,
    pi as _pi,
    price_catalog as _cat,
    pricing as _pricing,
    supplement as _supp,
)
from openusage_omarchy.spend.aggregate import Accumulator
from openusage_omarchy.spend.rates import ModelRates, TokenBreakdown

import support

NOW = support.NOW


def _dump(obj):
    return json.dumps(obj, separators=(",", ":"))


def _price(entries=None):
    cat = _cat.PricingCatalog(entries=entries or {
        "test-only-model": ModelRates(input_per_m=1.0, output_per_m=2.0,
                                      cache_write_per_m=1.0, cache_read_per_m=0.1)})
    return _pricing.ModelPricing(_supp.Supplement(), cat, _cat.PricingCatalog())


class PiTest(unittest.TestCase):
    def _record(self, provider, ident="test-only-1", carried=0.25):
        return _dump({
            "type": "message", "timestamp": "2026-09-23T01:00:00Z", "id": ident,
            "message": {"role": "assistant", "provider": provider,
                        "model": "test-only-model",
                        "usage": {"input": 10, "cacheWrite": 4, "cacheWrite1h": 1,
                                  "cacheRead": 2, "output": 5, "totalTokens": 22,
                                  "cost": {"total": carried}}}}).encode()

    def test_provider_mapping_and_dedup(self):
        entries = _pi.parse_records([self._record("openai-codex"),
                                     self._record("openai-codex"),
                                     self._record("unknown-provider")])
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["card"], "codex")
        deduped = _pi.dedup(entries)
        self.assertEqual(len(deduped), 1)
        scan = _pi.aggregate(deduped, "codex", 0, _price())
        today = next(item for item in scan.series.daily if item.date == "2026-09-23")
        self.assertAlmostEqual(today.cost_usd, 0.25)

    def test_card_filter(self):
        entries = _pi.parse_records([self._record("anthropic")])
        self.assertEqual(entries[0]["card"], "claude")
        scan = _pi.aggregate(entries, "codex", 0, _price())
        self.assertEqual(scan.series.daily, ())

    def test_cached_write_split(self):
        entries = _pi.parse_records([self._record("anthropic")])
        self.assertEqual(entries[0]["cache5m"], 3)
        self.assertEqual(entries[0]["cache1h"], 1)


class CodexPricingTest(unittest.TestCase):
    def test_dated_base(self):
        self.assertEqual(_codex_price.dated_base("gpt-5.5-2026-01-01"), "gpt-5.5")
        self.assertEqual(_codex_price.dated_base("gpt-5.5-20260101"), "gpt-5.5")
        self.assertEqual(_codex_price.dated_base("gpt-5.5"), "gpt-5.5")

    def test_priority_multiplier(self):
        base = ModelRates(input_per_m=1.0, output_per_m=2.0,
                          cache_write_per_m=1.0, cache_read_per_m=0.1)
        self.assertEqual(_codex_price.priority_multiplier("gpt-5.5", base), 2.5)
        self.assertEqual(_codex_price.priority_multiplier("gpt-5.4", base), 2.0)

    def test_prepare_unpriced_none(self):
        pricing = _pricing.ModelPricing(_supp.Supplement(), _cat.PricingCatalog(),
                                        _cat.PricingCatalog())
        self.assertIsNone(_codex_price.prepare(pricing, "test-only-missing"))

    def test_prepare_sets_long_and_priority(self):
        pricing = _price({"gpt-5.5": ModelRates(
            input_per_m=1.0, output_per_m=2.0, cache_write_per_m=1.0,
            cache_read_per_m=0.1)})
        prepared = _codex_price.prepare(pricing, "gpt-5.5")
        assert prepared is not None
        self.assertEqual(prepared.rates.input_above, 10)
        self.assertEqual(prepared.rates.fast_multiplier, 2.5)

    def test_resolve_missing(self):
        pricing = _pricing.ModelPricing(_supp.Supplement(), _cat.PricingCatalog(),
                                        _cat.PricingCatalog())
        rates, base, fast_alias, has_base = _codex_price.resolve_rates(
            pricing, "test-only-missing")
        self.assertIsNone(rates)
        self.assertFalse(fast_alias)


class OpenCodeCodexTest(unittest.TestCase):
    def _db(self, path, cutoff_ms):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE credential (id TEXT, integration_id TEXT,"
                     " value TEXT, active INTEGER, time_created INTEGER,"
                     " time_updated INTEGER)")
        conn.execute("CREATE TABLE message (time_created INTEGER, id TEXT, data TEXT)")
        conn.execute(
            "INSERT INTO credential VALUES ('c1','openai',?,?,?,?)",
            ('{"type":"oauth","access":"test-only-a","refresh":"test-only-r"}',
             1, cutoff_ms, cutoff_ms))
        data = {"role": "assistant", "providerID": "openai", "cost": 0,
                "time": {"completed": cutoff_ms},
                "tokens": {"total": 150, "input": 100, "cache": {"read": 0, "write": 0},
                           "output": 50, "reasoning": 0},
                "model": {"id": "test-only-model"}, "finish": "stop"}
        conn.execute("INSERT INTO message VALUES (?,?,?)",
                     (cutoff_ms, "m1", _dump(data)))
        conn.commit()
        conn.close()

    def test_scan_oauth_zero_cost(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            cutoff_ms = int(dt.datetime(2026, 9, 23, 1,
                                        tzinfo=dt.timezone.utc).timestamp() * 1000)
            self._db(data_dir / "opencode-test-only.db", cutoff_ms)
            scan = _oc_codex.scan(data_dir, {}, cutoff_ms / 1000 - 1, _price())
            assert scan is not None
            today = next(item for item in scan.series.daily if item.date == "2026-09-23")
            self.assertEqual(today.total_tokens, 150)

    def test_non_oauth_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            db_path = data_dir / "opencode-test-only.db"
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE credential (id TEXT, integration_id TEXT,"
                         " value TEXT, active INTEGER, time_created INTEGER,"
                         " time_updated INTEGER)")
            conn.execute("INSERT INTO credential VALUES ('c1','openai',"
                         "'{\"type\":\"api\",\"key\":\"test-only-k\"}',1,1,1)")
            conn.commit()
            conn.close()
            self.assertIsNone(_oc_codex.scan(data_dir, {}, 0, _price()))

    def test_parse_rows_and_dedup(self):
        payload = _dump([[1000, 0, 150, "test-only-m",
                               100, 0, 0, 50, 0, "m1"]])
        rows = _oc_codex.parse_rows(payload)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].total, 150)
        doubled = _oc_codex.deduplicated(rows + rows)
        self.assertEqual(len(doubled), 1)


class OpenCodeScanTest(unittest.TestCase):
    def _db(self, path, cutoff_ms):
        conn = sqlite3.connect(path)
        conn.execute("CREATE TABLE message (time_created INTEGER, data TEXT)")
        for model_id, provider in (("test-only-hosted", "opencode"),
                                   ("other-model", "other")):
            data = {"role": "assistant", "providerID": provider, "cost": 0.25,
                    "tokens": {"total": 15}, "modelID": model_id}
            conn.execute("INSERT INTO message VALUES (?,?)",
                         (cutoff_ms, _dump(data)))
        conn.commit()
        conn.close()

    def test_hosted_ids_carried(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            cutoff_ms = int(dt.datetime(2026, 9, 23, 1,
                                        tzinfo=dt.timezone.utc).timestamp() * 1000)
            self._db(data_dir / "opencode-test-only.db", cutoff_ms)
            scan = _oc.scan(data_dir, cutoff_ms / 1000 - 1)
            assert scan is not None
            today = next(item for item in scan.series.daily if item.date == "2026-09-23")
            self.assertEqual(today.total_tokens, 15)
            self.assertTrue(_oc.has_hosted_usage(data_dir))


class AntigravityTest(unittest.TestCase):
    def _varint(self, value):
        out = bytearray()
        while value > 0x7F:
            out.append((value & 0x7F) | 0x80)
            value >>= 7
        out.append(value)
        return bytes(out)

    def _field(self, num, wire, payload):
        return self._varint((num << 3) | wire) + payload

    def _bytes(self, num, payload):
        return self._field(num, 2, self._varint(len(payload)) + payload)

    def _event_blob(self, model_id, stamp, system=2, inp=10, output=5, read=1):
        usage = (self._field(1, 0, self._varint(system))
                 + self._field(2, 0, self._varint(inp))
                 + self._field(3, 0, self._varint(output))
                 + self._field(5, 0, self._varint(read)))
        inner = self._field(1, 0, self._varint(stamp))
        timing = self._bytes(4, inner)
        wrapped = (self._bytes(19, model_id.encode())
                   + self._bytes(4, usage) + self._bytes(9, timing))
        return self._bytes(1, wrapped)

    def test_varint_and_fields(self):
        self.assertEqual(_proto.decode_varint(b"\x96\x01"), (150, 2))
        self.assertIsNone(_proto.decode_varint(b"\xff"))
        blob = self._bytes(3, b"test-only")
        self.assertEqual(_proto.bytes_field(3, blob), b"test-only")
        self.assertIsNone(_proto.bytes_field(9, blob))
        blob = self._field(2, 0, self._varint(42))
        self.assertEqual(_proto.varint_field(2, blob), 42)

    def test_generation_event(self):
        stamp = int(dt.datetime(2026, 9, 23, 1, tzinfo=dt.timezone.utc).timestamp())
        blob = self._event_blob("test-only-model", stamp)
        event = _proto.generation_event(blob)
        assert event is not None
        self.assertEqual(event.model_id, "test-only-model")
        self.assertEqual(event.input_tokens, 12)
        self.assertEqual(event.timestamp_s, stamp)
        self.assertIsNone(_proto.generation_event(b"\xff"))

    def test_candidates_and_empty_scan(self):
        self.assertEqual(_proto.bytes_field(1, b"") if False else
                         _anti.model_candidates("test-only-m-tiered", "Label"),
                         ["test-only-m", "Label"])
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(_anti.scan(Path(tmp), 0, _price()))


class PublishTest(unittest.TestCase):
    def test_build_emits_spend_and_trend(self):
        acc = Accumulator()
        acc.add("2026-09-23", 100, 1.0, "test-only-model")
        scan = acc.build()
        assert scan is not None

        from openusage_omarchy.spend import tiles as _tiles_mod
        metrics: dict[str, model.Metric] = {}
        _tiles_mod.append_token_usage(scan.series, metrics, NOW,
                                      model_usage=scan.model_usage,
                                      model_note="test-only-note")
        _tiles_mod.append_trend(scan.series, metrics, NOW, "test-only-note")
        card = model.CardRef(card_id="claude", family="claude", label="Claude")
        snap = model.Snapshot(card=card, plan=None,
                              fetched_at=NOW.isoformat(), metrics=metrics)
        table = _catalog.Catalog(providers=(
            _catalog.ProviderDef(provider_id="claude", display_name="Claude",
                                 mark="test-only", auto_enable=True),))
        batch = Batch(generation=1, results=[
            CardResult(card=card, snapshot=snap, error=None,
                       from_cache=False, fetched_at=NOW)],
                      started_at=NOW, ended_at=NOW)
        state = _publish.build(table, batch, {"claude": True}, "session-1",
                               "0.0", NOW, [], None,
                               pricing=("bundled", "test-only"))
        self.assertEqual(state["spend"]["periods"]["today"]["tokens"], 100)
        self.assertEqual(len(state["spend"]["trend"]["claude"]), 31)
        self.assertEqual(state["pricing"]["source"], "bundled")

    def test_empty_spend(self):
        table = _catalog.Catalog(providers=(
            _catalog.ProviderDef(provider_id="claude", display_name="Claude",
                                 mark="test-only", auto_enable=True),))
        state = _publish.build(table, None, {"claude": False}, "session-1",
                               "0.0", NOW, [], None)
        self.assertEqual(state["spend"]["periods"]["today"]["tokens"], 0)
        self.assertEqual(state["spend"]["trend"], {})


if __name__ == "__main__":
    unittest.main()
