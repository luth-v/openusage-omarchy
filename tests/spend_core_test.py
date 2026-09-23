"""Spend core: JSONL discovery, scan cache, accumulator, tiles."""

import datetime as dt
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy import model
from openusage_omarchy.spend import jsonl as _jsonl
from openusage_omarchy.spend import scan_cache as _cache
from openusage_omarchy.spend import tiles as _tiles
from openusage_omarchy.spend.aggregate import (
    Accumulator, DailyUsageEntry, DailyUsageSeries,
    ModelUsageEntry, ModelUsageSeries, DailyModelUsageEntry, day_key,
)


def _scan(cost=1.0, tokens=100, day="2026-09-23", name="test-only-model"):
    acc = Accumulator()
    acc.add(day, tokens, cost, name)
    return acc.build()


class JsonlTest(unittest.TestCase):
    def test_discovers_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / "b.jsonl").write_text("{}\n")
            (base / "a.jsonl").write_text("{}\n")
            (base / "skip.txt").write_text("x")
            found = _jsonl.jsonl_files(base)
            self.assertEqual([Path(item.path).name for item in found],
                             ["a.jsonl", "b.jsonl"])

    def test_oversized_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "big.jsonl"
            path.write_bytes(b"x" * (_jsonl.MAX_RECORD + 10) + b"\n" + b'{"a":1}\n')
            records, oversized = _jsonl.read_records(str(path))
            assert records is not None
            self.assertEqual(oversized, 1)
            self.assertEqual(records, [b'{"a":1}'])

    def test_unreadable_none(self):
        records, _ = _jsonl.read_records("/nonexistent/test-only.jsonl")
        self.assertIsNone(records)

    def test_since_is_midnight(self):
        now = dt.datetime(2026, 9, 23, 15, 30, tzinfo=dt.timezone.utc)
        since = _jsonl.since_date(30, now)
        self.assertEqual((since.hour, since.minute), (0, 0))


class ScanCacheTest(unittest.TestCase):
    def test_save_and_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _cache.Store(Path(tmp), "test-only", 1)
            items = [{"ts": 1.0, "model": "test-only-m"}]
            store.save_record("id", "/tmp/test-only.jsonl", 10, 20.0, items)
            self.assertEqual(store.load_record("id", "/tmp/test-only.jsonl", 10, 20.0), items)
            self.assertIsNone(store.load_record("id", "/tmp/test-only.jsonl", 11, 20.0))

    def test_scan_parses_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            target = base / "a.jsonl"
            target.write_text('{"x":1}\n')
            stat = target.stat()
            files = [_jsonl.DiscoveredFile(path=str(target), size=stat.st_size,
                                           mtime=stat.st_mtime)]
            calls = []
            store = _cache.Store(base / "cache", "test-only", 1)
            out = store.scan(files, 0, "id", lambda records: calls.append(1) or [{"ok": True}])
            self.assertEqual(out, [{"ok": True}])
            out = store.scan(files, 0, "id", lambda records: [{"ok": False}])
            self.assertEqual(out, [{"ok": True}])
            self.assertEqual(len(calls), 1)

    def test_records_hold_totals_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = _cache.Store(Path(tmp), "test-only", 1)
            store.save_record("id", "/tmp/test-only.jsonl", 10, 20.0,
                              [{"model": "m", "tokens": 5}])
            found = store.load_record("id", "/tmp/test-only.jsonl", 10, 20.0)
            self.assertEqual(found, [{"model": "m", "tokens": 5}])


class AggregateTest(unittest.TestCase):
    def test_day_key_format(self):
        moment = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.timezone.utc)
        self.assertRegex(day_key(moment), r"^\d{4}-\d{2}-\d{2}$")

    def test_build_sorts_newest_first(self):
        acc = Accumulator()
        acc.add("2026-09-21", 10, 1.0, "m")
        acc.add("2026-09-23", 5, 0.5, "m")
        scan = acc.build()
        self.assertEqual([entry.date for entry in scan.series.daily],
                         ["2026-09-23", "2026-09-21"])

    def test_merged_sums_and_unions_unknown(self):
        first = _scan(cost=1.0, tokens=100, day="2026-09-23", name="a")
        second = _scan(cost=2.0, tokens=50, day="2026-09-23", name="b")
        second.unknown_by_day["2026-09-23"] = frozenset({"test-only-unknown"})
        merged = Accumulator.merged([first, second])
        assert merged is not None
        entry = merged.series.daily[0]
        self.assertEqual(entry.total_tokens, 150)
        self.assertAlmostEqual(entry.cost_usd, 3.0)
        self.assertIn("test-only-unknown", merged.unknown_by_day["2026-09-23"])

    def test_merged_none_when_empty(self):
        self.assertIsNone(Accumulator.merged([None, None]))


class TilesTest(unittest.TestCase):
    NOW = dt.datetime(2026, 9, 23, 12, 0, tzinfo=dt.timezone.utc)

    def test_today_yesterday_last30(self):
        series = DailyUsageSeries(daily=(
            DailyUsageEntry(date="2026-09-23", total_tokens=100, cost_usd=1.0),
            DailyUsageEntry(date="2026-09-22", total_tokens=50, cost_usd=0.5),
            DailyUsageEntry(date="2026-09-10", total_tokens=10, cost_usd=0.1),))
        metrics: dict[str, model.Metric] = {}
        _tiles.append_token_usage(series, metrics, self.NOW, estimated=True,
                                  model_usage=ModelUsageSeries(daily=()),
                                  model_note="test-only-note")
        self.assertIn("today", metrics)
        self.assertIn("yesterday", metrics)
        self.assertIn("last30", metrics)
        today = metrics["today"]
        assert isinstance(today, model.Values)
        self.assertTrue(today.values[0].estimated)
        last = metrics["last30"]
        assert isinstance(last, model.Values)
        self.assertEqual(last.values[-1].number, 160)

    def test_idle_day_has_no_tile(self):
        series = DailyUsageSeries(daily=(
            DailyUsageEntry(date="2026-09-23", total_tokens=0, cost_usd=0.0),))
        metrics: dict[str, model.Metric] = {}
        _tiles.append_token_usage(series, metrics, self.NOW)
        self.assertEqual(metrics, {})

    def test_trend_31_points_zero_filled(self):
        series = DailyUsageSeries(daily=(
            DailyUsageEntry(date="2026-09-23", total_tokens=100, cost_usd=1.0),))
        metrics: dict[str, model.Metric] = {}
        _tiles.append_trend(series, metrics, self.NOW, "test-only-note")
        trend = metrics["trend"]
        assert isinstance(trend, model.Chart)
        self.assertEqual(len(trend.points), 31)
        self.assertEqual(trend.points[-1].value, 100)
        self.assertEqual(trend.points[0].value, 0)

    def test_trend_empty_when_idle(self):
        series = DailyUsageSeries(daily=())
        metrics: dict[str, model.Metric] = {}
        _tiles.append_trend(series, metrics, self.NOW, "test-only-note")
        self.assertEqual(metrics, {})

    def test_breakdown_folds_small_and_unattributed(self):
        usage = ModelUsageSeries(daily=(
            DailyModelUsageEntry(date="2026-09-23", models=(
                ModelUsageEntry(model="big", total_tokens=950, cost_usd=9.5),
                ModelUsageEntry(model="tiny", total_tokens=5, cost_usd=0.05),
                ModelUsageEntry(model="Unattributed", total_tokens=500, cost_usd=5.0),)),))
        series = DailyUsageSeries(daily=(
            DailyUsageEntry(date="2026-09-23", total_tokens=1455, cost_usd=14.55),))
        metrics: dict[str, model.Metric] = {}
        _tiles.append_token_usage(series, metrics, self.NOW, model_usage=usage,
                                  model_note="test-only-note")
        today = metrics["today"]
        assert isinstance(today, model.Values)
        assert today.breakdown is not None
        names = [item["model"] for item in today.breakdown["models"]]
        self.assertIn("big", names)
        self.assertIn("Other", names)
        self.assertNotIn("Unattributed", names)

    def test_unknown_models_sorted(self):
        series = DailyUsageSeries(daily=(
            DailyUsageEntry(date="2026-09-23", total_tokens=10, cost_usd=1.0),))
        metrics: dict[str, model.Metric] = {}
        _tiles.append_token_usage(
            series, metrics, self.NOW,
            unknown_by_day={"2026-09-23": frozenset({"b-test-only", "a-test-only"})})
        today = metrics["today"]
        assert isinstance(today, model.Values)
        self.assertEqual(list(today.unknown_models), ["a-test-only", "b-test-only"])

    def test_source_note_fallback(self):
        note = _tiles.source_note("base", {"2026-09-23": frozenset({"gpt-5"})},
                                  {"2026-09-23"})
        self.assertIn("Fallback estimates", note)
        self.assertIn("GPT 5", note)


if __name__ == "__main__":
    unittest.main()
