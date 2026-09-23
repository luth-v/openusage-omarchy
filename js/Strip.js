// Bar strip content. Ports MenuBarContentBuilder and MenuBarBarGeometry.
// fmt injects Format.{number,stringFor} so this file stays decoupled.
var MAX_BARS = 4;
function trayLabel(metricLabel) {
    var s = String(metricLabel || "").toLowerCase();
    if (s === "today")
        return "T";
    if (s === "yesterday")
        return "Y";
    if (s === "last 30 days")
        return "M";
    return String(metricLabel || "");
}
function traySuffixFor(family, metricId) {
    if ((family === "claude" || family === "codex") && metricId === "rateLimitResets")
        return "resets";
    return null;
}
function displayedValue(used, limit, display) {
    if (String(display) === "Left")
        return Math.max(0, Number(limit) - Number(used));
    return Number(used);
}
function _rounded(value, kind) {
    var v = Number(value);
    if (!isFinite(v))
        return 0;
    if (kind === "percent")
        return Math.round(v);
    if (kind === "count")
        return Math.round(v * 10) / 10;
    return Math.round(v * 100) / 100;
}
function hasDataFor(metric) {
    if (!metric || typeof metric.type !== "string")
        return false;
    if (metric.type === "progress")
        return true;
    if (metric.type === "values")
        return Array.isArray(metric.values) && metric.values.length > 0;
    if (metric.type === "text")
        return String(metric.value || "") !== "";
    if (metric.type === "badge")
        return String(metric.text || "") !== "";
    if (metric.type === "chart")
        return Array.isArray(metric.points) && metric.points.length > 0;
    return false;
}
function isBoundedFor(metric) {
    return !!metric && metric.type === "progress" && Number(metric.limit) > 0;
}
function fractionFor(metric, display) {
    if (!isBoundedFor(metric))
        return 0;
    var kind = metric.format && metric.format.kind ? metric.format.kind : "percent";
    var shown = _rounded(displayedValue(metric.used, metric.limit, display), kind);
    var frac = shown / Number(metric.limit);
    return Math.min(1, Math.max(0, frac));
}
function valueFor(family, metricId, metric, display, fmt) {
    if (!metric)
        return "";
    if (metric.type === "progress") {
        var kind = metric.format && metric.format.kind ? metric.format.kind : "percent";
        var shown = displayedValue(metric.used, metric.limit, display);
        if (kind === "percent") {
            var pct = Math.round(Math.min(100, Math.max(0, shown / Number(metric.limit) * 100)));
            return pct + "%";
        }
        return fmt.number(shown, kind, "tray");
    }
    if (metric.type === "values") {
        var first = metric.values && metric.values.length > 0 ? metric.values[0] : null;
        if (!first)
            return "";
        var suffix = traySuffixFor(family, metricId);
        if (suffix && first.kind === "count")
            return fmt.number(first.number, "count", "tray") + " " + suffix;
        return fmt.stringFor(first, "tray");
    }
    if (metric.type === "text")
        return String(metric.value || "");
    if (metric.type === "badge")
        return String(metric.text || "");
    return "";
}
function _provider(catalog, family) {
    var list = catalog && Array.isArray(catalog.providers) ? catalog.providers : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === family)
            return list[i];
    return null;
}
function _metricDef(providerDef, metricId) {
    var list = providerDef && Array.isArray(providerDef.metrics) ? providerDef.metrics : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === metricId)
            return list[i];
    return null;
}
function _familyOf(cardId) {
    var cut = String(cardId).indexOf(":");
    return cut < 0 ? String(cardId) : String(cardId).slice(0, cut);
}
function build(layout, catalog, state, display, fmt) {
    var empty = {groups: [], bars: [], isEmpty: true, accessibilityText: ""};
    if (!layout || !catalog || !state || !Array.isArray(state.cards) || !fmt)
        return empty;
    var byCard = {};
    var i;
    for (i = 0; i < state.cards.length; i++) {
        var card = state.cards[i];
        if (card && card.cardId)
            byCard[card.cardId] = card;
    }
    var groups = [];
    var order = Array.isArray(layout.order) ? layout.order : [];
    for (i = 0; i < order.length; i++) {
        var cardId = order[i];
        var slot = layout.cards ? layout.cards[cardId] : null;
        if (!slot || !slot.enabled)
            continue;
        var family = _familyOf(cardId);
        var providerDef = _provider(catalog, family);
        if (!providerDef)
            continue;
        var stateCard = byCard[cardId];
        var metrics = stateCard && stateCard.metrics ? stateCard.metrics : {};
        var stars = Array.isArray(slot.stars) ? slot.stars.slice() : [];
        var alwaysSet = {};
        var always = Array.isArray(slot.alwaysVisible) ? slot.alwaysVisible : [];
        for (var a = 0; a < always.length; a++)
            alwaysSet[always[a]] = true;
        var rank = {};
        var mo = Array.isArray(slot.metricOrder) ? slot.metricOrder : [];
        for (var r = 0; r < mo.length; r++)
            rank[mo[r]] = r;
        stars.sort(function(x, y) {
            var ax = alwaysSet[x] ? 0 : 1;
            var ay = alwaysSet[y] ? 0 : 1;
            if (ax !== ay)
                return ax - ay;
            var rx = rank[x] === undefined ? 999 : rank[x];
            var ry = rank[y] === undefined ? 999 : rank[y];
            return rx - ry;
        });
        var resolved = [];
        for (var s = 0; s < stars.length; s++) {
            var metricId = stars[s];
            var metric = metrics[metricId];
            if (!hasDataFor(metric))
                continue;
            var def = _metricDef(providerDef, metricId);
            var label = trayLabel(def ? def.metricLabel || def.label : metricId);
            resolved.push({id: cardId + "." + metricId, label: label, value: valueFor(family, metricId, metric, display, fmt), fraction: fractionFor(metric, display), isBounded: isBoundedFor(metric), hasData: true});
        }
        if (resolved.length === 0)
            continue;
        groups.push({cardId: cardId, family: family, displayName: String(providerDef.displayName || family), metrics: resolved});
    }
    if (groups.length === 0)
        return empty;
    var bars = [];
    for (i = 0; i < groups.length && bars.length < MAX_BARS; i++) {
        var items = groups[i].metrics;
        for (var k = 0; k < items.length && bars.length < MAX_BARS; k++) {
            if (items[k].isBounded)
                bars.push(items[k]);
        }
    }
    var text = groups.map(function(g) {
        return g.displayName + " " + g.metrics.map(function(m) { return m.label + " " + m.value; }).join(", ");
    }).join("; ");
    return {groups: groups, bars: bars, isEmpty: false, accessibilityText: text};
}
function visualFraction(fraction) {
    var f = Number(fraction);
    if (!isFinite(f))
        return 0;
    var clamped = Math.min(1, Math.max(0, f));
    if (clamped > 0.7 && clamped < 1) {
        var remainder = 1 - clamped;
        var quantized = Math.min(1, Math.ceil(remainder / 0.15) * 0.15);
        return Math.max(0, 1 - quantized);
    }
    return clamped;
}
function fill(trackW, fraction) {
    var w = Number(trackW);
    var f = Number(fraction);
    if (!isFinite(w) || !isFinite(f) || !(f > 0))
        return {fillW: 0, remainderW: 0, dividerX: null};
    var visual = visualFraction(f);
    if (visual >= 1)
        return {fillW: w, remainderW: 0, dividerX: null};
    var minVisible = Math.max(4, Math.round(w * 0.2));
    var maxFillW = Math.max(1, w - minVisible);
    var fillW = Math.max(1, Math.min(maxFillW, Math.round(w * visual)));
    var remainderW = Math.min(w - 1, Math.max(w - fillW, minVisible));
    return {fillW: fillW, remainderW: remainderW, dividerX: w - remainderW};
}
function barsLayout(side, count) {
    var s = Math.max(8, Number(side) || 18);
    var n = Math.max(1, Math.min(4, Number(count) || 1));
    var pad = Math.max(1, Math.round(s * 0.08));
    var gap = Math.max(1, Math.round(s * 0.03));
    var trackX = pad;
    var trackW = s - 2 * pad;
    var layoutN = Math.max(2, n);
    var trackH = Math.max(1, Math.floor((s - 2 * pad - (layoutN - 1) * gap) / layoutN));
    var rx = Math.max(1, Math.floor(trackH / 3));
    var totalBars = n * trackH + (n - 1) * gap;
    var yOffset = pad + Math.floor((s - 2 * pad - totalBars) / 2);
    return {side: s, count: n, pad: pad, gap: gap, trackX: trackX, trackW: trackW, trackH: trackH, rx: rx, yOffset: yOffset};
}
