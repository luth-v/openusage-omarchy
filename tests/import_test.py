"""Every lib module imports cleanly (run under -B; run.sh checks pycache)."""

import importlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class ImportTest(unittest.TestCase):
    def test_all_modules_import(self):
        base = ROOT / "lib" / "openusage_omarchy"
        modules = []
        for path in sorted(base.rglob("*.py")):
            rel = path.relative_to(base).with_suffix("")
            name = "openusage_omarchy." + ".".join(rel.parts)
            modules.append(name)
        self.assertGreater(len(modules), 10)
        for name in modules:
            importlib.import_module(name)


if __name__ == "__main__":
    unittest.main()
