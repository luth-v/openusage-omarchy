"""Update checks against this plugin's GitHub releases.

Per the G1 resolution: "Update Automatically" means automatic hourly checks;
the banner's Install button runs ``omarchy plugin update --yes`` on click;
the beta channel only widens which releases the check compares against.
An optional "Update with Omarchy" hook updates the plugin on ``omarchy
update``. Rsync (non-git) installs report installable=false.
"""

from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

from . import PLUGIN_ID, atomic, catalog, log, paths

REPO = "luth-v/openusage-omarchy"
RELEASES_URL = f"https://api.github.com/repos/{REPO}/releases"
CHECK_INTERVAL_S = 3600
SCHEMA = "openusage-omarchy.update.v1"

HOOK_BODY = f"""#!/usr/bin/env sh
# Managed by OpenUsage (Update with Omarchy). Delete this file to stop
# updating the plugin when Omarchy updates.
exec omarchy plugin update {PLUGIN_ID} --yes
"""


def parse_version(tag: str) -> tuple[int, ...]:
    """Numeric prefix of a tag: v0.9.0-beta.1 -> (0, 9, 0)."""
    text = str(tag).strip()
    if text[:1] in ("v", "V"):
        text = text[1:]
    parts: list[int] = []
    for chunk in re.split(r"[.\-_+]", text):
        digits = re.match(r"(\d+)", chunk)
        if digits is None:
            break
        parts.append(int(digits.group(1)))
    return tuple(parts) or (0,)


def is_newer(latest: str, current: str) -> bool:
    left, right = parse_version(latest), parse_version(current)
    width = max(len(left), len(right))
    left += (0,) * (width - len(left))
    right += (0,) * (width - len(right))
    return left > right


def select_latest(releases: list, beta: bool) -> str | None:
    """First non-draft tag the channel admits. GitHub lists newest first."""
    for entry in releases:
        if not isinstance(entry, dict) or entry.get("draft"):
            continue
        tag = entry.get("tag_name")
        if not isinstance(tag, str) or not tag.strip():
            continue
        if entry.get("prerelease") and not beta:
            continue
        return tag.strip()
    return None


def channel_name(beta: bool) -> str:
    return "beta" if beta else "stable"


@dataclass
class UpdateState:
    latest: str | None = None
    channel: str = "stable"
    checked_at: str | None = None
    snoozed: str | None = None
    installable: bool = False
    not_before: str | None = None

    def to_dict(self) -> dict:
        return {
            "latest": self.latest,
            "channel": self.channel,
            "checkedAt": self.checked_at,
            "snoozed": self.snoozed,
            "installable": self.installable,
        }

    def to_disk(self) -> dict:
        out = self.to_dict()
        out["schema"] = SCHEMA
        out["notBefore"] = self.not_before
        return out

    @classmethod
    def from_disk(cls, raw: dict) -> "UpdateState":
        return cls(
            latest=raw.get("latest"),
            channel=str(raw.get("channel", "stable")),
            checked_at=raw.get("checkedAt"),
            snoozed=raw.get("snoozed"),
            not_before=raw.get("notBefore"),
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


def due(state: UpdateState, auto: bool, now: dt.datetime) -> bool:
    if not auto:
        return False
    blocked = _parse_time(state.not_before)
    if blocked is not None and now < blocked:
        return False
    checked = _parse_time(state.checked_at)
    if checked is None:
        return True
    return (now - checked).total_seconds() >= CHECK_INTERVAL_S


def load_state(dirs: paths.Paths, installable: bool) -> UpdateState:
    raw = atomic.read_json(dirs.update_file)
    if not isinstance(raw, dict) or raw.get("schema") != SCHEMA:
        return UpdateState(installable=installable)
    state = UpdateState.from_disk(raw)
    state.installable = installable
    return state


def save_state(dirs: paths.Paths, state: UpdateState) -> None:
    try:
        paths.assert_writable(dirs.update_file, dirs.home)
        atomic.write_json_atomic(dirs.update_file, state.to_disk())
    except (OSError, ValueError) as exc:
        log.get_logger("updates").warning("update state write failed: %s", exc)


def is_installable(plugin_root: Path | None = None) -> bool:
    root = plugin_root or catalog.plugin_root()
    return (root / ".git").is_dir()


def _backoff_until(response, now: dt.datetime) -> dt.datetime:
    header = response.header or (lambda name: None)
    retry = header("Retry-After")
    if retry is not None:
        try:
            return now + dt.timedelta(seconds=max(60, int(str(retry).strip())))
        except (TypeError, ValueError):
            pass
    reset = header("X-RateLimit-Reset")
    if reset is not None:
        try:
            moment = dt.datetime.fromtimestamp(int(str(reset).strip()),
                                               tz=dt.timezone.utc)
            if moment > now:
                return moment
        except (TypeError, ValueError, OverflowError, OSError):
            pass
    return now + dt.timedelta(minutes=30)


def run_check(http, state: UpdateState, current: str, beta: bool,
              now: dt.datetime, force: bool = False) -> UpdateState:
    """Fetch releases and refresh the state. Mutates and returns the state."""
    from . import http as _httpmod

    if not force and not due(state, True, now):
        return state
    logger = log.get_logger("updates")
    try:
        response = http.get(RELEASES_URL, headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "openusage-omarchy",
        }, timeout=30)
    except _httpmod.HttpError as exc:
        logger.warning("update check failed: %s", exc)
        return state
    if response.status in (403, 429):
        state.not_before = _backoff_until(response, now).isoformat()
        state.checked_at = now.isoformat()
        state.channel = channel_name(beta)
        logger.warning("update check rate-limited; retry after %s",
                       state.not_before)
        return state
    if response.status != 200:
        logger.warning("update check returned status %d", response.status)
        return state
    try:
        releases = json.loads(response.body.decode("utf-8", errors="replace"))
    except ValueError:
        logger.warning("update check returned bad JSON")
        return state
    if not isinstance(releases, list):
        logger.warning("update check returned bad JSON")
        return state
    latest = select_latest(releases, beta)
    state.channel = channel_name(beta)
    state.checked_at = now.isoformat()
    state.not_before = None
    if latest is not None and is_newer(latest, current):
        state.latest = latest
    elif latest is None or not is_newer(latest, current):
        state.latest = None
    # A dismiss lasts until the next check finds the update again, as
    # upstream: every successful check re-arms the banner.
    state.snoozed = None
    logger.info("update check finished (channel=%s, latest=%s)",
                state.channel, state.latest)
    return state


def snooze(state: UpdateState, version: str) -> None:
    state.snoozed = version


def install() -> bool:
    """Detach the updater so the shell reload cannot close its pipes."""
    logger = log.get_logger("updates")
    try:
        proc = subprocess.Popen(
            ["omarchy", "plugin", "update", PLUGIN_ID, "--yes"],
            start_new_session=True, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
            close_fds=True)
        threading.Thread(target=proc.wait, name="openusage-update-reap",
                         daemon=True).start()
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("update install failed: %s", exc)
        return False
    logger.info("update install started")
    return True


def reconcile_hook(dirs: paths.Paths, enabled: bool, installable: bool) -> None:
    """Write or remove exactly one plugin-owned hook file. Nothing else."""
    target = dirs.hook_file
    logger = log.get_logger("updates")
    if not enabled or not installable:
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("hook removal failed: %s", exc)
        return
    try:
        paths.assert_writable(target, dirs.home)
        current = target.read_text(encoding="utf-8") if target.exists() else None
    except OSError:
        current = None
    if current == HOOK_BODY:
        return
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(HOOK_BODY, encoding="utf-8")
        target.chmod(0o755)
    except OSError as exc:
        logger.warning("hook write failed: %s", exc)
