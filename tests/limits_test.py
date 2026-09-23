"""Limits projection: shape, math, matching, and the G2 email rule."""

import datetime as dt
import unittest

from openusage_omarchy import catalog, model
from openusage_omarchy.api import limits

NOW = dt.datetime(2026, 9, 23, 9, 0, tzinfo=dt.timezone.utc)


def snap(**metrics: model.Metric) -> model.Snapshot:
    return model.Snapshot(
        card=model.CardRef(card_id="cursor", family="cursor", label="Cursor"),
        plan="Pro",
        fetched_at=NOW.isoformat(),
        metrics=dict(metrics),
    )


class LimitsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.table = catalog.cached()

    def test_envelope(self):
        out = limits.project(
            {"cursor": snap(auto=model.Progress(metric_id="auto", used=40, limit=100,
                                                 resets_at=NOW.isoformat(), period_ms=2_678_400_000))},
            {},
            self.table,
            NOW,
        )
        self.assertEqual(out["schema"], "openusage.limits.v1")
        provider = out["providers"]["cursor"]
        self.assertEqual(provider["displayName"], "Cursor")
        self.assertEqual(provider["plan"], "Pro")
        self.assertFalse(provider["stale"])
        resource = provider["resources"]["autoUsage"]
        self.assertEqual(resource["kind"], "consumption")
        self.assertEqual(resource["unit"], "percent")
        self.assertEqual(resource["used"], 40)
        self.assertEqual(resource["remaining"], 60)
        self.assertAlmostEqual(resource["utilization"], 0.4)
        self.assertEqual(resource["windowSeconds"], 2678400.0)

    def test_dollar_unit(self):
        out = limits.project(
            {"cursor": snap(onDemand=model.Progress(metric_id="onDemand", used=12.5, limit=50,
                                                       format_kind="dollars"))},
            {},
            self.table,
            NOW,
        )
        resource = out["providers"]["cursor"]["resources"]["onDemand"]
        self.assertEqual(resource["unit"], "usd")

    def test_stale_and_expiry(self):
        old = NOW - dt.timedelta(seconds=600)
        snapshot = model.Snapshot(
            card=model.CardRef(card_id="cursor", family="cursor", label="Cursor"),
            plan=None,
            fetched_at=old.isoformat(),
            metrics={"auto": model.Progress(metric_id="auto", used=1, limit=100)},
        )
        out = limits.project({"cursor": snapshot}, {}, self.table, NOW)
        provider = out["providers"]["cursor"]
        self.assertTrue(provider["stale"])
        self.assertEqual(provider["expiresAt"], (old + dt.timedelta(seconds=300)).isoformat())

    def test_errors_and_unmapped_metrics(self):
        out = limits.project(
            {"cursor": snap(payAsYouGo=model.Badge(metric_id="payAsYouGo", text="Disabled"))},
            {"cursor": model.ErrorInfo("transport", "offline")},
            self.table,
            NOW,
        )
        self.assertEqual(out["providers"]["cursor"]["resources"], {})
        self.assertEqual(out["errors"], [{"providerId": "cursor", "message": "offline"}])

    def test_display_name_never_email(self):
        snapshot = model.Snapshot(
            card=model.CardRef(card_id="claude", family="claude",
                               label="Acme · jane.doe@example.com"),
            plan="Team",
            fetched_at=NOW.isoformat(),
            metrics={"session": model.Progress(metric_id="session", used=10, limit=100)},
        )
        out = limits.project({"claude": snapshot}, {}, self.table, NOW)
        self.assertEqual(out["providers"]["claude"]["displayName"], "Claude")

    def test_extra_cards_number_without_email(self):
        first = model.Snapshot(
            card=model.CardRef(card_id="claude", family="claude",
                               label="Claude"),
            plan="Team", fetched_at=NOW.isoformat(), metrics={})
        second = model.Snapshot(
            card=model.CardRef(card_id="claude:ab12", family="claude",
                               label="Acme · jane.doe@example.com"),
            plan="Team", fetched_at=NOW.isoformat(), metrics={})
        out = limits.project({"claude": first, "claude:ab12": second}, {},
                             self.table, NOW)
        self.assertEqual(out["providers"]["claude"]["displayName"], "Claude")
        self.assertEqual(out["providers"]["claude:ab12"]["displayName"],
                         "Claude 2")
        self.assertNotIn("jane.doe@example.com", repr(out))

    def test_values_balance_and_expiry(self):
        snapshot = model.Snapshot(
            card=model.CardRef(card_id="codex", family="codex", label="Codex"),
            plan="Plus",
            fetched_at=NOW.isoformat(),
            metrics={
                "credits": model.Values(
                    metric_id="credits",
                    values=(
                        model.ScalarValue(number=3, kind="count", label="credits"),
                        model.ScalarValue(number=1.5, kind="dollars", estimated=True),
                    ),
                    expiries_at=("2026-10-01T00:00:00+00:00",),
                ),
            },
        )
        out = limits.project({"codex": snapshot}, {}, self.table, NOW)
        resources = out["providers"]["codex"]["resources"]
        self.assertEqual(resources["credits"]["available"], 3)
        self.assertEqual(resources["credits"]["unit"], "credits")
        self.assertEqual(resources["credits"]["expiresAt"], ["2026-10-01T00:00:00+00:00"])
        self.assertEqual(resources["creditValue"]["unit"], "usd")
        self.assertTrue(resources["creditValue"]["estimated"])

    def test_values_consumption(self):
        snapshot = model.Snapshot(
            card=model.CardRef(card_id="claude", family="claude", label="Claude"),
            plan="Pro",
            fetched_at=NOW.isoformat(),
            metrics={
                "extra": model.Values(
                    metric_id="extra",
                    values=(model.ScalarValue(number=2.5, kind="dollars"),),
                ),
            },
        )
        out = limits.project({"claude": snapshot}, {}, self.table, NOW)
        resources = out["providers"]["claude"]["resources"]
        # catalog maps claude/extra -> extraUsage (consumption, usd)
        self.assertEqual(resources["extraUsage"]["used"], 2.5)
        self.assertEqual(resources["extraUsage"]["unit"], "usd")

    def test_copilot_personal_credits_count(self):
        snapshot = model.Snapshot(
            card=model.CardRef(card_id="copilot", family="copilot", label="Copilot"),
            plan="Business",
            fetched_at=NOW.isoformat(),
            metrics={
                "premium": model.Values(
                    metric_id="premium",
                    values=(model.ScalarValue(number=321, kind="count"),),
                ),
                "orgCredits": model.Values(
                    metric_id="orgCredits",
                    values=(model.ScalarValue(number=1200, kind="count",
                                              label="credits"),),
                ),
            },
        )
        out = limits.project({"copilot": snapshot}, {}, self.table, NOW)
        resources = out["providers"]["copilot"]["resources"]
        self.assertEqual(resources["premiumCredits"]["kind"], "consumption")
        self.assertEqual(resources["premiumCredits"]["unit"], "credits")
        self.assertEqual(resources["premiumCredits"]["used"], 321)
        self.assertEqual(resources["orgCredits"]["available"], 1200)

    def test_progress_keeps_live_unit(self):
        out = limits.project(
            {"grok": model.Snapshot(
                card=model.CardRef(card_id="grok", family="grok", label="Grok"),
                plan="SuperGrok",
                fetched_at=NOW.isoformat(),
                metrics={"weekly": model.Progress(
                    metric_id="weekly", used=25, limit=100,
                    suffix="credits")})},
            {},
            self.table,
            NOW,
        )
        resource = out["providers"]["grok"]["resources"]["weekly"]
        self.assertEqual(resource["unit"], "percent")

    def test_match_cards(self):
        cards = [
            model.CardRef(card_id="cursor", family="cursor", label="Cursor"),
            model.CardRef(card_id="codex:aa11", family="codex", label="Codex 1"),
            model.CardRef(card_id="codex:bb22", family="codex", label="Codex 2"),
        ]
        self.assertEqual([c.card_id for c in limits.match_cards("cursor", cards)], ["cursor"])
        self.assertEqual([c.card_id for c in limits.match_cards("codex:aa11", cards)], ["codex:aa11"])
        self.assertEqual(
            [c.card_id for c in limits.match_cards("codex", cards)], ["codex:aa11", "codex:bb22"]
        )
        self.assertEqual(limits.match_cards("nope", cards), [])


if __name__ == "__main__":
    unittest.main()
