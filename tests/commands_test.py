"""Command parser table test. Unknown lines are ignored, never run."""

import unittest

from openusage_omarchy.daemon import commands


class CommandsTest(unittest.TestCase):
    def test_refresh_variants(self):
        cmd = commands.parse_line('{"v": 1, "cmd": "refresh"}')
        assert cmd is not None
        self.assertEqual(cmd.cmd, "refresh")
        self.assertIsNone(cmd.card_id)
        self.assertFalse(cmd.force)
        cmd = commands.parse_line('{"v": 1, "cmd": "refresh", "force": true, "cardId": "cursor"}')
        assert cmd is not None
        self.assertEqual(cmd.card_id, "cursor")
        self.assertTrue(cmd.force)

    def test_claim_reset(self):
        cmd = commands.parse_line('{"v": 1, "cmd": "claimReset", "cardId": "codex"}')
        assert cmd is not None
        self.assertEqual(cmd.cmd, "claimReset")
        self.assertEqual(cmd.card_id, "codex")
        self.assertIsNone(cmd.expiry)
        self.assertIsNone(cmd.request_id)
        cmd = commands.parse_line(
            '{"v": 1, "cmd": "claimReset", "cardId": "codex:aa",'
            ' "expiry": "2026-09-24T00:00:00+00:00", "requestId": "req-1"}'
        )
        assert cmd is not None
        self.assertEqual(cmd.expiry, "2026-09-24T00:00:00+00:00")
        self.assertEqual(cmd.request_id, "req-1")

    def test_blank_lines_ignored(self):
        self.assertIsNone(commands.parse_line(""))
        self.assertIsNone(commands.parse_line("   \n"))

    def test_key_commands(self):
        cmd = commands.parse_line(
            '{"v": 1, "cmd": "setKey", "provider": "openrouter",'
            ' "value": "test-only-k"}'
        )
        assert cmd is not None
        self.assertEqual(cmd.cmd, "setKey")
        self.assertEqual(cmd.provider, "openrouter")
        self.assertEqual(cmd.value, "test-only-k")
        cmd = commands.parse_line('{"v": 1, "cmd": "deleteKey", "provider": "zai"}')
        assert cmd is not None
        self.assertEqual(cmd.cmd, "deleteKey")
        self.assertEqual(cmd.provider, "zai")
        self.assertIsInstance(cmd, commands.DeleteKey)

    def test_describe_carries_provider(self):
        cmd = commands.parse_line(
            '{"v": 1, "cmd": "setKey", "provider": "zai", "value": "test-only-k"}'
        )
        assert cmd is not None
        described = commands.describe(cmd)
        self.assertEqual(described["provider"], "zai")
        self.assertIn("value", described)
        self.assertNotIn("test-only-k", repr(described))
        self.assertNotIn("test-only-k", repr(cmd))

    def test_logged_command_masks_value(self):
        from openusage_omarchy import redact

        cmd = commands.parse_line(
            '{"v": 1, "cmd": "setKey", "provider": "zai", "value": "test-only-k"}'
        )
        assert cmd is not None
        logged = redact.redact_command(commands.describe(cmd))
        self.assertEqual(logged["value"], "[REDACTED]")
        self.assertNotIn("test-only-k", repr(logged))

    def test_service_extras(self):
        cmd = commands.parse_line('{"v": 1, "cmd": "checkUpdate"}')
        assert cmd is not None
        self.assertEqual(cmd.cmd, "checkUpdate")
        cmd = commands.parse_line(
            '{"v": 1, "cmd": "snoozeUpdate", "version": "v0.2.0"}')
        assert cmd is not None
        self.assertEqual(cmd.version, "v0.2.0")
        cmd = commands.parse_line('{"v": 1, "cmd": "installUpdate"}')
        assert cmd is not None

    def test_malformed(self):
        bad = [
            "{not json",
            "[1, 2]",
            '{"v": 2, "cmd": "refresh"}',
            '{"v": 1}',
            '{"v": 1, "cmd": "reboot"}',
            '{"v": 1, "cmd": "setKey", "value": "x"}',
            '{"v": 1, "cmd": "setKey", "provider": "openrouter"}',
            '{"v": 1, "cmd": "setKey", "provider": "openrouter", "value": "  "}',
            '{"v": 1, "cmd": "setKey", "provider": "cursor", "value": "x"}',
            '{"v": 1, "cmd": "deleteKey"}',
            '{"v": 1, "cmd": "deleteKey", "provider": "cursor"}',
            '{"v": 1, "cmd": "refresh", "provider": "zai"}',
            '{"v": 1, "cmd": "refresh", "value": "x"}',
            '{"v": 1, "cmd": "refresh", "cardId": ""}',
            '{"v": 1, "cmd": "refresh", "cardId": 7}',
            '{"v": 1, "cmd": "claimReset"}',
            '{"v": 1, "cmd": "claimReset", "cardId": ""}',
            '{"v": 1, "cmd": "claimReset", "cardId": "codex", "expiry": 7}',
            '{"v": 1, "cmd": "claimReset", "cardId": "codex", "requestId": ""}',
            '{"v": 1, "cmd": "snoozeUpdate"}',
            '{"v": 1, "cmd": "snoozeUpdate", "version": ""}',
            '{"v": 1, "cmd": "setLogLevel"}',
            '{"v": 1, "cmd": "setLogLevel", "level": "Verbose"}',
            '{"v": 1, "cmd": "setShortcut"}',
            '{"v": 1, "cmd": "setShortcut", "combo": {"mods": [], "key": "O"}}',
            '{"v": 1, "cmd": "setShortcut", "combo": "SUPER+O"}',
            '{"v": 1, "cmd": "checkUpdate", "cardId": "codex"}',
            '{"v": 1, "cmd": "installUpdate", "force": true, "version": "v1"}',
            '{"v": 1, "cmd": "refresh", "level": "Debug"}',
        ]
        for line in bad:
            with self.assertRaises(commands.InvalidCommand, msg=line):
                commands.parse_line(line)


if __name__ == "__main__":
    unittest.main()
