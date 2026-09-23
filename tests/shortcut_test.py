"""Shortcut bind grammar. Only {mods, key} in, one fixed line out."""

import tempfile
import unittest
import json
import subprocess
from pathlib import Path

from openusage_omarchy import shortcut

import support

LINE = ("bind = SUPER SHIFT, O, exec, "
        "omarchy-shell luth-v.openusage-omarchy toggle\n")


class GrammarTest(unittest.TestCase):
    def test_recorder_key_table_matches_python(self):
        root = Path(__file__).resolve().parent.parent
        script = ("const fs=require('fs'),vm=require('vm'),c=vm.createContext({});"
                  "vm.runInContext(fs.readFileSync('js/Settings.js','utf8'),c);"
                  "process.stdout.write(JSON.stringify(c.NAMED_KEYS));")
        result = subprocess.run(["node", "-e", script], cwd=root,
                                capture_output=True, check=True, timeout=10)
        self.assertEqual(set(json.loads(result.stdout)), set(shortcut.NAMED_KEYS))

    def test_valid_combo(self):
        combo = shortcut.valid_combo({"mods": ["SHIFT", "SUPER"], "key": "o"})
        self.assertEqual(combo, {"mods": ["SUPER", "SHIFT"], "key": "O"})
        self.assertEqual(shortcut.render(combo), LINE)

    def test_named_and_function_keys(self):
        self.assertEqual(
            shortcut.valid_combo({"mods": ["SUPER"], "key": "Space"})["key"],
            "SPACE")
        self.assertEqual(
            shortcut.valid_combo({"mods": ["ALT"], "key": "F12"})["key"], "F12")

    def test_rejects_injection(self):
        bad = [
            {"mods": ["SUPER"], "key": "O\nbind = , x, exec, evil"},
            {"mods": ["SUPER"], "key": "O, x"},
            {"mods": ["SUPER"], "key": "$(evil)"},
            {"mods": ["SUPER"], "key": "O;evil"},
            {"mods": ["SUPER"], "key": "`evil`"},
            {"mods": ["SUPER"], "key": ""},
            {"mods": ["SUPER"], "key": 7},
            {"mods": ["SUPER", "BOGUS"], "key": "O"},
            {"mods": "SUPER", "key": "O"},
            {"mods": [], "key": "O"},
            {"mods": ["SUPER"], "key": "SUPER"},
            "SUPER+O",
            None,
        ]
        for combo in bad:
            self.assertIsNone(shortcut.valid_combo(combo), combo)

    def test_display_roundtrip(self):
        self.assertEqual(shortcut.parse_display("Super+Shift+O"),
                         {"mods": ["SUPER", "SHIFT"], "key": "O"})
        self.assertIsNone(shortcut.parse_display(""))
        self.assertIsNone(shortcut.parse_display("O"))
        self.assertIsNone(shortcut.parse_display("Bogus+O"))

    def test_apply_writes_and_removes(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            combo = {"mods": ["SUPER", "SHIFT"], "key": "O"}
            self.assertTrue(shortcut.apply(env.paths, combo))
            target = env.paths.bind_file
            self.assertEqual(target.read_text(encoding="utf-8"), LINE)
            self.assertFalse(shortcut.apply(env.paths, combo))  # in sync
            shortcut.reconcile(env.paths, "")
            self.assertFalse(target.exists())

    def test_reconcile_follows_display_string(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            shortcut.reconcile(env.paths, "Super+Shift+O")
            self.assertEqual(env.paths.bind_file.read_text(encoding="utf-8"),
                             LINE)
            shortcut.reconcile(env.paths, "Alt+F12")
            self.assertIn("ALT, F12", env.paths.bind_file.read_text(
                encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
