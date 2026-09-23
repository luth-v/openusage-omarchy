"""Loopback-only read-only HTTP API. Pure router plus a thin transport.

Binds the literal 127.0.0.1:6736. A taken port disables the feature for the
session. At most 16 concurrent connections; above that, 503 server_busy.
Only GET/OPTIONS; anything else is 405. CORS is permissive, as upstream.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .. import API_HOST, API_PORT, catalog, layout as _layout, log, model
from . import limits, usage

MAX_CONNECTIONS = 16


@dataclass
class ApiState:
    enabled_ordered: list[str] = field(default_factory=list)
    known: set[str] = field(default_factory=set)
    snapshots: dict[str, model.Snapshot] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    generated_at: dt.datetime = field(
        default_factory=lambda: dt.datetime.now(dt.timezone.utc))

    def matching(self, token: str) -> list[str]:
        """Exact card id, or a family id naming every card of that family."""
        return sorted(cid for cid in self.known
                      if cid == token or model.family_of(cid) == token)


def build_state(snapshots: dict[str, model.Snapshot], errors: dict[str, str],
                layout: dict | None, table: catalog.Catalog,
                now: dt.datetime,
                detected: dict[str, bool] | None = None) -> ApiState:
    """Serving snapshot: collection routes follow the layout order and
    enablement; single-id routes work for disabled cards too."""
    ids = {item.provider_id for item in table.providers} | set(snapshots)
    if isinstance(layout, dict):
        ids.update(cid for cid in layout.get("cards", {}) if isinstance(cid, str))
    order = layout.get("order") if isinstance(layout, dict) else None
    ordered = [cid for cid in order if cid in ids] if isinstance(order, list) else []
    ordered.extend(cid for cid in sorted(ids) if cid not in ordered)
    cards = [snapshots[cid].card if cid in snapshots else model.CardRef(
        cid, model.family_of(cid), cid) for cid in ordered]
    enabled = _layout.enabled_card_ids(layout, detected or {}, table, cards)
    return ApiState(enabled_ordered=[cid for cid in ordered if cid in enabled], known=ids,
                    snapshots=dict(snapshots), errors=dict(errors),
                    generated_at=now)


def _error(status: int, code: str) -> tuple[int, bytes]:
    return status, json.dumps({"error": code}).encode()


def route(method: str, raw_path: str, state: ApiState,
          table: catalog.Catalog) -> tuple[int, bytes | None]:
    if method == "OPTIONS":
        return 204, None
    segments = raw_path.split("?", 1)[0].split("/")
    parts = [item for item in segments if item]
    if len(parts) == 2 and parts[0] == "v1" and parts[1] == "limits":
        if method != "GET":
            return _error(405, "method_not_allowed")
        return 200, _limits_bytes(
            [cid for cid in state.enabled_ordered if cid in state.snapshots],
            state, table)
    if len(parts) == 3 and parts[0] == "v1" and parts[1] == "limits":
        if method != "GET":
            return _error(405, "method_not_allowed")
        ids = state.matching(parts[2])
        if not ids:
            return _error(404, "provider_not_found")
        return 200, _limits_bytes(
            [cid for cid in ids if cid in state.snapshots], state, table)
    if len(parts) == 2 and parts[0] == "v1" and parts[1] == "usage":
        if method != "GET":
            return _error(405, "method_not_allowed")
        found = {cid: state.snapshots[cid] for cid in state.enabled_ordered
                 if cid in state.snapshots}
        return 200, _usage_bytes(found, state, table)
    if len(parts) == 3 and parts[0] == "v1" and parts[1] == "usage":
        if method != "GET":
            return _error(405, "method_not_allowed")
        ids = state.matching(parts[2])
        if not ids:
            return _error(404, "provider_not_found")
        found = {cid: state.snapshots[cid] for cid in ids
                 if cid in state.snapshots}
        return 200, _usage_bytes(found, state, table)
    return _error(404, "not_found")


def _limits_bytes(ids: list[str], state: ApiState,
                  table: catalog.Catalog) -> bytes:
    from ..model import ErrorInfo  # local: projection takes typed errors

    snapshots = {cid: state.snapshots[cid] for cid in ids}
    errors = {cid: ErrorInfo(category="", message=state.errors[cid])
              for cid in ids if cid in state.errors}
    envelope = limits.project(snapshots, errors, table, state.generated_at)
    return json.dumps(envelope, separators=(",", ":"),
                      sort_keys=True).encode()


def _usage_bytes(found: dict[str, model.Snapshot], state: ApiState,
                 table: catalog.Catalog) -> bytes:
    del state
    return json.dumps(usage.project(found, table), separators=(",", ":"),
                      sort_keys=True).encode()


class _Handler(BaseHTTPRequestHandler):
    server_version = "OpenUsageOmarchy/1"

    def _serve(self, method: str) -> None:
        gate: threading.Semaphore = self.server.gate  # type: ignore[attr-defined]
        if not gate.acquire(blocking=False):
            self._send(*_error(503, "server_busy"))
            return
        try:
            table = self.server.table  # type: ignore[attr-defined]
            state = self.server.state_fn()  # type: ignore[attr-defined]
            log.get_logger("localapi").debug("%s %s", method, self.path)
            self._send(*route(method, self.path, state, table))
        finally:
            gate.release()

    def _send(self, status: int, body: bytes | None) -> None:
        self.send_response(status)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Connection", "close")
        if body is None:
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        self._serve("GET")

    def do_OPTIONS(self) -> None:
        self._serve("OPTIONS")

    def do_POST(self) -> None:
        self._send(*_error(405, "method_not_allowed"))

    def do_PUT(self) -> None:
        self._send(*_error(405, "method_not_allowed"))

    def do_DELETE(self) -> None:
        self._send(*_error(405, "method_not_allowed"))

    def do_PATCH(self) -> None:
        self._send(*_error(405, "method_not_allowed"))

    def log_message(self, fmt: str, *args) -> None:
        log.get_logger("localapi").debug(fmt % args)


class Server:
    """Threaded loopback server. start() returns False when the port is
    taken, disabling the feature for the session."""

    def __init__(self, state_fn, table: catalog.Catalog,
                 port: int = API_PORT) -> None:
        self._state_fn = state_fn
        self._table = table
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> bool:
        try:
            server = ThreadingHTTPServer((API_HOST, self._port), _Handler)
        except OSError as exc:
            log.get_logger("localapi").info("disabled: %s", exc)
            return False
        server.daemon_threads = True
        server.gate = threading.Semaphore(MAX_CONNECTIONS)  # type: ignore[attr-defined]
        server.state_fn = self._state_fn  # type: ignore[attr-defined]
        server.table = self._table  # type: ignore[attr-defined]
        self._server = server
        self._thread = threading.Thread(target=server.serve_forever,
                                        name="openusage-api", daemon=True)
        self._thread.start()
        log.get_logger("localapi").info(
            "listening on %s:%d", *server.server_address[:2])
        return True

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)

    @property
    def address(self) -> tuple[str, int] | None:
        if self._server is None:
            return None
        host, port = self._server.server_address[:2]
        return str(host), int(port)
