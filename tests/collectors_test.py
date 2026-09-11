import datetime as dt
import importlib.machinery
import importlib.util
import io
import json
import urllib.error
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


def load(name):
    loader = importlib.machinery.SourceFileLoader(name, str(Path('bin')/('openusage-'+name)))
    spec = importlib.util.spec_from_loader(name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    return module


class Collectors(unittest.TestCase):
    def test_opencode_units_and_invalid_windows(self):
        m = load('opencode')
        result = m.parse_limits({'usage': {'rolling': {'percent': 1, 'resetsAt': '2027-01-01T00:00:00Z'}, 'weekly': {'percent': None}}})
        self.assertEqual(result[0]['percent'], .01)
        self.assertEqual(result[0]['title'], 'Session')
        for payload in ({}, {'error': 'denied'}, {'usage': {'rolling': {'percent': True}}}):
            with self.assertRaises(ValueError):
                m.parse_limits(payload)

    def test_opencode_missing_login(self):
        m = load('opencode')
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'OPENCODE_DATA_DIR': temp}):
            record = m.collect(True)
        self.assertFalse(record['ready'])
        self.assertEqual(record['usageStatusText'], 'Not logged in')
        self.assertEqual(record['limits'], [])

    def test_opencode_probe_reuse_force_and_failure(self):
        m = load('opencode')
        payload = {'usage': {'weekly': {'percent': 40, 'resetsAt': '2099-01-01T00:00:00Z'}}}
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {'OPENCODE_DATA_DIR': temp, 'XDG_CACHE_HOME': temp}):
            (Path(temp)/'auth.json').write_text(json.dumps({'opencode-go': {'type': 'api', 'key': 'test-only-key'}}))
            with patch.object(m.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(payload).encode())) as request:
                self.assertTrue(m.collect()['ready'])
                self.assertEqual(request.call_count, 1)
                self.assertEqual(m.collect()['limits'][0]['percent'], .4)
                self.assertEqual(request.call_count, 1)
            with patch.object(m.urllib.request, 'urlopen', side_effect=urllib.error.URLError('offline')) as request:
                failed = m.collect(True)
                self.assertEqual(request.call_count, 1)
                self.assertEqual(failed['limits'][0]['percent'], .4)
                self.assertEqual(failed['usageStatusText'], 'Refresh failed')
            cache = Path(temp)/'openusage/opencode-limits.json'
            self.assertEqual(cache.stat().st_mode & 0o777, 0o600)
            self.assertNotIn('test-only-key', cache.read_text())

    def test_reset_aware_fallback(self):
        for name in ('cursor', 'grok'):
            m = load(name)
            cached = {'limits': [{'label': 'Expired', 'resetsAt': '2000-01-01T00:00:00Z'}, {'label': 'Future', 'resetsAt': '2099-01-01T00:00:00Z'}]}
            self.assertEqual([x['label'] for x in m.usable_cached_limits(cached)], ['Future'])

    def test_cursor_grok_percent_units(self):
        c, g = load('cursor'), load('grok')
        self.assertEqual(c.limits_from_usage({'planUsage': {'autoPercentUsed': 1}})[0]['percent'], .01)
        self.assertEqual(g.limits_from_billing({'config': {'creditUsagePercent': 1}})[0][0]['percent'], .01)


if __name__ == '__main__':
    unittest.main()
