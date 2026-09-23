"""Redaction rules. Synthetic secrets only; none of these are real."""

import io
import logging
import unittest

from openusage_omarchy import log, redact

JWT = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.SflKxwRJSMeKKF2QT4fwpMeJf36POk6yJV_adQssw5c"
SK = "sk-test-0123456789abcdef"
BEARER = "Bearer testbearertokenvalue123"


class RedactTest(unittest.TestCase):
    def test_mask_value(self):
        self.assertEqual(redact.mask_value("short"), "[REDACTED]")
        self.assertEqual(redact.mask_value("0123456789abcdef"), "0123...cdef")

    def test_patterns(self):
        cases = [
            f"token {JWT} here",
            f"key={SK} end",
            f"auth {BEARER} ok",
            "https://user:hunter2@example.com/x",
            "callback?key=abcdef123456&x=1",
            "mail me at jane.doe@example.com today",
        ]
        for text in cases:
            cleaned = redact.redact_text(text, home="/nowhere")
            for secret in (JWT, SK, "testbearertokenvalue123", "hunter2", "abcdef123456",
                           "jane.doe@example.com", "user:hunter2"):
                self.assertNotIn(secret, cleaned, text)

    def test_home_path(self):
        self.assertEqual(redact.redact_text("/home/u/.grok/auth.json", home="/home/u"),
                         "[PATH]/.grok/auth.json")

    def test_plain_text_untouched(self):
        text = "refresh end: 3/3 ok"
        self.assertEqual(redact.redact_text(text, home="/home/u"), text)

    def test_command_value_masked_by_key(self):
        cmd = {"v": 1, "cmd": "setKey", "provider": "zai", "value": SK}
        cleaned = redact.redact_command(cmd)
        assert isinstance(cleaned, dict)
        self.assertEqual(cleaned["value"], "[REDACTED]")
        self.assertEqual(cleaned["provider"], "zai")
        self.assertEqual(cmd["value"], SK)

    def test_log_handler_redacts(self):
        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        handler.setFormatter(log.RedactingFormatter("%(message)s"))
        logger = logging.getLogger("openusage_omarchy.redact-test")
        logger.handlers = [handler]
        logger.propagate = False
        logger.setLevel(logging.INFO)
        logger.info("saw %s and %s", SK, "jane.doe@example.com")
        out = stream.getvalue()
        self.assertNotIn(SK, out)
        self.assertNotIn("jane.doe@example.com", out)
        self.assertIn("sk-t...cdef", out)
        logger.handlers = []


if __name__ == "__main__":
    unittest.main()
