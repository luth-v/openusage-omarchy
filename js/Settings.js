// Settings view model. Pure; node-tested. Option lists mirror the upstream
// Setting label enums; notification rows mirror PaceMilestone labels and
// tooltips; the reset copy mirrors SettingsScreen (minus the iCloud clause,
// which ADR 0005 omits). Shortcut helpers format and parse the shell.json
// `shortcut` string; the daemon (pass 8) validates the combo grammar.
var STYLE_OPTIONS = [{value: "Text", label: "Text"}, {value: "Bars", label: "Bars"}];
var DENSITY_OPTIONS = [{value: "Default", label: "Default"}, {value: "Compact", label: "Compact"}];
var TIME_FORMAT_OPTIONS = [{value: "Auto", label: "Auto"}, {value: "12h", label: "12-hour"}, {value: "24h", label: "24-hour"}];
var DISPLAY_OPTIONS = [{value: "Used", label: "Used"}, {value: "Left", label: "Left"}];
var RESET_OPTIONS = [{value: "Countdown", label: "Countdown"}, {value: "Exact Time", label: "Exact Time"}];
var LOG_LEVEL_OPTIONS = [{value: "Error", label: "Error"}, {value: "Warning", label: "Warning"}, {value: "Info", label: "Info"}, {value: "Debug", label: "Debug"}];
var NOTIFICATIONS = [
    {key: "notifyAlmostOut", label: "Almost Out",
        tip: "Alert when a limit drops below 10% remaining."},
    {key: "notifyCuttingClose", label: "Cutting It Close",
        tip: "Alert when a limit is projected to finish with little left."},
    {key: "notifyWillRunOut", label: "Will Run Out",
        tip: "Alert when a limit is projected to finish before it resets."}
];
var RESET_SETTINGS_TITLE = "Reset All Settings?";
var RESET_SETTINGS_MESSAGE = "Restores every setting and customization to its default and turns providers back on for the tools you have installed. This cannot be undone.";
var UPDATE_WITH_OMARCHY_NOTE = "Update this plugin when Omarchy updates (git installs only).";
var CUSTOMIZE_CROSS_LINK = {title: "Customize", subtitle: "Choose what's visible and where"};
var SETTINGS_CROSS_LINK = {title: "Settings", subtitle: "Notifications, appearance and more"};
var MOD_ORDER = ["SUPER", "SHIFT", "CTRL", "ALT"];
var MOD_LABELS = {SUPER: "Super", SHIFT: "Shift", CTRL: "Ctrl", ALT: "Alt"};
var NAMED_KEYS = ["SPACE", "RETURN", "ENTER", "TAB", "ESCAPE", "BACKSPACE", "DELETE",
    "INSERT", "HOME", "END", "PAGEUP", "PAGEDOWN", "UP", "DOWN", "LEFT", "RIGHT",
    "MINUS", "EQUAL", "BRACKETLEFT", "BRACKETRIGHT", "BACKSLASH", "SEMICOLON",
    "APOSTROPHE", "COMMA", "PERIOD", "SLASH", "GRAVE",
    "F1", "F2", "F3", "F4", "F5", "F6", "F7", "F8", "F9", "F10", "F11", "F12"];
function validShortcutKey(key) {
    var text = String(key || "").trim().toUpperCase();
    if (/^[A-Z0-9]$/.test(text) || NAMED_KEYS.indexOf(text) >= 0)
        return text;
    return null;
}
function sortedMods(mods) {
    var seen = {};
    var list = [];
    var input = Array.isArray(mods) ? mods : [];
    for (var i = 0; i < input.length; i++) {
        var mod = String(input[i]).toUpperCase();
        if (MOD_ORDER.indexOf(mod) >= 0 && !seen[mod]) {
            seen[mod] = true;
            list.push(mod);
        }
    }
    return MOD_ORDER.filter(function(mod) { return seen[mod]; });
}
// "Super+Shift+O" for the shell.json string and the recorder chips.
function formatShortcut(mods, key) {
    var name = validShortcutKey(key);
    if (!name)
        return "";
    var parts = sortedMods(mods).map(function(mod) { return MOD_LABELS[mod]; });
    parts.push(name.length === 1 ? name.toUpperCase() : name);
    return parts.join("+");
}
function parseShortcut(text) {
    var parts = String(text || "").split("+").map(function(p) { return p.trim(); }).filter(function(p) { return p !== ""; });
    if (parts.length === 0)
        return null;
    var key = parts[parts.length - 1];
    var mods = [];
    var labels = {};
    for (var i = 0; i < MOD_ORDER.length; i++)
        labels[MOD_LABELS[MOD_ORDER[i]].toUpperCase()] = MOD_ORDER[i];
    for (var k = 0; k < parts.length - 1; k++) {
        var mod = labels[parts[k].toUpperCase()] || null;
        if (!mod)
            return null;
        mods.push(mod);
    }
    if (/^(SUPER|SHIFT|CTRL|ALT)$/i.test(key) || !validShortcutKey(key))
        return null;
    return {mods: sortedMods(mods), key: key.length === 1 ? key.toUpperCase() : key};
}
// Structured payload for the daemon setShortcut command (pass 8).
function shortcutPayload(mods, key) {
    var name = validShortcutKey(key);
    if (!name || sortedMods(mods).length === 0)
        return null;
    return {mods: sortedMods(mods), key: name};
}
// Codex fallback picker: "None", the option title, or "Unavailable Model".
function fallbackTitle(options, selected) {
    var id = String(selected || "");
    if (!id)
        return "None";
    var list = Array.isArray(options) ? options : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === id)
            return String(list[i].title || id);
    return "Unavailable Model";
}
function fallbackUnavailable(options, selected) {
    var id = String(selected || "");
    if (!id)
        return false;
    var list = Array.isArray(options) ? options : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === id)
            return false;
    return true;
}
// Settings `claudeAccounts`: {"~/.claude-work": {label, hidden}} keyed by
// config dir (ADR 0006). Returns a new object with one dir patched; an entry
// back at defaults (no label, shown) is dropped so shell.json stays small.
function claudeAccountsWith(current, dir, patch) {
    var out = {};
    var source = current && typeof current === "object" && !Array.isArray(current) ? current : {};
    for (var key in source)
        if (source.hasOwnProperty(key) && source[key] && typeof source[key] === "object")
            out[key] = {label: String(source[key].label || ""), hidden: source[key].hidden === true};
    var name = String(dir || "");
    if (!name)
        return out;
    var entry = out[name] || {label: "", hidden: false};
    if (patch && typeof patch.label === "string")
        entry.label = patch.label.trim();
    if (patch && typeof patch.hidden === "boolean")
        entry.hidden = patch.hidden;
    if (entry.label === "" && !entry.hidden)
        delete out[name];
    else
        out[name] = entry;
    return out;
}
// One row per discovered dir from state.claudeAccounts, labels from Settings.
function claudeAccountRows(state, saved) {
    var list = state && Array.isArray(state.claudeAccounts) ? state.claudeAccounts : [];
    var prefs = saved && typeof saved === "object" ? saved : {};
    return list.filter(function(row) { return row && typeof row.dir === "string"; }).map(function(row) {
        var pref = prefs[row.dir] || {};
        return {dir: row.dir, placeholder: String(row.placeholder || ""),
            label: typeof pref.label === "string" ? pref.label : String(row.label || ""),
            hidden: pref.hidden === true || (pref.hidden === undefined && row.hidden === true)};
    });
}
