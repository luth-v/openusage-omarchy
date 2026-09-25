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
// "Claude — Work" -> "Work": the Account part of a card label.
function accountLabel(label) {
    var text = String(label || "");
    var cut = text.indexOf(" — ");
    return cut < 0 ? "" : text.slice(cut + 3).trim();
}
// Short Account prefixes for a family with several enabled cards
// (ADR 0006): first letter, first two where initials collide.
function accountPrefixes(labels) {
    var initial = function(text, n) {
        var head = String(text || "").slice(0, n);
        return head.charAt(0).toUpperCase() + head.slice(1);
    };
    var counts = {};
    var ids = Object.keys(labels);
    for (var i = 0; i < ids.length; i++) {
        var one = initial(labels[ids[i]], 1);
        counts[one] = (counts[one] || 0) + 1;
    }
    var out = {};
    for (var k = 0; k < ids.length; k++) {
        var first = initial(labels[ids[k]], 1);
        out[ids[k]] = counts[first] > 1 ? initial(labels[ids[k]], 2) : first;
    }
    return out;
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
    var perFamily = {};
    for (i = 0; i < order.length; i++) {
        var owned = layout.cards ? layout.cards[order[i]] : null;
        if (!owned || !owned.enabled || !byCard[order[i]])
            continue;
        var fam = _familyOf(order[i]);
        if (!perFamily[fam])
            perFamily[fam] = {};
        perFamily[fam][order[i]] = accountLabel(byCard[order[i]].label) || order[i];
    }
    var prefixes = {};
    for (var f in perFamily) {
        if (perFamily.hasOwnProperty(f) && Object.keys(perFamily[f]).length > 1) {
            var picked = accountPrefixes(perFamily[f]);
            for (var cid in picked)
                prefixes[cid] = picked[cid];
        }
    }
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
        var raws = [];
        for (var s = 0; s < stars.length; s++) {
            var metricId = stars[s];
            var metric = metrics[metricId];
            if (!hasDataFor(metric))
                continue;
            var def = _metricDef(providerDef, metricId);
            var label = trayLabel(def ? def.metricLabel || def.label : metricId);
            var shown = valueFor(family, metricId, metric, display, fmt);
            raws.push(shown);
            if (prefixes[cardId])
                shown = prefixes[cardId] + " " + shown;
            resolved.push({id: cardId + "." + metricId, label: label, value: shown, fraction: fractionFor(metric, display), isBounded: isBoundedFor(metric), hasData: true});
        }
        if (resolved.length === 0)
            continue;
        var name = prefixes[cardId] && stateCard.label ? String(stateCard.label) : String(providerDef.displayName || family);
        groups.push({cardId: cardId, family: family, displayName: name, accountPrefix: prefixes[cardId] || "", metrics: resolved, text: inlineText(prefixes[cardId], raws)});
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
// One-line bar text: ["74%", "45%"] + "W" -> "W 74·45%"; a shared "%" is kept once at the end.
function inlineText(prefix, raws) {
    var allPercent = raws.length > 1 && raws.every(function(v) { return /^\d+(\.\d+)?%$/.test(v); });
    var parts = allPercent ? raws.map(function(v, i) { return i < raws.length - 1 ? v.slice(0, -1) : v; }) : raws;
    var joined = parts.join("·");
    return prefix ? prefix + " " + joined : joined;
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
