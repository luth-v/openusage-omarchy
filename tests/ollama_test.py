"""Ollama collector: signed Cloud limits plus the never-auto-enable rule.

The crypto vector below is pinned against openssl (independent
implementation): same seed, same message, byte-identical signature.
"""

import base64
import json
import tempfile
import unittest
from pathlib import Path

from openusage_omarchy import model
from openusage_omarchy.providers import ollama
from openusage_omarchy.providers.ollama import crypto as _crypto

import support

FIX = Path(__file__).resolve().parent / "fixtures"

# openssl-pinned vector (seed, its pubkey, and the signature of MSG).
SEED = bytes.fromhex(
    "79b25e7048f3f75321dc0b77dd16cb373f6754e6b817634dbda16dd552620576")
PUB = bytes.fromhex(
    "acc870b790c1d2dc890f3d2965806b7f91bfa5f4e08c6830e22cf1bb11f5f3a5")
MSG = b"GET,/api/usage?ts=1788393600"
SIG = bytes.fromhex(
    "29f9a06d94e22b53c137734f27719ac42f54b224b27748035bc3f13a234851"
    "4ecdd2931c7ccafed7fd6584b3fa13b5e8a1143b53c796e126ce645a5f33f58706")


def _str(blob: bytes) -> bytes:
    return len(blob).to_bytes(4, "big") + blob


def _u32(number: int) -> bytes:
    return number.to_bytes(4, "big")


def build_pem(seed: bytes = SEED, pub: bytes = PUB,
              cipher: bytes = b"none", outer_pub: bytes | None = None,
              truncate: int = 0) -> str:
    """A minimal openssh-key-v1 PEM, with knobs for the reject cases."""
    pub_blob = _str(b"ssh-ed25519") + _str(outer_pub or pub)
    inner = (
        _u32(0x01020304) + _u32(0x01020304) + _str(b"ssh-ed25519")
        + _str(pub) + _str(seed + pub)
    )
    inner += bytes(range(1, (8 - len(inner) % 8) % 8 + 1))
    blob = (
        b"openssh-key-v1\x00" + _str(cipher) + _str(b"none") + _str(b"")
        + _u32(1) + _str(pub_blob) + _str(inner)
    )
    if truncate:
        blob = blob[:-truncate]
    body = base64.b64encode(blob).decode()
    wrapped = "\n".join(body[pos:pos + 64] for pos in range(0, len(body), 64))
    return f"-----BEGIN OPENSSH PRIVATE KEY-----\n{wrapped}\n-----END OPENSSH PRIVATE KEY-----\n"


def load(name: str):
    return json.loads((FIX / name).read_text())


def usage_url() -> str:
    return f"https://ollama.com/api/usage?ts={int(support.NOW.timestamp())}"


def account_url() -> str:
    return f"https://ollama.com/api/me?ts={int(support.NOW.timestamp())}"


def write_key(env, pem: str | None = None) -> None:
    path = ollama.key_path(env)
    path.parent.mkdir(parents=True)
    path.write_text(pem if pem is not None else build_pem())


class CryptoTest(unittest.TestCase):
    def test_pinned_vector(self):
        self.assertEqual(_crypto.public_from_seed(SEED), PUB)
        self.assertEqual(_crypto.sign(SEED, MSG), SIG)

    def test_pem_round_trip(self):
        parsed = _crypto.parse_openssh_private_key(build_pem())
        assert parsed is not None
        blob, seed = parsed
        self.assertEqual(seed, SEED)
        self.assertEqual(base64.b64decode(
            base64.b64encode(blob).decode())[:15], blob[:15])
        header = _crypto.authorization(blob, seed, "GET", "/api/usage?ts=1")
        public, _, signature = header.partition(":")
        self.assertEqual(base64.b64decode(public), blob)
        self.assertEqual(len(base64.b64decode(signature)), 64)

    def test_parse_rejects(self):
        self.assertIsNone(_crypto.parse_openssh_private_key("garbage"))
        self.assertIsNone(_crypto.parse_openssh_private_key(build_pem(cipher=b"aes256-ctr")))
        self.assertIsNone(_crypto.parse_openssh_private_key(build_pem(truncate=10)))
        self.assertIsNone(_crypto.parse_openssh_private_key(
            build_pem(outer_pub=b"\x00" * 32)))
        with self.assertRaises(ValueError):
            _crypto.public_from_seed(b"short")


class OllamaMapperTest(unittest.TestCase):
    def test_map_usage(self):
        plan, lines = ollama.map_usage(
            (FIX / "ollama_usage.json").read_bytes(),
            (FIX / "ollama_account.json").read_bytes(),
        )
        self.assertEqual(plan, "Pro")
        self.assertAlmostEqual(lines["session"].used, 34.9)
        self.assertAlmostEqual(lines["weekly"].used, 31.6)
        self.assertAlmostEqual(lines["monthly"].used, 5.3)
        self.assertIsNone(lines["session"].resets_at)
        last = lines["last4Weeks"]
        assert isinstance(last, model.Values)
        self.assertAlmostEqual(last.values[0].number, 1.5)

    def test_partial_and_empty(self):
        _, lines = ollama.map_usage(b'{"limits": {"weekly": {"usage": 0.5}}}', None)
        self.assertEqual(list(lines), ["weekly"])
        _, lines = ollama.map_usage(b'{"limits": {}}', None)
        self.assertEqual(lines, {})
        with self.assertRaises(ValueError):
            ollama.map_usage(b"{}", None)
        with self.assertRaises(ValueError):
            ollama.map_usage(b"broken", None)

    def test_plan_name(self):
        self.assertEqual(ollama.plan_name(b'{"plan": "max"}'), "Max")
        self.assertIsNone(ollama.plan_name(b"{}"))


class OllamaFetchTest(unittest.TestCase):
    def test_never_auto_enables(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_key(env)
            self.assertFalse(ollama.has_credentials(env))

    def test_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_key(env)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", usage_url(), load("ollama_usage.json"))
            env.http.add_json("POST", account_url(), load("ollama_account.json"))
            snap = ollama.fetch(ollama.cards(env)[0], env)
            self.assertEqual(snap.plan, "Pro")
            self.assertAlmostEqual(snap.metrics["session"].used, 34.9)
            call = env.http.calls[0]
            self.assertEqual(call[0], "GET")

    def test_not_signed_in_and_missing_key(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            with self.assertRaises(model.CollectorError) as ctx:
                ollama.fetch(ollama.cards(env)[0], env)
            self.assertEqual(ctx.exception.category, "auth")
            write_key(env)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add("GET", usage_url(), 401, b"{}")
            with self.assertRaises(model.CollectorError) as ctx:
                ollama.fetch(ollama.cards(env)[0], env)
            self.assertIn("signin", ctx.exception.message)

    def test_account_failure_keeps_meters(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_key(env)
            assert isinstance(env.http, support.FakeHttp)
            env.http.add_json("GET", usage_url(), load("ollama_usage.json"))
            env.http.add("POST", account_url(), 500, b"{}")
            snap = ollama.fetch(ollama.cards(env)[0], env)
            self.assertIsNone(snap.plan)
            self.assertIn("weekly", snap.metrics)

    def test_key_errors(self):
        with tempfile.TemporaryDirectory() as tmp, support.test_env(tmp) as env:
            write_key(env, "not a key")
            with self.assertRaises(model.CollectorError) as ctx:
                ollama.fetch(ollama.cards(env)[0], env)
            self.assertIn("signing key", ctx.exception.message)


if __name__ == "__main__":
    unittest.main()
