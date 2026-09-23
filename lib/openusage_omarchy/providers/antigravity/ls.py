"""Language-server discovery over /proc (Linux port of the ps/lsof scan).

Finds a running ``language_server`` (Antigravity app) or ``agy`` (CLI) and
returns the CSRF token plus listening ports for its local Connect-RPC
service. No subprocesses: argv comes from ``cmdline``, ports from the TCP
tables joined to the process's socket inodes. ``proc_root`` is injectable
so tests run against a fake tree.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from ... import log

_LISTEN = "0A"


@dataclass(frozen=True)
class Found:
    pid: int
    csrf: str
    ports: tuple[int, ...]
    extension_port: int | None = None


def _basename_argv0(args: list[str]) -> str:
    if not args:
        return ""
    return args[0].rsplit("/", 1)[-1].lower()


def match_process(args: list[str], process_name: str) -> bool:
    """Argv matches the wanted executable (upstream name rules)."""
    name = process_name.lower()
    if not name or not args:
        return False
    exe = _basename_argv0(args)
    if exe == name:
        return True
    joined = " ".join(args).lower()
    if len(name) >= 8:
        return exe.startswith(name + "_") or name in joined
    return (
        joined.endswith("/" + name)
        or ("/" + name + " ") in joined
        or ("/" + name + "\t") in joined
    )


def extract_flag(args: list[str], flag: str) -> str | None:
    """A CLI flag value: ``--flag value`` or ``--flag=value``."""
    equals = flag + "="
    for index, part in enumerate(args):
        if part == flag:
            if index + 1 < len(args):
                return args[index + 1]
        elif part.startswith(equals):
            return part[len(equals):]
    return None


def marker_rank(args: list[str], markers: list[str]) -> int | None:
    """0 for an exact flag match, 1 for a path substring, None for no match."""
    wanted = [item.strip().lower() for item in markers if item.strip()]
    if not wanted:
        return 0
    flags = [
        (extract_flag(args, "--ide_name") or "").lower(),
        (extract_flag(args, "--override_ide_name") or "").lower(),
        (extract_flag(args, "--app_data_dir") or "").lower(),
    ]
    if any(flags):
        for marker in wanted:
            if marker in flags:
                return 0
        return None
    joined = " ".join(args).lower()
    for marker in wanted:
        if f"/{marker}/" in joined:
            return 1
    return None


def _tcp_listeners(proc_root: str) -> dict[str, int]:
    """Socket inode to local port for every LISTEN entry in the TCP tables."""
    found: dict[str, int] = {}
    for name in ("tcp", "tcp6"):
        try:
            with open(os.path.join(proc_root, "net", name), encoding="utf-8") as handle:
                lines = handle.read().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            parts = line.split()
            if len(parts) < 10 or parts[3] != _LISTEN:
                continue
            address = parts[1]
            colon = address.rfind(":")
            try:
                port = int(address[colon + 1:], 16)
            except ValueError:
                continue
            if 0 < port < 65536:
                found[parts[9]] = port
    return found


def listening_ports(pid: int, proc_root: str = "/proc") -> list[int]:
    """Ports the process listens on, via its socket inodes. Never raises."""
    try:
        table = _tcp_listeners(proc_root)
        names = os.listdir(os.path.join(proc_root, str(pid), "fd"))
    except OSError:
        return []
    ports: set[int] = set()
    for name in names:
        try:
            link = os.readlink(os.path.join(proc_root, str(pid), "fd", name))
        except OSError:
            continue
        if link.startswith("socket:[") and link.endswith("]"):
            port = table.get(link[len("socket:["):-1])
            if port is not None:
                ports.add(port)
    return sorted(ports)


def _cmdline(pid: int, proc_root: str) -> list[str] | None:
    try:
        with open(os.path.join(proc_root, str(pid), "cmdline"), "rb") as handle:
            raw = handle.read()
    except OSError:
        return None
    args = [part.decode("utf-8", "replace") for part in raw.split(b"\0") if part]
    return args or None


def discover(
    process_name: str,
    markers: list[str],
    csrf_flag: str,
    port_flag: str | None,
    proc_root: str = "/proc",
) -> Found | None:
    """First matching process with usable ports, best marker rank first."""
    logger = log.get_logger("subprocess")
    try:
        pids = sorted(int(name) for name in os.listdir(proc_root) if name.isdigit())
    except OSError:
        return None
    ranked: list[tuple[int, int, list[str]]] = []
    for pid in pids:
        args = _cmdline(pid, proc_root)
        if args is None or not match_process(args, process_name):
            continue
        rank = marker_rank(args, markers)
        if rank is not None:
            ranked.append((rank, pid, args))
    if not ranked:
        logger.info("ls discover: %s process not found", process_name)
        return None
    ranked.sort()
    for _rank, pid, args in ranked:
        if not csrf_flag.strip():
            csrf = ""
        else:
            found = extract_flag(args, csrf_flag)
            if found is None:
                continue
            csrf = found
        extension: int | None = None
        if port_flag:
            raw_port = extract_flag(args, port_flag)
            if raw_port is not None:
                try:
                    extension = int(raw_port)
                except ValueError:
                    extension = None
        ports = listening_ports(pid, proc_root)
        if not ports and extension is None:
            continue
        logger.info(
            "ls discover: found %s pid=%s ports=%s", process_name, pid, ports)
        return Found(pid=pid, csrf=csrf, ports=tuple(ports),
                     extension_port=extension)
    return None
