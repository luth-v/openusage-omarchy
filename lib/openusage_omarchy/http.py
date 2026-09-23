"""Outbound HTTP. The only network egress in the package.

Stdlib urllib. Every request carries a socket timeout of at most 30 s.
Client errors (4xx) return a Response so collectors can map 401/403/429;
server errors (5xx) and transport failures raise HttpError.
Loopback hosts always bypass the proxy (the Antigravity language server).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol
from urllib import request as _request
from urllib.error import HTTPError, URLError

from . import HTTP_TIMEOUT_S, log, proxy as _proxy, redact


@dataclass(frozen=True)
class Response:
    status: int
    body: bytes
    headers: dict[str, str] | None = None

    def header(self, name: str) -> str | None:
        if not self.headers:
            return None
        want = name.lower()
        for key, value in self.headers.items():
            if key.lower() == want:
                return value
        return None


class HttpError(Exception):
    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(redact.redact_text(message))
        self.status = status


class HttpClient(Protocol):
    def get(
        self, url: str, headers: dict[str, str] | None = None, timeout: float = ...  # noqa: E501
    ) -> Response: ...
    def post(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str] | None = None,
        timeout: float = ...,
    ) -> Response: ...


class Http:
    def __init__(self, proxy: "_proxy.ProxyConfig | None" = None) -> None:
        self._proxy = proxy
        self._log = log.get_logger("http")
        self._remote_opener: "_request.OpenerDirector | None" = None
        if proxy is not None and proxy.supported:
            self._remote_opener = _proxy_opener(proxy)

    def get(
        self, url: str, headers: dict[str, str] | None = None, timeout: float = HTTP_TIMEOUT_S
    ) -> Response:
        return self._send("GET", url, None, headers, timeout)

    def post(
        self,
        url: str,
        body: bytes,
        headers: dict[str, str] | None = None,
        timeout: float = HTTP_TIMEOUT_S,
    ) -> Response:
        return self._send("POST", url, body, headers, timeout)

    def _send(
        self,
        method: str,
        url: str,
        body: bytes | None,
        headers: dict[str, str] | None,
        timeout: float,
    ) -> Response:
        deadline = min(max(float(timeout), 1.0), HTTP_TIMEOUT_S)
        req = _request.Request(url, data=body, method=method, headers=headers or {})
        if _proxy.is_loopback(url):
            opener = _loopback_opener().open
        elif self._remote_opener is not None:
            opener = self._remote_opener.open
        else:
            opener = _request.urlopen
        try:
            with opener(req, timeout=deadline) as reply:  # noqa: S310
                raw_headers: dict[str, str] = {}
                try:
                    for key, value in reply.getheaders():
                        raw_headers[str(key)] = str(value)
                except (AttributeError, TypeError, ValueError):
                    raw_headers = {}
                return Response(status=reply.status, body=reply.read(), headers=raw_headers)
        except HTTPError as exc:
            if exc.code is not None and 400 <= exc.code < 500:
                try:
                    error_body = exc.read()
                except (OSError, ValueError):
                    error_body = b""
                try:
                    error_headers = {str(k): str(v) for k, v in exc.headers.items()}
                except (AttributeError, TypeError, ValueError):
                    error_headers = {}
                return Response(
                    status=exc.code, body=error_body, headers=error_headers)
            raise HttpError(f"{method} {url} returned status {exc.code}", exc.code) from exc
        except URLError as exc:
            raise HttpError(f"{method} {url} failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise HttpError(f"{method} {url} timed out") from exc
        except OSError as exc:
            raise HttpError(f"{method} {url} failed: {exc}") from exc


def parse_json_object(body: bytes) -> dict | None:
    import json

    try:
        payload = json.loads(body.decode("utf-8", errors="replace"))
    except (ValueError, UnicodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_loopback(url: str) -> bool:
    return _proxy.is_loopback(url)


def _proxy_opener(config: "_proxy.ProxyConfig") -> "_request.OpenerDirector":
    target = f"{config.scheme}://{config.host}:{config.port}"
    handlers: list = [_request.ProxyHandler({"http": target, "https": target})]
    if config.username:
        manager = _request.HTTPPasswordMgrWithDefaultRealm()
        manager.add_password(None, target, config.username, config.password or "")
        handlers.append(_request.ProxyBasicAuthHandler(manager))
    return _request.build_opener(*handlers)


def _loopback_opener() -> "_request.OpenerDirector":
    """Proxy-bypassing opener that trusts loopback TLS (self-signed LS certs).

    Only the Antigravity language server uses loopback HTTPS. Remote hosts keep
    full certificate validation. Pass 8 adds proxy support for remote hosts;
    loopback never goes through a proxy.
    """
    import ssl

    context = ssl._create_unverified_context()
    return _request.build_opener(
        _request.ProxyHandler({}),
        _request.HTTPSHandler(context=context),
    )
