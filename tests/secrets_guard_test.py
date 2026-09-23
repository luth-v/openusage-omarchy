"""Fixtures hold no real-shaped secrets. Placeholders like test-only-* only."""

import re
import unittest
from pathlib import Path

FIX = Path(__file__).resolve().parent / "fixtures"

PATTERNS = [
    re.compile(r"[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._~+/-]{8,}={0,2}"),
]


class SecretsGuardTest(unittest.TestCase):
    def test_fixtures_clean(self):
        files = sorted(FIX.glob("*"))
        self.assertGreater(len(files), 0)
        for path in files:
            text = path.read_text(encoding="utf-8")
            for pattern in PATTERNS:
                self.assertIsNone(pattern.search(text), f"{path.name}: {pattern.pattern}")


if __name__ == "__main__":
    unittest.main()
