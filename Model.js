// Pure quota model. All percentages are Used fractions until presentation.
var providers = [
    {id: "claude", name: "Claude", mark: "Cl"},
    {id: "codex", name: "Codex", mark: "Cx"},
    {id: "cursor", name: "Cursor", mark: "Cu"},
    {id: "opencode", name: "OpenCode", mark: "Oc"},
    {id: "grok", name: "Grok", mark: "Gr"}
];
function title(label) {
    return label.replace(/\s*\([^)]*\)/g, "").trim() || label;
}
function parse(raw, id) {
    try {
        var r = typeof raw === "string" ? JSON.parse(raw) : raw;
        if (!r || r.schemaVersion !== 1 || r.id !== id || !Array.isArray(r.limits)) return null;
        var limits = [];
        r.limits.forEach(function(l) {
            if (!l || typeof l.label !== "string" || !l.label.trim() || typeof l.percent !== "number" || !isFinite(l.percent) || l.percent < 0 || l.percent > 1) return;
            limits.push({label: l.label, title: typeof l.title === "string" && l.title ? l.title : title(l.label), percent: l.percent, resetsAt: typeof l.resetsAt === "string" ? l.resetsAt : ""});
        });
        return {id: id, limits: limits, ready: limits.length > 0, tierLabel: String(r.tierLabel || ""), updatedAt: String(r.updatedAt || ""), usageStatusText: String(r.usageStatusText || ""), authHelpText: String(r.authHelpText || "")};
    } catch (_) { return null; }
}
function lead(record) {
    if (!record) return null;
    return record.limits.reduce(function(best, l) { return !best || l.percent > best.percent ? l : best; }, null);
}
function displayed(p, display) { return display === "Left" ? 1-p : p; }
function percent(p, display) { return Math.round(displayed(p, display)*100) + "%"; }
function span(label) {
    var s = label.toLowerCase();
    if (/week|7.day/.test(s)) return 7*86400000;
    if (/month|30.day/.test(s)) return 30*86400000;
    if (/session|5.hour|5h|rolling/.test(s)) return 5*3600000;
    return 0;
}
function pace(limit, now) {
    if (limit.percent >= 0.9) return "alarm";
    var duration = span(limit.label), reset = Date.parse(limit.resetsAt);
    if (!duration || !isFinite(reset) || reset <= now) return "ok";
    var elapsed = Math.max(0, Math.min(1, 1-(reset-now)/duration));
    if (limit.percent > 0 && (elapsed === 0 || limit.percent / elapsed > 1)) return "alarm";
    return limit.percent >= elapsed * 0.9 && limit.percent > 0 ? "ahead" : "ok";
}
function countdown(reset, now) {
    var end = Date.parse(reset);
    if (!isFinite(end)) return "Reset unknown";
    var seconds = Math.ceil((end-now)/1000);
    if (seconds <= 0) return "Reset due";
    var minutes = Math.ceil(seconds/60), hours = Math.floor(minutes/60), days = Math.floor(hours/24);
    return days ? days+"d "+hours%24+"h" : hours ? hours+"h "+minutes%60+"m" : minutes+"m";
}
function metrics(record, star) {
    var first = lead(record);
    if (!first) return [];
    var result = [first];
    record.limits.forEach(function(l) { if (l.label === star && l.label !== first.label) result.push(l); });
    return result;
}
function barLabel(provider, record, star, display) {
    var chosen = metrics(record, star);
    return chosen.length ? provider.mark+" "+chosen.map(function(l) { return percent(l.percent, display); }).join(" · ") : "";
}
function percents(record, star, display) {
    return metrics(record, star).map(function(l) { return percent(l.percent, display); }).join(" · ");
}
function ordered(order) {
    var seen = {};
    var result = [];
    function push(id) {
        providers.forEach(function(p) {
            if (p.id === id && !seen[id]) { result.push(p); seen[id] = true; }
        });
    }
    if (Array.isArray(order)) order.forEach(push);
    providers.forEach(function(p) { push(p.id); });
    return result;
}
function move(order, id, delta) {
    var list = ordered(order).map(function(p) { return p.id; });
    var i = list.indexOf(id);
    var j = i + delta;
    if (i < 0 || j < 0 || j >= list.length) return list;
    var swap = list[i];
    list[i] = list[j];
    list[j] = swap;
    return list;
}

function themeWarning(raw, fallback) {
    var match = /^\s*yellow\s*=\s*["'](#[0-9a-fA-F]{6})["']/m.exec(raw);
    return match ? match[1] : fallback;
}
function status(record) {
    if (!record) return "Waiting for first refresh";
    // Packaged collectors always include login guidance, even when healthy.
    return [record.usageStatusText, (!record.ready || record.usageStatusText) ? record.authHelpText : ""].filter(function(s) { return !!s; }).join(" · ");
}
