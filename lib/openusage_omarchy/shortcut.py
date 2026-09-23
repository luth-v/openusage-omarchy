"""Global-shortcut bind file. Strict grammar, one fixed output line.

The recorded combo is written into a file that Hyprland ``source``s, so the
grammar admits only ``{mods, key}`` and emits exactly one line. Anything
else (newlines, commas, shell metacharacters) is rejected. The daemon never
touches ``~/.config/hypr/*``; the user adds the ``source =`` line by hand.
"""

from __future__ import annotations

from . import PLUGIN_ID, log, paths

MODS = ("SUPER", "SHIFT", "CTRL", "ALT")

NAMED_KEYS = frozenset({
    "SPACE", "RETURN", "ENTER", "TAB", "ESCAPE", "BACKSPACE", "DELETE",
    "INSERT", "HOME", "END", "PAGEUP", "PAGEDOWN",
    "UP", "DOWN", "LEFT", "RIGHT",
    "MINUS", "EQUAL", "BRACKETLEFT", "BRACKETRIGHT", "BACKSLASH",
    "SEMICOLON", "APOSTROPHE", "COMMA", "PERIOD", "SLASH", "GRAVE",
} | {f"F{n}" for n in range(1, 13)})

MOD_LABELS = {"SUPER": "Super", "SHIFT": "Shift", "CTRL": "Ctrl", "ALT": "Alt"}

BIND_LINE = "bind = {mods}, {key}, exec, omarchy-shell {plugin} toggle"


def valid_key(key: object) -> str | None:
    """Canonical key text, or None when the key is outside the grammar."""
    if not isinstance(key, str):
        return None
    text = key.strip()
    if len(text) == 1 and (text.isascii() and text.isalnum()):
        return text.upper()
    upper = text.upper()
    return upper if upper in NAMED_KEYS else None


def valid_mods(mods: object) -> list[str] | None:
    """Canonical mod list in fixed order, or None when invalid."""
    if not isinstance(mods, list):
        return None
    seen: list[str] = []
    for item in mods:
        if not isinstance(item, str) or item.upper() not in MODS:
            return None
        if item.upper() not in seen:
            seen.append(item.upper())
    return [mod for mod in MODS if mod in seen]


def valid_combo(combo: object) -> dict | None:
    """Canonical ``{mods, key}``, or None when the combo is invalid."""
    if not isinstance(combo, dict):
        return None
    mods = valid_mods(combo.get("mods"))
    key = valid_key(combo.get("key"))
    if mods is None or key is None or not mods:
        return None
    return {"mods": mods, "key": key}


def render(combo: dict) -> str:
    mods = " ".join(combo["mods"])
    return BIND_LINE.format(mods=mods, key=combo["key"], plugin=PLUGIN_ID) + "\n"


def parse_display(text: str) -> dict | None:
    """Parse the shell.json display string (Super+Shift+O) into a combo."""
    parts = [item.strip() for item in str(text or "").split("+")]
    parts = [item for item in parts if item]
    if not parts:
        return None
    labels = {label.upper(): mod for mod, label in MOD_LABELS.items()}
    mods: list[str] = []
    for item in parts[:-1]:
        mod = labels.get(item.upper())
        if mod is None:
            return None
        mods.append(mod)
    key = parts[-1]
    if key.upper() in MODS:
        return None
    return valid_combo({"mods": mods, "key": key})


def apply(dirs: paths.Paths, combo: dict | None) -> bool:
    """Write the bind file for combo, or remove it for None. True on change."""
    target = dirs.bind_file
    logger = log.get_logger("config")
    if combo is None:
        try:
            target.unlink(missing_ok=True)
        except OSError as exc:
            logger.warning("shortcut removal failed: %s", exc)
            return False
        return True
    try:
        paths.assert_writable(target, dirs.home)
        current = target.read_text(encoding="utf-8") if target.exists() else None
    except OSError:
        current = None
    wanted = render(combo)
    if current == wanted:
        return False
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(wanted, encoding="utf-8")
        target.chmod(0o600)
    except OSError as exc:
        logger.warning("shortcut write failed: %s", exc)
        return False
    return True


def reconcile(dirs: paths.Paths, display: str) -> None:
    """Rewrite the bind file from the shell.json string."""
    text = str(display or "").strip()
    apply(dirs, parse_display(text) if text else None)
