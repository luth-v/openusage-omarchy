"""Long-lived daemon. Owns refresh, cache, and state.json.

Runs as a child Process of Service.qml. Exits on stdin EOF. A second instance
exits 0 while the lock holder lives. All durable state is on disk, so a shell
hot-reload restarts cheaply without re-hitting provider APIs.
"""

from __future__ import annotations

import datetime as dt
import fcntl
import os
import queue
import sys
import threading
from typing import TextIO

from .. import REFRESH_INTERVAL_S, atomic, catalog, layout as _layout, log, model, paths, redact
from .. import http as _http
from .. import notify as _notify
from .. import proxy as _proxy
from .. import secrets as _secrets
from .. import settings as _settings
from .. import shortcut as _shortcut
from .. import update as _update
from ..api import server as _server
from ..engine import detect, refresh as _refresh, session
from ..providers import Env, SystemClock, registry
from ..providers import codex as _codex
from ..providers.codex import reset_claim as _claim
from . import commands, publish


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


# Claim outcome (providers/codex/reset_claim.py) to state.json lastClaim
# status plus the exact upstream banner line (RateLimitResetsDetail.swift).
CLAIM_RESULTS = {
    "success": ("ok", "Reset claimed. Enjoy!"),
    "nothingToReset": ("not_needed", "Your usage doesn't need a reset yet"),
    "noCredit": ("unavailable", "That reset is no longer available"),
    "failed": ("error", "Couldn't reset usage. Please try again."),
}

APPLIED_FALLBACK = "codex-fallback"


def read_applied_fallback(dirs: paths.Paths) -> str | None:
    """The fallback choice the cache was built with. None when unknown."""
    try:
        text = (dirs.cache_dir / APPLIED_FALLBACK).read_text(encoding="utf-8")
    except OSError:
        return None
    return text.strip()


def write_applied_fallback(dirs: paths.Paths, value: str) -> None:
    try:
        target = dirs.cache_dir / APPLIED_FALLBACK
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value.strip() + "\n", encoding="utf-8")
    except OSError as exc:
        log.get_logger("refresh").warning("fallback marker write failed: %s", exc)


class Daemon:
    def __init__(self, dirs: paths.Paths) -> None:
        self.dirs = dirs
        self.settings = _settings.Settings(dirs.shell_json)
        self.env = Env(http=_http.Http(_proxy.load(dirs.proxy_config)),
                       clock=SystemClock(), paths=dirs,
                       settings=self.settings)
        self.collectors = registry()
        self.table = catalog.cached()
        try:
            self.version = catalog.manifest_version()
        except (OSError, ValueError):
            self.version = ""
        self.installable = _update.is_installable()
        self.update_state = _update.UpdateState(installable=self.installable)
        self.notify_state: dict[str, _notify.NotificationState] = {}
        self.api_listening = False
        self._api: _server.Server | None = None
        self.session_id = ""
        self.detected: dict[str, bool] = {}
        self.key_sources: dict[str, str] = {}
        self.codex_options: list[dict] = []
        self.in_flight: list[str] = []
        self.next_at: dt.datetime | None = None
        self.last_batch: _refresh.Batch | None = None
        self._spend_threads: list[threading.Thread] = []
        self._last_claims: dict[str, dict] = {}
        self._commands: "queue.Queue[commands.Command | None]" = queue.Queue()
        self._state_lock = threading.Lock()
        self._log = log.get_logger("refresh")

    def run(self, stdin: TextIO) -> int:
        _notify.startup()
        self.session_id = session.get_session_id(self.dirs.session_file)
        layout = atomic.read_json(self.dirs.layout_file)
        self.detected = detect.detect_all(
            self.collectors, self.env,
            _layout.detection_families(layout, self.table))
        self.key_sources = self._read_key_sources()
        self.update_state = _update.load_state(self.dirs, self.installable)
        self.notify_state = _notify.load_state(self.dirs)
        self._reconcile_settings()
        self._api = _server.Server(self._api_state, self.table)
        self.api_listening = self._api.start()
        worker = threading.Thread(target=self._worker, daemon=True)
        worker.start()
        for line in stdin:
            try:
                command = commands.parse_line(line)
            except commands.InvalidCommand as exc:
                self._log.warning("bad command: %s", redact.redact_text(str(exc)))
                continue
            if command is None:
                continue
            self._log.info("command: %s", redact.redact_command(commands.describe(command)))
            self._commands.put(command)
        self._commands.put(None)
        worker.join(timeout=5)
        _notify.shutdown()
        if self._api is not None:
            self._api.stop()
        return 0

    def _worker(self) -> None:
        self._run_batch(force=self._fallback_rescan_due(), families=None)
        self._maybe_update_check(force=False)
        handlers = {
            commands.Refresh: self._handle_refresh,
            commands.ClaimReset: self._handle_claim,
            commands.SetKey: self._change_key,
            commands.DeleteKey: self._change_key,
            commands.CheckUpdate: self._handle_check_update,
            commands.SnoozeUpdate: self._handle_snooze,
            commands.InstallUpdate: self._handle_install,
        }
        while True:
            remaining = ((self.next_at - _utcnow()).total_seconds()
                         if self.next_at else REFRESH_INTERVAL_S)
            try:
                command = self._commands.get(timeout=min(5.0, max(0.0, remaining)))
            except queue.Empty:
                if self.next_at is None or _utcnow() >= self.next_at:
                    self._run_batch(force=self._fallback_rescan_due(), families=None)
                    self._maybe_update_check(force=False)
                self._reconcile_if_changed()
                continue
            if command is None:  # stdin EOF: stop the worker
                return
            handlers[type(command)](command)
            self._reconcile_if_changed()

    def _handle_refresh(self, command: commands.Refresh) -> None:
        families = ({model.family_of(command.card_id)}
                    if command.card_id else None)
        self._run_batch(force=command.force, families=families,
                        requested_card_id=command.card_id)

    def _handle_claim(self, command: commands.ClaimReset) -> None:
        self._claim_reset(command.card_id, command.expiry, command.request_id)

    def _handle_check_update(self, _command: commands.CheckUpdate) -> None:
        self._maybe_update_check(force=True)

    def _handle_snooze(self, command: commands.SnoozeUpdate) -> None:
        with self._state_lock:
            _update.snooze(self.update_state, command.version)
            _update.save_state(self.dirs, self.update_state)
            self._write_state()

    def _handle_install(self, _command: commands.InstallUpdate) -> None:
        if self.installable:
            _update.install()
        else:
            self._log.warning("installUpdate ignored: not a git install")

    def _read_key_sources(self) -> dict[str, str]:
        found = {item.provider_id: "none" for item in self.table.providers}
        for provider in _secrets.PROVIDERS:
            try:
                found[provider] = _secrets.key_source(provider, self.dirs)
            except (OSError, ValueError) as exc:
                self._log.warning("key presence check failed: %s", exc)
        return found

    def _change_key(self, command: commands.SetKey | commands.DeleteKey) -> None:
        provider = command.provider
        if provider not in _secrets.PROVIDERS:
            return
        try:
            if isinstance(command, commands.SetKey):
                _secrets.set_key(provider, command.value, self.dirs)
            else:
                _secrets.delete_key(provider, self.dirs)
        except (_secrets.SecretsError, OSError, ValueError) as exc:
            self._log.warning("key change failed for %s: %s", provider, exc)
            return
        with self._state_lock:
            try:
                self.key_sources[provider] = _secrets.key_source(
                    provider, self.dirs)
            except (OSError, ValueError):
                self.key_sources[provider] = "none"
            self.detected[provider] = self.key_sources[provider] != "none"
        self._run_batch(force=True, families={provider})

    def _record_claim(self, card_id: str, outcome: str) -> None:
        status, message = CLAIM_RESULTS.get(outcome, CLAIM_RESULTS["failed"])
        self._last_claims[card_id] = {
            "status": status,
            "message": message,
            "at": _utcnow().isoformat(),
        }

    def _claim_reset(
        self, card_id: str, expiry: str | None, request_id: str | None
    ) -> None:
        target = next((card for card in _codex.cards(self.env)
                       if card.card_id == card_id), None)
        if target is None:
            self._log.warning("claimReset: unknown card %s", card_id)
            return
        outcome = _claim.claim_for_card(target, self.env, expiry, request_id)
        self._log.info("claimReset %s: %s", card_id, outcome)
        self._record_claim(card_id, outcome)
        self._run_batch(force=True, families={"codex"})

    def _run_batch(self, force: bool, families: set[str] | None,
                   requested_card_id: str | None = None) -> None:
        layout = atomic.read_json(self.dirs.layout_file)
        candidates = _layout.enabled_families(layout, self.detected, self.table)
        if requested_card_id and self.table.provider(model.family_of(requested_card_id)):
            candidates.add(model.family_of(requested_card_id))
        available = []
        for collector in self.collectors:
            if collector.family not in candidates or (
                    families is not None and collector.family not in families):
                continue
            try:
                available.extend(collector.cards(self.env))
            except Exception as exc:
                self._log.warning("%s cards failed: %s", collector.family,
                                  type(exc).__name__)
        enabled = _layout.enabled_card_ids(layout, self.detected, self.table,
                                           available)
        if requested_card_id in {card.card_id for card in available}:
            enabled.add(requested_card_id)
        with self._state_lock:
            self.in_flight = sorted(cid for cid in enabled
                                    if families is None or model.family_of(cid) in families)
            self._write_state()
        try:
            batch = _refresh.refresh(
                self.collectors, self.env, self.session_id, force=force,
                families=families, enabled_ids=enabled
            )
        except Exception as exc:  # the batch must always settle below
            self._log.warning("refresh batch failed: %s", type(exc).__name__)
            batch = None
        try:
            with self._state_lock:
                # A family-scoped batch merges into the previous one; other
                # providers keep their last-good rows instead of blanking.
                if batch is not None:
                    if families is not None and self.last_batch is not None:
                        batch = _refresh.merge_batches(self.last_batch, batch)
                    self.last_batch = batch
                elif families is None and self.last_batch is None:
                    now = _utcnow()
                    self.last_batch = _refresh.Batch(
                        generation=0, results=[], started_at=now,
                        ended_at=now)
                self.in_flight = []
                if families is None:
                    self.next_at = _utcnow() + dt.timedelta(
                        seconds=REFRESH_INTERVAL_S)
                try:
                    self.codex_options = self._load_codex_options()
                except Exception as exc:
                    self._log.warning("codex options failed: %s",
                                      type(exc).__name__)
                if batch is not None:
                    try:
                        self._notify_pass(batch)
                    except Exception as exc:
                        self._log.warning("notify pass failed: %s",
                                          type(exc).__name__)
        finally:
            # Quota publishes first, on every path including timeouts and
            # failures: inFlight clears and the schedule advances here.
            with self._state_lock:
                try:
                    self._write_state()
                except Exception as exc:
                    self._log.warning("state publish failed: %s",
                                      type(exc).__name__)
                paths.harden_runtime_files(self.dirs)
        if batch is not None:
            self._spawn_spend_attach(batch)

    def _spawn_spend_attach(self, batch: _refresh.Batch) -> threading.Thread:
        """Enrich a published batch with spend tiles in the background.

        Slow scans attach when ready through a second publish. A batch
        superseded by a newer one is dropped: its successor re-attaches.
        Returns the thread so tests can join it.
        """
        def _work() -> None:
            try:
                enriched = _refresh.attach_spend(
                    batch, self.collectors, self.env, self.session_id)
            except Exception as exc:
                self._log.warning("spend attach failed: %s", type(exc).__name__)
                return
            with self._state_lock:
                current = self.last_batch
                if current is None or current.generation != enriched.generation:
                    return
                self.last_batch = enriched
                try:
                    self._write_state()
                except Exception as exc:
                    self._log.warning("state publish failed: %s",
                                      type(exc).__name__)

        self._spend_threads = [thread for thread in self._spend_threads
                               if thread.is_alive()]
        worker = threading.Thread(target=_work, name="openusage-spend",
                                  daemon=True)
        self._spend_threads.append(worker)
        worker.start()
        return worker

    def _load_codex_options(self) -> list[dict]:
        try:
            from ..spend import context as _spend_ctx
            return _spend_ctx.codex_options(self.env)
        except Exception:
            return []

    def _fallback_rescan_due(self) -> bool:
        """True when the fallback choice changed since the last batch.

        A shell.json write reloads the shell, so the QML picker cannot force
        a rescan itself; the marker in the cache dir survives the restart.
        First boot adopts the choice without a rescan.
        """
        from ..spend import context as _spend_ctx
        current = _spend_ctx.fallback_setting(self.env)
        applied = read_applied_fallback(self.dirs)
        if applied is None:
            write_applied_fallback(self.dirs, current)
            return False
        if applied == current:
            return False
        write_applied_fallback(self.dirs, current)
        self._log.info("codex fallback changed; forcing a rescan")
        return True

    def _write_state(self) -> None:
        try:
            from ..spend import context as _spend_ctx
            pricing = _spend_ctx.pricing_info(self.env)
        except (OSError, ValueError):
            pricing = ("bundled", None)
        state = publish.build(
            self.table,
            self.last_batch,
            self.detected,
            self.session_id,
            self.version,
            _utcnow(),
            list(self.in_flight),
            self.next_at,
            secrets=dict(self.key_sources),
            pricing=pricing,
            last_claims=dict(self._last_claims),
            codex_options=list(self.codex_options),
            update=self.update_state.to_dict(),
            api_listening=self.api_listening,
        )
        try:
            publish.publish(self.dirs, state)
        except OSError as exc:
            self._log.warning("state publish failed: %s", exc)

    def _maybe_update_check(self, force: bool) -> None:
        with self._state_lock:
            auto = self.settings.get("updateAuto", True) is not False
            beta = bool(self.settings.get("betaUpdates", False))
            _update.run_check(self.env.http, self.update_state, self.version,
                              beta, _utcnow(), force=force)
            _update.save_state(self.dirs, self.update_state)
            self._write_state()

    def _reconcile_settings(self) -> None:
        """Re-derive level, bind file, and hook from shell.json."""
        log.set_level(str(self.settings.get("logLevel", "Info")))
        _shortcut.reconcile(self.dirs, str(self.settings.get("shortcut", "")))
        _update.reconcile_hook(
            self.dirs,
            bool(self.settings.get("updateWithOmarchy", False)),
            self.installable)

    def _reconcile_if_changed(self) -> None:
        if self.settings.changed():
            self._reconcile_settings()

    def _notify_pass(self, batch: _refresh.Batch) -> None:
        toggles = {name: bool(self.settings.get(key, False))
                   for name, key in _notify.SETTING_KEYS.items()}
        if not any(toggles.values()):
            return
        layout = atomic.read_json(self.dirs.layout_file)
        labels = {(item.provider_id, metric.metric_id): metric.metric_label
                  for item in self.table.providers for metric in item.metrics}
        enabled = _layout.enabled_card_ids(
            layout, self.detected, self.table, [item.card for item in batch.results])
        metrics = _notify.collect([item for item in batch.results
                                   if item.card.card_id in enabled],
                                  layout if isinstance(layout, dict) else None,
                                  labels, _utcnow())
        fired, keep = _notify.evaluate(metrics, toggles, self.notify_state)
        if fired:
            delivered = _notify.post(fired, self._provider_name)
            _notify.commit(fired, keep, self.notify_state, delivered)
        self.notify_state = keep
        _notify.save_state(self.dirs, keep)

    def _provider_name(self, provider_id: str) -> str:
        provider = self.table.provider(provider_id)
        return provider.display_name if provider else provider_id

    def _api_state(self) -> _server.ApiState:
        snapshots: dict = {}
        errors: dict = {}
        if self.last_batch is not None:
            for item in self.last_batch.results:
                if item.snapshot is not None:
                    snapshots[item.card.card_id] = item.snapshot
                if item.error is not None:
                    errors[item.card.card_id] = item.error.message
        layout = atomic.read_json(self.dirs.layout_file)
        return _server.build_state(
            snapshots, errors,
            layout if isinstance(layout, dict) else None,
            self.table, _utcnow(), self.detected)


def serve(dirs: paths.Paths, stdin: TextIO | None = None) -> int:
    os.umask(0o077)
    paths.harden(dirs)
    paths.ensure_runtime_dir(dirs.runtime_dir)
    fd = os.open(dirs.daemon_lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        os.close(fd)
        print("openusage-omarchy: daemon already running", file=sys.stderr)
        return 0
    try:
        return Daemon(dirs).run(stdin or sys.stdin)
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def main() -> int:
    dirs = paths.Paths.from_env()
    log.setup("info", dirs.log_file)
    return serve(dirs)
