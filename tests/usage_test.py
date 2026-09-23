"""Legacy /v1/usage projection. Values rows read as combined text."""

import unittest

from openusage_omarchy import catalog, model
from openusage_omarchy.api import usage

TABLE = catalog.cached()


def snap(card_id="codex", family="codex", metrics=None, plan="Pro"):
    return model.Snapshot(
        card=model.CardRef(card_id=card_id, family=family, label="Codex"),
        plan=plan,
        fetched_at="2026-09-23T09:00:00+00:00",
        metrics=metrics or {},
    )


class UsageTest(unittest.TestCase):
    def test_progress_line(self):
        snapshots = {"codex": snap(metrics={
            "session": model.Progress(
                metric_id="session", used=42, limit=100,
                resets_at="2026-09-23T14:00:00+00:00", period_ms=18000000)})}
        out = usage.project(snapshots, TABLE)
        self.assertEqual(len(out), 1)
        row = out[0]
        self.assertEqual(row["providerId"], "codex")
        self.assertEqual(row["displayName"], "Codex")
        self.assertEqual(row["lines"], [{
            "type": "progress", "label": "Session", "used": 42, "limit": 100,
            "format": {"kind": "percent"},
            "resetsAt": "2026-09-23T14:00:00+00:00",
            "periodDurationMs": 18000000, "color": None,
        }])

    def test_values_line_reads_as_text(self):
        snapshots = {"claude": snap(card_id="claude", family="claude", metrics={
            "today": model.Values(
                metric_id="today",
                values=(model.ScalarValue(number=5.17, kind="dollars"),
                        model.ScalarValue(number=9200000, kind="count",
                                           label="tokens")))})}
        out = usage.project(snapshots, TABLE)
        line = out[0]["lines"][0]
        self.assertEqual(line["type"], "text")
        self.assertEqual(line["value"], "$5.17 · 9.2M tokens")
        self.assertIsNone(line["subtitle"])

    def test_badge_and_chart(self):
        snapshots = {"grok": snap(card_id="grok", family="grok", metrics={
            "paygo": model.Badge(metric_id="paygo", text="2500 cap"),
            "trend": model.Chart(
                metric_id="trend",
                points=(model.ChartPoint(label="Sep 22", value=1200,
                                         value_label="1.2K tokens"),),
                note="Estimated from local logs.")})}
        out = usage.project(snapshots, TABLE)
        kinds = [line["type"] for line in out[0]["lines"]]
        self.assertIn("badge", kinds)
        self.assertIn("barChart", kinds)

    def test_display_names_hide_emails(self):
        snapshots = {
            "claude": snap(card_id="claude", family="claude"),
            "claude:ab12": model.Snapshot(
                card=model.CardRef(card_id="claude:ab12", family="claude",
                                   label="Acme jane@example.com"),
                plan=None, fetched_at="2026-09-23T09:00:00+00:00",
                metrics={}),
        }
        out = usage.project(snapshots, TABLE)
        names = [row["displayName"] for row in out]
        self.assertEqual(names, ["Claude", "Claude 2"])
        self.assertNotIn("jane@example.com", repr(out))

    def test_compact_numbers(self):
        self.assertEqual(
            usage.legacy_value_string((model.ScalarValue(
                number=1500, kind="count", label="requests"),)), "1.5K requests")
        self.assertEqual(
            usage.legacy_value_string((model.ScalarValue(
                number=42, kind="count"),)), "42")


if __name__ == "__main__":
    unittest.main()
