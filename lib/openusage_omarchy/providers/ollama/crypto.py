"""Ollama Cloud credential: OpenSSH key parse plus Ed25519 signing.

Ollama links ``~/.ollama/id_ed25519`` to an ollama.com account on
``ollama signin``. Requests carry ``Authorization: <pub>:<sig>`` over the
string ``"<METHOD>,<uri>"``, exactly as the Ollama CLI signs. The key never
leaves the machine; only signatures go out.

Ed25519 is RFC 8032 in pure Python (stdlib only: no third-party deps are
allowed). The test vectors in ``tests/ollama_test.py`` pin it to the RFC.
"""

from __future__ import annotations

import base64
import hashlib

_Q = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)
_KEY_TYPE = b"ssh-ed25519"
_MAGIC = b"openssh-key-v1\x00"


def _inv(value: int) -> int:
    return pow(value, _Q - 2, _Q)


def _xrecover(y: int) -> int:
    num = (y * y - 1) % _Q
    den = (_D * y * y + 1) % _Q
    root = pow(num * _inv(den) % _Q, (_Q + 3) // 8, _Q)
    if (root * root - num * _inv(den)) % _Q != 0:
        root = (root * _I) % _Q
    return _Q - root if root % 2 else root


_BASE_Y = (4 * _inv(5)) % _Q
_BASE = (_xrecover(_BASE_Y), _BASE_Y)


def _add(point_p: tuple[int, int], point_q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = point_p
    x2, y2 = point_q
    shared = _D * x1 * x2 * y1 * y2 % _Q
    x3 = (x1 * y2 + x2 * y1) * _inv((1 + shared) % _Q) % _Q
    y3 = (y1 * y2 + x1 * x2) * _inv((1 - shared) % _Q) % _Q
    return x3, y3


def _scalarmult(point: tuple[int, int], scalar: int) -> tuple[int, int]:
    acc = (0, 1)
    while scalar:
        if scalar & 1:
            acc = _add(acc, point)
        point = _add(point, point)
        scalar >>= 1
    return acc


def _encode_point(point: tuple[int, int]) -> bytes:
    x, y = point
    return ((y & ((1 << 255) - 1)) | ((x & 1) << 255)).to_bytes(32, "little")


def _scalar_from_seed(seed: bytes) -> int:
    digest = hashlib.sha512(seed).digest()

    def _bit(index: int) -> int:
        return (digest[index // 8] >> (index % 8)) & 1

    return 2**254 + sum(2**index * _bit(index) for index in range(3, 254))


def public_from_seed(seed: bytes) -> bytes:
    """The 32-byte Ed25519 public key for a 32-byte seed."""
    if len(seed) != 32:
        raise ValueError("bad seed length")
    return _encode_point(_scalarmult(_BASE, _scalar_from_seed(seed)))


def sign(seed: bytes, message: bytes) -> bytes:
    """The 64-byte Ed25519 signature of a message under a seed."""
    if len(seed) != 32:
        raise ValueError("bad seed length")
    digest = hashlib.sha512(seed).digest()
    secret = _scalar_from_seed(seed)
    nonce = int.from_bytes(
        hashlib.sha512(digest[32:] + message).digest(), "little") % _L
    point_r = _scalarmult(_BASE, nonce)
    encoded_r = _encode_point(point_r)
    encoded_a = _encode_point(_scalarmult(_BASE, secret))
    challenge = int.from_bytes(
        hashlib.sha512(encoded_r + encoded_a + message).digest(), "little")
    scalar_s = (nonce + challenge * secret) % _L
    return encoded_r + scalar_s.to_bytes(32, "little")


class _Reader:
    def __init__(self, blob: bytes, offset: int = 0) -> None:
        self.blob = blob
        self.offset = offset

    def u32(self) -> int | None:
        if self.offset + 4 > len(self.blob):
            return None
        value = int.from_bytes(self.blob[self.offset:self.offset + 4], "big")
        self.offset += 4
        return value

    def blob_string(self) -> bytes | None:
        length = self.u32()
        if length is None or length < 0 or self.offset + length > len(self.blob):
            return None
        value = self.blob[self.offset:self.offset + length]
        self.offset += length
        return value


def parse_openssh_private_key(pem: str) -> tuple[bytes, bytes] | None:
    """(public wire blob, seed) from an unencrypted ssh-ed25519 PEM, else None.

    Every read is bounds-checked; anything outside the exact Ollama shape
    (single key, cipher none, matching public halves) is unusable, not fatal.
    """
    body = "".join(
        line.strip() for line in pem.splitlines()
        if line.strip() and not line.strip().startswith("-----")
    )
    try:
        blob = base64.b64decode(body, validate=True)
    except (ValueError, TypeError):
        return None
    if not blob.startswith(_MAGIC):
        return None
    reader = _Reader(blob, len(_MAGIC))
    if reader.blob_string() != b"none" or reader.blob_string() != b"none":
        return None
    if reader.blob_string() is None or reader.u32() != 1:
        return None
    public_blob = reader.blob_string()
    private_section = reader.blob_string()
    if public_blob is None or private_section is None:
        return None
    inner = _Reader(private_section)
    if inner.u32() is None or inner.u32() is None:
        return None
    if inner.blob_string() != _KEY_TYPE or inner.blob_string() is None:
        return None
    private_key = inner.blob_string()
    if private_key is None or len(private_key) != 64:
        return None
    seed, public_half = private_key[:32], private_key[32:]
    if public_from_seed(seed) != public_half:
        return None
    outer = _Reader(public_blob)
    if outer.blob_string() != _KEY_TYPE:
        return None
    if outer.blob_string() != public_half:
        return None
    return public_blob, seed


def authorization(public_blob: bytes, seed: bytes, method: str, uri: str) -> str:
    """The ``<base64 public key>:<base64 signature>`` header value."""
    signature = sign(seed, f"{method},{uri}".encode("utf-8"))
    public = base64.b64encode(public_blob).decode("ascii")
    return f"{public}:{base64.b64encode(signature).decode('ascii')}"
