"""Quota notifications. Pure evaluator plus a notify-send sink.

Ports upstream PaceNotificationLogic.swift and QuotaNotificationEvaluator.swift:
three milestones (Almost Out, Cutting It Close, Will Run Out), each deduped
per metric per reset window. A quota already bad at launch primes the baseline
without alerting; recovery or a new window re-arms. Dedup state persists on
disk so a shell hot-reload does not re-fire. All three toggles default off.
"""

from __future__ import annotations

import datetime as dt
import shutil
import subprocess
import threading
from dataclasses import dataclass, field

from . import atomic, log, model, paths

UNDER_TEN = "underTenPercent"
HEALTHY_TO_CLOSE = "healthyToClose"
CLOSE_TO_RUNNING_OUT = "closeToRunningOut"

TITLES = {
    UNDER_TEN: "Almost Out",
    HEALTHY_TO_CLOSE: "Cutting It Close",
    CLOSE_TO_RUNNING_OUT: "Will Run Out",
}

BODIES = {
    UNDER_TEN: "Under 10% usage remaining for this window.",
    HEALTHY_TO_CLOSE: "Projected to finish close to your limit.",
    CLOSE_TO_RUNNING_OUT: "Projected to finish before the limit resets.",
}

SETTING_KEYS = {
    UNDER_TEN: "notifyAlmostOut",
    HEALTHY_TO_CLOSE: "notifyCuttingClose",
    CLOSE_TO_RUNNING_OUT: "notifyWillRunOut",
}

JITTER_TOLERANCE_S = 1.0
SCHEMA = "openusage-omarchy.notify.v1"

_SEVERITY = {"untracked": -1, "healthy": 0, "close": 1, "runningOut": 2}


def bucket(state: str) -> str:
    if state in ("healthy",):
        return "healthy"
    if state == "closeToLimit":
        return "close"
    if state in ("runningOut", "spent"):
        return "runningOut"
    return "untracked"


@dataclass
class NotificationState:
    resets_at: str | None = None
    fired: set[str] = field(default_factory=set)
    previous_bucket: str = "untracked"
    was_under_ten: bool = False
    primed: bool = False

    def to_dict(self) -> dict:
        return {
            "resetsAt": self.resets_at,
            "fired": sorted(self.fired),
            "previousBucket": self.previous_bucket,
            "wasUnderTen": self.was_under_ten,
            "primed": self.primed,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "NotificationState":
        fired = {str(item) for item in raw.get("fired", []) if item in TITLES}
        prev = str(raw.get("previousBucket", "untracked"))
        return cls(
            resets_at=raw.get("resetsAt"),
            fired=fired,
            previous_bucket=prev if prev in _SEVERITY else "untracked",
            was_under_ten=bool(raw.get("wasUnderTen", False)),
            primed=bool(raw.get("primed", False)),
        )


def _parse_time(raw: str | None) -> dt.datetime | None:
    if not raw:
        return None
    try:
        moment = dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (ValueError, TypeError, AttributeError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    return moment


def reset_window_advanced(current: str | None, previous: str | None) -> bool:
    now = _parse_time(current)
    if now is None:
        return False
    old = _parse_time(previous)
    if old is None:
        return True
    return (now - old).total_seconds() > JITTER_TOLERANCE_S


def transitions(
    state: str,
    fraction: float,
    resets_at: str | None,
    previous: NotificationState,
    toggles: dict[str, bool],
) -> tuple[list[str], NotificationState]:
    """Milestones to fire now plus the state to persist. Pure."""
    current = NotificationState(
        resets_at=previous.resets_at,
        fired=set(previous.fired),
        previous_bucket=previous.previous_bucket,
        was_under_ten=previous.was_under_ten,
        primed=previous.primed,
    )
    if reset_window_advanced(resets_at, previous.resets_at):
        current.fired = set()
        current.was_under_ten = False
        current.previous_bucket = "untracked"
    current.resets_at = resets_at or previous.resets_at
    current_bucket = bucket(state)
    if state == "noData":
        return [], current
    if not current.primed:
        current.primed = True
        current.previous_bucket = current_bucket
        current.was_under_ten = fraction < 0.10
        current.fired = set()
        return [], current
    fire: list[str] = []

    def maybe(milestone: str) -> bool:
        if toggles.get(milestone) and milestone not in current.fired:
            fire.append(milestone)
            return True
        return False

    if current_bucket != "untracked":
        prev_sev = _SEVERITY[current.previous_bucket]
        now_sev = _SEVERITY[current_bucket]
        pace_fired = False
        if current_bucket == "close" and prev_sev < _SEVERITY["close"]:
            pace_fired = maybe(HEALTHY_TO_CLOSE) or pace_fired
        if now_sev >= _SEVERITY["runningOut"] and prev_sev < _SEVERITY["runningOut"]:
            pace_fired = maybe(CLOSE_TO_RUNNING_OUT) or pace_fired
        if now_sev < prev_sev:
            if now_sev <= _SEVERITY["healthy"]:
                current.fired.discard(HEALTHY_TO_CLOSE)
            if now_sev <= _SEVERITY["close"]:
                current.fired.discard(CLOSE_TO_RUNNING_OUT)
        if now_sev <= prev_sev or pace_fired:
            current.previous_bucket = current_bucket
    under_now = fraction < 0.10
    crossed = under_now and not current.was_under_ten
    under_fired = crossed and maybe(UNDER_TEN)
    if not under_now:
        current.fired.discard(UNDER_TEN)
    if not crossed or under_fired:
        current.was_under_ten = under_now
    return fire, current


def minimum_elapsed(period_s: float) -> float:
    if not period_s > 0:
        return 60.0
    return max(60.0, period_s * 0.01)


def _pace_verdict(used: float, limit: float, resets_at: str | None,
                 period_s: float, now: dt.datetime) -> str | None:
    """healthy|closeToLimit|runningOut, or None when pace is untrustworthy."""
    reset = _parse_time(resets_at)
    if reset is None or not (limit > 0 and period_s > 0 and used > 0):
        return None
    elapsed = (now - (reset - dt.timedelta(seconds=period_s))).total_seconds()
    if not elapsed >= minimum_elapsed(period_s) or not now < reset:
        return None
    projected = used / elapsed * period_s
    if used >= limit:
        return "runningOut"
    if projected <= limit * 0.9:
        return "healthy"
    if projected <= limit:
        return "closeToLimit"
    return "runningOut"


def _level(_used: float, _limit: float) -> str:
    # Severity bands carry no pace; bucket() maps level to untracked.
    return "level"


def session_signal(family: str, metric_id: str) -> str | None:
    if family == "claude" and metric_id == "session":
        return "missingResetDate"
    if family == "antigravity" and metric_id in ("geminiPro", "claude"):
        return "zeroUsage"
    if family == "opencode" and metric_id == "session":
        return "zeroUsage"
    return None


def meter_state(metric: model.Progress, family: str,
               now: dt.datetime) -> str:
    """Pace bucket input per metric. Ports Pace.js meterState verdicts."""
    used, limit = metric.used, metric.limit
    if not limit > 0:
        return "level"
    left = limit - used
    if metric.format_kind == "percent":
        rounded = round(left)
    elif metric.format_kind == "count":
        rounded = round(left * 10) / 10
    else:
        rounded = round(left * 100) / 100
    if rounded <= 0:
        return "spent"
    signal = session_signal(family, metric.metric_id)
    if signal == "missingResetDate" and used <= 0 and not metric.resets_at:
        return "level"
    if signal == "zeroUsage" and used <= 0 and metric.resets_at:
        reset = _parse_time(metric.resets_at)
        if reset is not None and now < reset:
            return "level"
    if metric.resets_at and metric.period_ms and metric.period_ms > 0:
        verdict = _pace_verdict(used, limit, metric.resets_at,
                                metric.period_ms / 1000, now)
        if verdict is not None:
            if verdict == "healthy":
                return "healthy"
            if used / limit < 0.05:
                return "level"
            if verdict == "closeToLimit":
                spare = round((1 - _projected_fraction(
                    used, limit, metric, now)) * 100)
                if spare < 1:
                    return "runningOut"
                return "closeToLimit"
            return "runningOut"
    return _level(used, limit)


def _projected_fraction(used: float, limit: float, metric: model.Progress,
                        now: dt.datetime) -> float:
    reset = _parse_time(metric.resets_at)
    period_s = (metric.period_ms or 0) / 1000
    if reset is None or not period_s > 0:
        return used / limit
    elapsed = (now - (reset - dt.timedelta(seconds=period_s))).total_seconds()
    if elapsed <= 0:
        return used / limit
    return (used / elapsed * period_s) / limit


def remaining_fraction(metric: model.Progress) -> float:
    if not metric.limit > 0:
        return 1.0
    return max(0.0, min(1.0, (metric.limit - metric.used) / metric.limit))


@dataclass(frozen=True)
class MetricInput:
    key: str
    provider: str
    title: str
    state: str
    fraction: float
    resets_at: str | None


def collect(results: list, layout: dict | None,
            labels: dict[tuple[str, str], str],
            now: dt.datetime) -> list[MetricInput]:
    """Enabled, bounded, visible progress metrics for this pass."""
    out: list[MetricInput] = []
    for item in results:
        snapshot = item.snapshot
        if snapshot is None:
            continue
        slot = (layout or {}).get("cards", {}).get(snapshot.card.card_id)
        if slot is not None and not slot.get("enabled", True):
            continue
        disabled = set(slot.get("disabled", []) if slot else [])
        always = set(slot.get("alwaysVisible", []) if slot else [])
        expanded = bool(slot.get("expanded", False)) if slot else True
        for metric_id, metric in snapshot.metrics.items():
            if not isinstance(metric, model.Progress) or not metric.limit > 0:
                continue
            if metric_id in disabled:
                continue
            if slot is not None and metric_id not in always and not expanded:
                continue
            title = labels.get((snapshot.card.family, metric_id), metric_id)
            out.append(MetricInput(
                key=f"{snapshot.card.card_id}:{metric_id}",
                provider=snapshot.card.family,
                title=title,
                state=meter_state(metric, snapshot.card.family, now),
                fraction=remaining_fraction(metric),
                resets_at=metric.resets_at,
            ))
    return out


def evaluate(metrics: list[MetricInput], toggles: dict[str, bool],
             stored: dict[str, NotificationState]
             ) -> tuple[list[tuple[MetricInput, str]], dict[str, NotificationState]]:
    """Fire milestones for this pass. Prunes metrics absent from the pass."""
    fired: list[tuple[MetricInput, str]] = []
    keep: dict[str, NotificationState] = {}
    for metric in metrics:
        previous = stored.get(metric.key, NotificationState())
        fire, current = transitions(metric.state, metric.fraction,
                                    metric.resets_at, previous, toggles)
        for milestone in fire:
            fired.append((metric, milestone))
        keep[metric.key] = current
    return fired, keep


def commit(fired: list[tuple[MetricInput, str]],
           keep: dict[str, NotificationState],
           previous: dict[str, NotificationState], delivered: bool) -> None:
    """Mark milestones fired only when delivery succeeded (in place).

    A failed delivery reverts the recorded advance to the previous pass's
    signals so the edge re-fires next pass instead of being lost.
    """
    for metric, milestone in fired:
        state = keep.get(metric.key)
        if state is None:
            continue
        if delivered:
            state.fired.add(milestone)
            continue
        old = previous.get(metric.key, NotificationState())
        if milestone == UNDER_TEN:
            state.was_under_ten = old.was_under_ten
        else:
            state.previous_bucket = old.previous_bucket


def load_state(dirs: paths.Paths) -> dict[str, NotificationState]:
    raw = atomic.read_json(dirs.notify_file)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return {}
    states = raw.get("states") or {}
    return {str(key): NotificationState.from_dict(item)
            for key, item in states.items() if isinstance(item, dict)}


def save_state(dirs: paths.Paths, stored: dict[str, NotificationState]) -> None:
    try:
        paths.assert_writable(dirs.notify_file, dirs.home)
        atomic.write_json_atomic(dirs.notify_file, {
            "schema": SCHEMA,
            "states": {key: item.to_dict() for key, item in stored.items()},
        })
    except (OSError, ValueError) as exc:
        log.get_logger("refresh").warning("notify state write failed: %s", exc)


OPEN_ACTION = "default"
IPC_CMD = ["omarchy-shell", "luth-v.openusage-omarchy", "open"]
QUICK_POLL_S = 0.5
WAITER_TIMEOUT_S = 3600
IPC_TIMEOUT_S = 10
_waiters: set[subprocess.Popen] = set()
_waiters_lock = threading.Lock()
_stopping = threading.Event()


def startup() -> None:
    _stopping.clear()


def shutdown() -> None:
    """Stop notification children before the daemon exits."""
    _stopping.set()
    with _waiters_lock:
        children = list(_waiters)
    for child in children:
        if child.poll() is None:
            try:
                child.terminate()
            except OSError:
                pass
    for child in children:
        try:
            child.wait(timeout=1)
        except subprocess.TimeoutExpired:
            child.kill()
            child.wait(timeout=1)
        except OSError:
            pass
    with _waiters_lock:
        _waiters.difference_update(children)


def _build_args(body: str) -> list[str]:
    return ["notify-send", "--app-name=OpenUsage",
            f"--action={OPEN_ACTION}=Open", "--wait",
            "OpenUsage", body]


def _open_dashboard() -> bool:
    """Run the plugin IPC to show the Dashboard. Never raises."""
    if shutil.which("omarchy-shell") is None:
        return False
    try:
        done = subprocess.run(IPC_CMD, capture_output=True,
                              timeout=IPC_TIMEOUT_S, check=False)
    except (OSError, subprocess.SubprocessError):
        return False
    return done.returncode == 0


def _wait_and_open(proc: "subprocess.Popen[str]") -> bool:
    """Wait for the close, then open on tap. Bounded, never raises."""
    try:
        try:
            out, _ = proc.communicate(timeout=WAITER_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            try:
                proc.kill()
            except OSError:
                pass
            try:
                out, _ = proc.communicate(timeout=10)
            except (OSError, subprocess.SubprocessError):
                return True
            out = out or ""
        if proc.returncode != 0:
            return False
        if not _stopping.is_set() and OPEN_ACTION in (out or "").split():
            _open_dashboard()
        return True
    except (OSError, subprocess.SubprocessError, ValueError):
        try:
            proc.terminate()
        except OSError:
            pass
        with _waiters_lock:
            _waiters.discard(proc)
        return False
    finally:
        with _waiters_lock:
            _waiters.discard(proc)


def post(alerts: list[tuple[MetricInput, str]],
         provider_name) -> bool:
    """One grouped notify-send call. False when delivery failed or skipped.

    Uses --action=default=Open --wait so a tap opens the Dashboard. The main
    thread blocks at most QUICK_POLL_S; a daemon thread waits for the close
    and runs the IPC. shutdown() terminates live children on daemon exit.
    """
    if not alerts or shutil.which("notify-send") is None:
        return False
    lines = []
    for metric, milestone in alerts:
        lines.append(f"{TITLES[milestone]} — "
                     f"{provider_name(metric.provider)} {metric.title}\n"
                     f"{BODIES[milestone]}")
    try:
        proc = subprocess.Popen(_build_args("\n".join(lines)),
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    with _waiters_lock:
        if _stopping.is_set():
            proc.terminate()
            return False
        _waiters.add(proc)
    try:
        out, _ = proc.communicate(timeout=QUICK_POLL_S)
    except subprocess.TimeoutExpired:
        try:
            worker = threading.Thread(target=_wait_and_open, args=(proc,),
                                      daemon=True)
            worker.start()
        except (OSError, RuntimeError, ValueError):
            try:
                proc.kill()
            except OSError:
                pass
            with _waiters_lock:
                _waiters.discard(proc)
            return True
        return True
    except (OSError, subprocess.SubprocessError, ValueError):
        try:
            proc.terminate()
        except OSError:
            pass
        with _waiters_lock:
            _waiters.discard(proc)
        return False
    with _waiters_lock:
        _waiters.discard(proc)
    if proc.returncode != 0:
        return False
    if OPEN_ACTION in (out or "").split():
        _open_dashboard()
    return True
