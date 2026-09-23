"""Optional proxy routing for provider HTTP requests.

Same contract as upstream docs/proxy.md, minus SOCKS5: config file holds
``{"proxy": {"enabled": true, "url": "http://127.0.0.1:8080"}}``. Read once
per Http instance (restart after editing). Missing, disabled, invalid, or
unreadable config leaves proxying off. Loopback always bypasses the proxy.

SOCKS5 is omitted: no stdlib support (recorded in docs/parity.md). A socks5
URL parses but is inert, with a warning at load.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from . import log

DEFAULT_PORTS = {"http": 80, "https": 443, "socks5": 1080}
LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@dataclass(frozen=True)
class ProxyConfig:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None

    @property
    def supported(self) -> bool:
        return self.scheme in ("http", "https")

    def url(self) -> str:
        auth = ""
        if self.username:
            auth = self.username
            if self.password:
                auth += f":{self.password}"
            auth += "@"
        return f"{self.scheme}://{auth}{self.host}:{self.port}"


def load(path: Path) -> ProxyConfig | None:
    """Parse the proxy config file. None means proxying stays off."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    proxy = raw.get("proxy") if isinstance(raw, dict) else None
    if not isinstance(proxy, dict) or proxy.get("enabled") is not True:
        return None
    url = proxy.get("url")
    if not isinstance(url, str) or not url.strip():
        return None
    try:
        parts = urlparse(url.strip())
    except ValueError:
        return None
    scheme = (parts.scheme or "").lower()
    host = (parts.hostname or "").strip()
    if scheme not in DEFAULT_PORTS or not host:
        return None
    try:
        port = parts.port or DEFAULT_PORTS[scheme]
    except ValueError:
        return None
    if not 1 <= port <= 65535:
        return None
    _warn_loose_mode(path)
    config = ProxyConfig(
        scheme=scheme, host=host, port=port,
        username=parts.username, password=parts.password,
    )
    if not config.supported:
        log.get_logger("http").warning(
            "proxy scheme %s is not supported; proxying stays off", scheme)
        return None
    return config


def _warn_loose_mode(path: Path) -> None:
    try:
        mode = path.stat().st_mode & 0o777
    except OSError:
        return
    if mode & 0o077:
        # The URL may embed credentials; never echo the path contents.
        log.get_logger("http").warning(
            "proxy config is readable by others; use mode 0600")


def is_loopback(url: str) -> bool:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return False
    return host in LOOPBACK_HOSTS
