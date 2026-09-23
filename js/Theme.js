// Theme-derived colors. Pure; node-tested. Severity fills use Omarchy
// theme roles only: healthy takes the accent, critical takes urgent, and
// warning takes the theme's terminal yellow (colors.toml), falling back to
// the accent when the theme has no yellow. The spend ring keeps upstream's
// fixed per-provider brand colors (TotalSpendPalette).
function parseYellow(raw) {
    var match = /^\s*yellow\s*=\s*["']?(#[0-9A-Fa-f]{6})/m.exec(String(raw || ""));
    return match ? match[1] : null;
}
function meterColor(severity, roles) {
    roles = roles || {};
    if (severity === "critical")
        return roles.urgent;
    if (severity === "warning")
        return roles.warning || roles.accent;
    if (severity === "normal")
        return roles.accent;
    return roles.track;
}
var SPEND_COLORS = {
    claude: "#DE7356",
    codex: "#10A37F",
    openrouter: "#6467F2",
    antigravity: "#4285F4",
    copilot: "#A855F7"
};
var SPEND_ADAPTIVE = {
    cursor: {light: "#13120A", dark: "#F5F5F7"},
    grok: {light: "#8E8E93", dark: "#98989D"},
    opencode: {light: "#6E6E73", dark: "#AEAEB2"},
    zai: {light: "#2D2D2D", dark: "#D1D1D6"}
};
var SPEND_FALLBACK = ["#34C759", "#5856D6", "#FF2D55", "#A2845E"];
function spendColor(providerId, light) {
    var id = String(providerId || "");
    if (SPEND_COLORS[id])
        return SPEND_COLORS[id];
    if (SPEND_ADAPTIVE[id])
        return light ? SPEND_ADAPTIVE[id].light : SPEND_ADAPTIVE[id].dark;
    var hash = 0;
    for (var i = 0; i < id.length; i++)
        hash = (hash * 31 + id.charCodeAt(i)) & 0xFFFF;
    return SPEND_FALLBACK[hash % SPEND_FALLBACK.length];
}
function _channel(value) {
    var n = Number(value);
    if (!isFinite(n))
        return 0;
    return n <= 0.03928 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4);
}
function isLight(color) {
    var c = color || {};
    var lum = 0.2126 * _channel(c.r) + 0.7152 * _channel(c.g) + 0.0722 * _channel(c.b);
    return lum >= 0.5;
}
