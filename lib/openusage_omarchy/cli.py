"""One-shot CLI. Prints the /v1/limits JSON and exits. No daemon needed.

Shares the provider engine and cache with the daemon. A normal read reuses
snapshots fetched this session and younger than 5 minutes; --force refreshes
through the engine and writes the same cache.

Exit codes: 0 success, 2 bad args or unknown provider, 4 a refresh failed and
left a matched card with no data to show.
"""

from __future__ import annotations

import datetime as dt
import json
import sys

from . import atomic, catalog, layout as _layout, log, model, paths, proxy as _proxy
from . import http as _http
from . import settings as _settings
from .api import limits
from .daemon import main as _daemon
from .engine import detect, refresh as _refresh, session
from .providers import Env, SystemClock, registry

EXIT_OK = 0
EXIT_ARGS = 2
EXIT_FAILED = 4

USAGE = "usage: openusage-omarchy [id] [--force]"


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _parse(argv: list[str]) -> tuple[str | None, bool]:
    wanted: str | None = None
    force = False
    for arg in argv:
        if arg == "--force":
            force = True
        elif arg in ("-h", "--help"):
            print(USAGE)
            raise SystemExit(EXIT_OK)
        elif arg.startswith("-"):
            raise ValueError(f"unknown flag: {arg}")
        elif wanted is None:
            wanted = arg
        else:
            raise ValueError(f"too many arguments: {arg}")
    return wanted, force


def _live_env() -> Env:
    dirs = paths.Paths.from_env()
    return Env(http=_http.Http(_proxy.load(dirs.proxy_config)),
               clock=SystemClock(), paths=dirs)


def run(argv: list[str], env: Env | None = None) -> int:
    if argv == ["serve"]:
        return _daemon.main()
    try:
        wanted, force = _parse(argv)
    except ValueError as exc:
        print(f"openusage-omarchy: {exc}\n{USAGE}", file=sys.stderr)
        return EXIT_ARGS
    live = env or _live_env()
    if live.settings is None:
        live = Env(http=live.http, clock=live.clock, paths=live.paths,
                   settings=_settings.Settings(live.paths.shell_json))
    collectors = registry()
    table = catalog.cached()
    if wanted is not None:
        cards = [card for collector in collectors for card in collector.cards(live)]
        matched = limits.match_cards(wanted, cards)
        if not matched:
            print(f"openusage-omarchy: unknown provider: {wanted}", file=sys.stderr)
            return EXIT_ARGS
        families: set[str] | None = {card.family for card in matched}
    else:
        layout = atomic.read_json(live.paths.layout_file)
        found = detect.detect_all(
            collectors, live, _layout.detection_families(layout, table))
        possible = _layout.enabled_families(layout, found, table)
        cards = [card for collector in collectors if collector.family in possible
                 for card in collector.cards(live)]
        enabled_ids = _layout.enabled_card_ids(layout, found, table, cards)
        families = {card.family for card in cards if card.card_id in enabled_ids}
    session_id = session.get_session_id(live.paths.session_file)
    batch = _refresh.refresh(
        collectors, live, session_id, force=force, families=families,
        enabled_ids=enabled_ids if wanted is None else {card.card_id for card in matched})
    snapshots: dict[str, model.Snapshot] = {}
    errors: dict[str, model.ErrorInfo] = {}
    for item in batch.results:
        if item.snapshot is not None:
            snapshots[item.card.card_id] = item.snapshot
        if item.error is not None:
            errors[item.card.card_id] = item.error
    envelope = limits.project(snapshots, errors, table, live.clock.now())
    print(json.dumps(envelope, separators=(",", ":"), sort_keys=True))
    missing = any(item.snapshot is None for item in batch.results)
    return EXIT_FAILED if missing else EXIT_OK


def main(argv: list[str] | None = None) -> int:
    dirs = paths.Paths.from_env()
    log.setup("info", dirs.log_file)
    try:
        return run(list(sys.argv[1:] if argv is None else argv))
    except SystemExit as exc:
        code = exc.code
        return code if isinstance(code, int) else EXIT_OK
    except BrokenPipeError:
        return EXIT_OK
