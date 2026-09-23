"""Proxy config parsing. Bad config leaves proxying off, silently."""

import json
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy import proxy

import support


def write_config(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


class ProxyTest(unittest.TestCase):
    def test_http_with_auth(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            target = env.paths.proxy_config
            write_config(target, {"proxy": {
                "enabled": True,
                "url": "http://user:pass@proxy.example.com:8080"}})
            config = proxy.load(target)
            self.assertIsNotNone(config)
            assert config is not None
            self.assertEqual(config.scheme, "http")
            self.assertEqual(config.host, "proxy.example.com")
            self.assertEqual(config.port, 8080)
            self.assertTrue(config.supported)

    def test_default_ports(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            target = env.paths.proxy_config
            write_config(target, {"proxy": {
                "enabled": True, "url": "https://proxy.example.com"}})
            config = proxy.load(target)
            assert config is not None
            self.assertEqual(config.port, 443)

    def test_socks5_is_inert(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            target = env.paths.proxy_config
            write_config(target, {"proxy": {
                "enabled": True, "url": "socks5://127.0.0.1:10808"}})
            self.assertIsNone(proxy.load(target))

    def test_bad_configs_stay_off(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            target = env.paths.proxy_config
            for payload in (
                {"proxy": {"enabled": False,
                           "url": "http://127.0.0.1:8080"}},
                {"proxy": {"enabled": True, "url": "gopher://x"}},
                {"proxy": {"enabled": True, "url": "http://"}},
                {"proxy": {"enabled": True}},
                {"proxy": "http://127.0.0.1:8080"},
                {},
            ):
                write_config(target, payload)
                self.assertIsNone(proxy.load(target), payload)
            missing = target.parent / "absent.json"
            self.assertIsNone(proxy.load(missing))

    def test_loopback_bypass(self):
        self.assertTrue(proxy.is_loopback("http://127.0.0.1:6736/v1/limits"))
        self.assertTrue(proxy.is_loopback("http://localhost:9999/"))
        self.assertTrue(proxy.is_loopback("http://[::1]/"))
        self.assertFalse(proxy.is_loopback("https://api.github.com/x"))


if __name__ == "__main__":
    unittest.main()
