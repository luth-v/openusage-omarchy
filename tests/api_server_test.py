"""Local HTTP API. Pure router plus a loopback-only transport test."""

import json
import unittest
import urllib.request

from openusage_omarchy import catalog, model
from openusage_omarchy.api import server

TABLE = catalog.cached()


def snap(card_id="codex", family="codex"):
    return model.Snapshot(
        card=model.CardRef(card_id=card_id, family=family, label="Codex"),
        plan="Pro",
        fetched_at="2026-09-23T09:00:00+00:00",
        metrics={"session": model.Progress(
            metric_id="session", used=42, limit=100)},
    )


def state():
    return server.ApiState(
        enabled_ordered=["codex"], known={"codex", "claude"},
        snapshots={"codex": snap()}, errors={},
        generated_at=snap_fetched())


def snap_fetched():
    import datetime as dt
    return dt.datetime(2026, 9, 23, 9, 1, tzinfo=dt.timezone.utc)


class RouterTest(unittest.TestCase):
    def test_collection_uses_layout_enablement(self):
        layout = {"schema": "openusage-omarchy.layout.v1",
                  "firstRunCompleted": True,
                  "order": ["codex", "claude"],
                  "cards": {"codex": {"enabled": False},
                            "claude": {"enabled": True}}}
        built = server.build_state({"codex": snap()}, {}, layout, TABLE,
                                   snap_fetched(), {"codex": True})
        self.assertEqual(built.enabled_ordered, ["claude"])
        status, body = server.route("GET", "/v1/limits", built, TABLE)
        self.assertEqual(status, 200)
        self.assertNotIn("codex", json.loads(body)["providers"])

    def test_limits_collection(self):
        status, body = server.route("GET", "/v1/limits", state(), TABLE)
        self.assertEqual(status, 200)
        assert body is not None
        envelope = json.loads(body)
        self.assertEqual(envelope["schema"], "openusage.limits.v1")
        self.assertIn("codex", envelope["providers"])

    def test_limits_single_and_family(self):
        status, body = server.route("GET", "/v1/limits/codex", state(), TABLE)
        self.assertEqual(status, 200)
        assert body is not None
        self.assertIn("codex", json.loads(body)["providers"])
        status, _ = server.route("GET", "/v1/limits/nope", state(), TABLE)
        self.assertEqual(status, 404)

    def test_usage_collection_and_single(self):
        status, body = server.route("GET", "/v1/usage", state(), TABLE)
        self.assertEqual(status, 200)
        assert body is not None
        rows = json.loads(body)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["providerId"], "codex")
        status, body = server.route("GET", "/v1/usage/claude", state(), TABLE)
        self.assertEqual(status, 200)
        assert body is not None
        self.assertEqual(json.loads(body), [])

    def test_usage_unknown_is_404(self):
        status, body = server.route("GET", "/v1/usage/nope", state(), TABLE)
        self.assertEqual(status, 404)
        assert body is not None
        self.assertEqual(json.loads(body), {"error": "provider_not_found"})

    def test_method_and_route_errors(self):
        status, body = server.route("POST", "/v1/limits", state(), TABLE)
        self.assertEqual(status, 405)
        assert body is not None
        self.assertEqual(json.loads(body), {"error": "method_not_allowed"})
        status, _ = server.route("GET", "/v1/nope", state(), TABLE)
        self.assertEqual(status, 404)
        status, body = server.route("OPTIONS", "/v1/limits", state(), TABLE)
        self.assertEqual(status, 204)
        self.assertIsNone(body)

    def test_query_string_ignored(self):
        status, _ = server.route("GET", "/v1/limits?x=1", state(), TABLE)
        self.assertEqual(status, 200)


class TransportTest(unittest.TestCase):
    def test_binds_loopback_only(self):
        app = server.Server(state, TABLE, port=0)
        self.assertTrue(app.start())
        try:
            address = app.address
            assert address is not None
            host, port = address
            self.assertEqual(host, "127.0.0.1")
            with urllib.request.urlopen(
                    f"http://127.0.0.1:{port}/v1/usage",
                    timeout=5) as reply:  # noqa: S310
                self.assertEqual(reply.status, 200)
                self.assertEqual(
                    reply.headers.get("Access-Control-Allow-Origin"), "*")
                rows = json.loads(reply.read())
            self.assertEqual(rows[0]["providerId"], "codex")
        finally:
            app.stop()


if __name__ == "__main__":
    unittest.main()
