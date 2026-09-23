"""XDG paths plus the forbidden-path guard.

All new paths use ``openusage-omarchy``. The ``openusage`` state, config and
bin paths belong to an unrelated tool and must never be read or written.
"""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from . import APP_DIR


@dataclass(frozen=True)
class Paths:
    home: Path
    state_dir: Path
    cache_dir: Path
    config_dir: Path
    data_dir: Path
    runtime_dir: Path

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Paths":
        src = env if env is not None else os.environ
        home = Path(src.get("HOME") or str(Path.home())).expanduser()
        state = Path(src.get("XDG_STATE_HOME") or (home / ".local" / "state"))
        cache = Path(src.get("XDG_CACHE_HOME") or (home / ".cache"))
        config = Path(src.get("XDG_CONFIG_HOME") or (home / ".config"))
        data = Path(src.get("XDG_DATA_HOME") or (home / ".local" / "share"))
        runtime = Path(src.get("XDG_RUNTIME_DIR") or (Path("/tmp") / f"runtime-{os.getuid()}"))
        return cls(
            home=home,
            state_dir=state / APP_DIR,
            cache_dir=cache / APP_DIR,
            config_dir=config / APP_DIR,
            data_dir=data / APP_DIR,
            runtime_dir=runtime / APP_DIR,
        )

    @property
    def state_file(self) -> Path:
        return self.state_dir / "state.json"

    @property
    def layout_file(self) -> Path:
        return self.state_dir / "layout.json"

    @property
    def snapshots_dir(self) -> Path:
        return self.cache_dir / "snapshots"

    @property
    def pricing_dir(self) -> Path:
        return self.cache_dir / "pricing"

    @property
    def scan_dir(self) -> Path:
        return self.cache_dir / "log-scan"

    @property
    def log_file(self) -> Path:
        return self.state_dir / f"{APP_DIR}.log"

    @property
    def daemon_lock(self) -> Path:
        return self.runtime_dir / "daemon.lock"

    @property
    def session_file(self) -> Path:
        return self.runtime_dir / "session"

    @property
    def shell_json(self) -> Path:
        base = self.config_dir.parent
        return base / "omarchy" / "shell.json"

    @property
    def proxy_config(self) -> Path:
        return self.config_dir / "config.json"

    @property
    def bind_file(self) -> Path:
        return self.config_dir / "hyprland.conf"

    @property
    def update_file(self) -> Path:
        return self.state_dir / "update.json"

    @property
    def notify_file(self) -> Path:
        return self.state_dir / "notify.json"

    @property
    def hook_file(self) -> Path:
        base = self.config_dir.parent
        return base / "omarchy" / "hooks" / "post-update.d" / "openusage-omarchy"


def forbidden_prefixes(home: Path) -> list[Path]:
    local = home / ".local"
    config = home / ".config"
    return [
        local / "state" / "openusage",
        config / "openusage",
        local / "bin" / "openusage",
        Path("/usr/share/omarchy"),
        config / "hypr",
    ]


def assert_writable(path: Path, home: Path | None = None) -> Path:
    """Refuse writes into forbidden locations. Returns the path when allowed."""
    base = home or Path.home()
    resolved = Path(os.path.normpath(path))
    for prefix in forbidden_prefixes(base):
        if resolved == prefix or prefix in resolved.parents:
            raise ValueError(f"refusing to write forbidden path: {path}")
    return path


def ensure_dir(path: Path, mode: int = 0o700) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, mode)
    except OSError:
        pass
    return path


def ensure_runtime_dir(path: Path) -> Path:
    """Reject another user's or a symlinked runtime root before writing."""
    for target in (path.parent, path):
        try:
            target.mkdir(mode=0o700)
        except FileExistsError:
            pass
        info = target.lstat()
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) & 0o077):
            raise OSError("runtime directory must be private and owned by this user")
    return path


def _chmod(path: Path, mode: int) -> None:
    try:
        if path.is_symlink():
            return
        os.chmod(path, mode)
    except OSError:
        pass


def harden(dirs: Paths) -> None:
    """Make state and cache dirs 0700 and their files 0600, best-effort.

    Runs at startup: writers already create private files, but QML-owned
    layout.json and pre-existing installs may be wider. Never raises.
    """
    for directory in (dirs.state_dir, dirs.cache_dir, dirs.snapshots_dir,
                      dirs.pricing_dir, dirs.scan_dir):
        try:
            ensure_dir(directory, 0o700)
        except OSError:
            continue
    for root in (dirs.state_dir, dirs.cache_dir):
        try:
            entries = list(root.rglob("*"))
        except OSError:
            continue
        for entry in entries:
            if entry.is_symlink():
                continue
            if entry.is_dir():
                _chmod(entry, 0o700)
            elif entry.is_file():
                _chmod(entry, 0o600)


def harden_runtime_files(dirs: Paths) -> None:
    """Re-tighten files rewritten at runtime (QML owns layout.json).

    Called after each batch publish: a few chmods, no walk. Never raises.
    """
    stem = dirs.log_file.stem
    for path in (dirs.state_file, dirs.layout_file, dirs.update_file,
                 dirs.notify_file, dirs.log_file,
                 dirs.log_file.with_name(f"{stem}.1.log")):
        _chmod(path, 0o600)
