.import "Catalog.js" as Catalog
// Dashboard view model. Pure; node-tested. Ports WidgetData (headline,
// trailing, unbounded detail), WidgetDataStore header bits (plan, warning,
// staleness), and the row/header/options menu items. Deps inject Format
// (fmt), Pace (pace) and Layout (layout, for displayMetrics only).
var NO_DATA = "No data";
var NO_DATA_HEADLINE = "—";
var EMPTY_DASHBOARD = "Turn on Customize to choose what to show.";
var STALE_AFTER_S = 600;
var USAGE_PERIODS = ["today", "yesterday", "last30"];
var RESETS_METRIC = "rateLimitResets";
var LOCAL_ESTIMATE_NOTE = "Estimated locally, so it may be off";
var CURSOR_HISTORY_NOTE = "From your Cursor usage history.";
var FRESH_SESSION_TIP = "Sessions start after you send your first message.";
// Lone-dollar trailing words (WidgetDescriptor+Factories valueWord).
var VALUE_WORDS = {
    "claude.extra": "spent",
    "cursor.onDemand": "spent",
    "cursor.credits": "left",
    "copilot.orgSpend": "spent",
    "devin.extra": "left",
    "ollama.last4Weeks": "spent",
    "openrouter.balance": "left",
    "openrouter.keyLimit": "spent"
};
function providerDef(catalog, family) {
    var list = catalog && Array.isArray(catalog.providers) ? catalog.providers : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === family)
            return list[i];
    return null;
}
function metricDef(catalog, family, metricId) {
    var def = providerDef(catalog, family);
    var list = def && Array.isArray(def.metrics) ? def.metrics : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === metricId)
            return list[i];
    return null;
}
function metricTitle(catalog, family, metricId) {
    var def = metricDef(catalog, family, metricId);
    if (!def)
        return String(metricId);
    return String(def.metricLabel || def.label || metricId);
}
function cardById(state, cardId) {
    var list = state && Array.isArray(state.cards) ? state.cards : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].cardId === cardId)
            return list[i];
    return null;
}
function isRefreshing(refresh, cardId) {
    var flight = refresh && Array.isArray(refresh.inFlight) ? refresh.inFlight : [];
    return flight.indexOf(cardId) >= 0;
}
function _ms(x) {
    if (Object.prototype.toString.call(x) === "[object Date]")
        return x.getTime();
    if (typeof x === "number")
        return x;
    if (typeof x === "string") {
        var t = new Date(x).getTime();
        return isNaN(t) ? null : t;
    }
    return null;
}
function stalenessHint(fetchedAt, now, fmt) {
    var f = _ms(fetchedAt);
    var n = now === undefined ? Date.now() : _ms(now);
    if (f === null || n === null)
        return null;
    var age = (n - f) / 1000;
    if (!(age >= STALE_AFTER_S))
        return null;
    var duration = fmt.compactDuration(age);
    if (!duration)
        return null;
    return {label: "Outdated", tooltip: "Last updated " + duration + " ago"};
}
function hasDataFor(metric) {
    if (!metric || typeof metric.type !== "string")
        return false;
    if (metric.type === "progress")
        return Number(metric.limit) > 0;
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
function _shown(used, limit, display) {
    if (String(display) === "Left")
        return Math.max(0, Number(limit) - Number(used));
    return Number(used);
}
function _headlinePercent(metric, display) {
    var pct = Math.round(Math.min(100, Math.max(0, _shown(metric.used, metric.limit, display) / Number(metric.limit) * 100)));
    return pct + "%";
}
function _meterRow(catalog, family, metricId, metric, opts, deps) {
    var fmt = deps.fmt;
    var pace = deps.pace;
    var title = metricTitle(catalog, family, metricId);
    var empty = {metricId: metricId, title: title, hasData: false, layout: "meter",
        headline: NO_DATA_HEADLINE, headlineTip: null, headlineToggle: false,
        trailing: NO_DATA, trailingTip: null, trailingToggle: false,
        meter: {fraction: 0, severity: null, tick: null, tip: null}, note: null,
        detail: "", detailTip: null, subtitle: "", points: [], chartNote: "",
        breakdown: null, resets: null, unknown: null, interactive: false};
    if (!hasDataFor(metric))
        return empty;
    var kind = metric.format && metric.format.kind ? metric.format.kind : "percent";
    var word = String(opts.display) === "Left" ? "left" : "used";
    var otherWord = word === "left" ? "used" : "left";
    var otherDisplay = word === "left" ? "Used" : "Left";
    var headline;
    var headlineTip;
    if (kind === "percent") {
        headline = _headlinePercent(metric, opts.display) + " " + word;
        headlineTip = _headlinePercent(metric, otherDisplay) + " " + otherWord;
    } else {
        headline = fmt.number(_shown(metric.used, metric.limit, opts.display), kind, "full") + " " + word;
        headlineTip = fmt.number(_shown(metric.used, metric.limit, otherDisplay), kind, "full") + " " + otherWord;
    }
    var signal = pace.sessionSignalFor(family, metricId);
    var fresh = pace.isFreshSession({sessionSignal: signal, hasData: true, used: metric.used,
        limit: metric.limit, resetsAt: metric.resetsAt, now: opts.now});
    var trailing = null;
    var trailingTip = null;
    var trailingToggle = false;
    if (fresh) {
        trailing = "Not started";
        trailingTip = FRESH_SESSION_TIP;
    } else if (metric.resetsAt) {
        trailing = String(fmt.normalizeResetMode(opts.resetMode)) === "absolute"
            ? fmt.resetAbsoluteLabel(metric.resetsAt, opts.now, opts.timeFormat)
            : fmt.resetRelativeLabel(metric.resetsAt, opts.now);
        trailingTip = String(fmt.normalizeResetMode(opts.resetMode)) === "absolute"
            ? fmt.resetRelativeLabel(metric.resetsAt, opts.now)
            : fmt.resetAbsoluteLabel(metric.resetsAt, opts.now, opts.timeFormat);
        trailingToggle = true;
    } else if (metric.periodMs) {
        var duration = fmt.compactDuration(Number(metric.periodMs) / 1000);
        trailing = duration ? "Resets in " + duration : null;
    } else if (kind === "dollars") {
        var limit = Number(metric.limit);
        trailing = fmt.currency(limit, limit === Math.round(limit) ? 0 : 2) + " limit";
    } else if (kind === "count") {
        trailing = metric.format && metric.format.suffix ? String(metric.format.suffix) : null;
    }
    var state = pace.meterState({hasData: true, used: metric.used, limit: metric.limit, kind: kind,
        resetsAt: metric.resetsAt, periodMs: metric.periodMs, now: opts.now,
        sessionSignal: signal});
    var rounded = pace.roundedAtPrecision(_shown(metric.used, metric.limit, opts.display), kind);
    var fraction = Math.min(1, Math.max(0, rounded / Number(metric.limit)));
    var severity = pace.severityOf(state);
    var tick = pace.paceTick({resetsAt: metric.resetsAt, periodMs: metric.periodMs,
        now: opts.now, display: opts.display, alwaysShowPacing: !!opts.alwaysShowPacing}, state);
    var tip = pace.tooltipOf(state);
    var note = null;
    if (state.kind === "spent") {
        note = {text: "Limit reached", tone: "flame", tip: tip, action: null};
    } else if (state.kind === "runningOut") {
        if (state.etaSec !== null && state.etaSec !== undefined) {
            var at = _ms(opts.now);
            var target = at === null ? Date.now() + state.etaSec * 1000 : at + state.etaSec * 1000;
            note = {text: fmt.deadlineLabel("Limit", target, opts.resetMode, opts.now, opts.timeFormat),
                tone: "flame", tip: tip, action: "toggleReset"};
        } else {
            note = {text: null, tone: "flame", tip: tip, action: null};
        }
    } else if (state.kind === "closeToLimit") {
        note = {text: state.spare, tone: "spare", tip: tip, action: null};
    } else if (state.kind === "healthy" && opts.alwaysShowPacing && tip) {
        note = {text: tip, tone: "projection", tip: null, action: null};
    }
    return {metricId: metricId, title: title, hasData: true, layout: "meter",
        headline: headline, headlineTip: headlineTip, headlineToggle: true,
        trailing: trailing, trailingTip: trailingTip, trailingToggle: trailingToggle,
        meter: {fraction: fraction, severity: severity, tick: tick, tip: tip}, note: note,
        detail: "", detailTip: null, subtitle: "", points: [], chartNote: "",
        breakdown: null, resets: null, unknown: null, interactive: false};
}
function _usagePeriod(catalog, family, metricId) {
    return Catalog.isSpend(catalog, family) && USAGE_PERIODS.indexOf(metricId) >= 0;
}
function _valuesDetail(values, word, fmt) {
    if (values.length === 1) {
        var single = values[0];
        if (single.kind === "dollars" && word)
            return fmt.number(single.number, "dollars", "row") + " " + word;
        return fmt.stringFor(single, "row");
    }
    return values.map(function(v) { return fmt.stringFor(v, "row"); }).join(" · ");
}
function _valuesTip(catalog, family, metricId, values, fmt) {
    var notes = [];
    var dollars = values.filter(function(v) { return v && v.kind === "dollars"; });
    if (dollars.some(function(v) { return !!v.estimated; }))
        notes.push(LOCAL_ESTIMATE_NOTE);
    if (family === "cursor" && _usagePeriod(catalog, family, metricId))
        notes.push(CURSOR_HISTORY_NOTE);
    var abbrev = values.some(function(v) { return v && Math.abs(Number(v.number)) >= 1000; });
    if (_usagePeriod(catalog, family, metricId) && values.length > 0
            && values.every(function(v) { return v && Number(v.number) === 0; }))
        return (["No usage in this period"].concat(notes)).join("\n");
    if (!abbrev && notes.length === 0)
        return null;
    var figures = abbrev ? values.map(function(v) { return fmt.stringFor(v, "full"); }).join(" · ") : null;
    return ([figures].concat(notes)).filter(function(x) { return !!x; }).join("\n");
}
function breakdownShares(models) {
    var list = Array.isArray(models) ? models : [];
    var allPriced = list.length > 0 && list.every(function(m) { return m && m.costUSD !== null && m.costUSD !== undefined; });
    if (allPriced) {
        var costTotal = list.reduce(function(sum, m) { return sum + Number(m.costUSD || 0); }, 0);
        if (costTotal > 0)
            return list.map(function(m) { return Math.min(1, Math.max(0, Number(m.costUSD || 0) / costTotal)); });
    }
    var tokenTotal = list.reduce(function(sum, m) { return sum + Number(m.totalTokens || 0); }, 0);
    if (!(tokenTotal > 0))
        return list.map(function() { return 0; });
    return list.map(function(m) { return Math.min(1, Math.max(0, Number(m.totalTokens || 0) / tokenTotal)); });
}
function wholePercents(shares) {
    var list = Array.isArray(shares) ? shares : [];
    if (!list.some(function(s) { return s > 0; }))
        return list.map(function() { return 0; });
    var raw = list.map(function(s) { return s * 100; });
    var out = raw.map(function(v) { return Math.floor(v); });
    var leftover = 100 - out.reduce(function(sum, v) { return sum + v; }, 0);
    if (!(leftover > 0))
        return out;
    var order = raw.map(function(v, i) { return i; }).sort(function(a, b) {
        var ra = raw[a] - Math.floor(raw[a]);
        var rb = raw[b] - Math.floor(raw[b]);
        if (ra !== rb)
            return rb - ra;
        return a - b;
    });
    for (var i = 0; i < order.length && leftover > 0; i++) {
        out[order[i]]++;
        leftover--;
    }
    return out;
}
function expiryEntries(expiries, now, fmt, pace, resetMode, timeFormat) {
    var list = Array.isArray(expiries) ? expiries.slice() : [];
    var moments = [];
    for (var i = 0; i < list.length; i++) {
        var ms = _ms(list[i]);
        if (ms !== null)
            moments.push({iso: list[i], ms: ms});
    }
    moments.sort(function(a, b) { return a.ms - b.ms; });
    var n = now === undefined ? Date.now() : _ms(now);
    return moments.map(function(entry) {
        var relative = fmt.whenLabel(entry.ms, "relative", n);
        var absolute = fmt.whenLabel(entry.ms, "absolute", n, timeFormat);
        var imminent = relative === null || relative === fmt.IMMINENT;
        var seconds = n === null ? Infinity : (entry.ms - n) / 1000;
        return {iso: entry.iso,
            time: (imminent || absolute === null) ? "Expiring soon" : absolute,
            countdown: imminent ? null : relative,
            severity: pace.expirySeverity(seconds)};
    });
}
function _breakdownFor(metric) {
    var raw = metric && metric.breakdown ? metric.breakdown : null;
    var models = raw && Array.isArray(raw.models) ? raw.models : [];
    if (models.length === 0)
        return null;
    var shares = breakdownShares(models);
    var percents = wholePercents(shares);
    return {models: models.map(function(m, i) {
        return {name: String(m.model || "Other"), cost: m.costUSD === undefined ? null : m.costUSD,
            tokens: Number(m.totalTokens || 0), share: shares[i], percent: percents[i]};
    }), note: raw.sourceNote ? String(raw.sourceNote) : ""};
}
function _resetsFor(family, metric) {
    if (!metric || !Array.isArray(metric.values) || metric.values.length === 0)
        return null;
    return {count: Math.max(0, Math.floor(Number(metric.values[0].number) || 0)),
        claimable: family === "codex"};
}
function _unknownFor(metric) {
    var names = metric && Array.isArray(metric.unknownModels) ? metric.unknownModels : [];
    if (names.length === 0)
        return null;
    var header = names.length === 1 ? "Unknown model found" : "Unknown models found";
    return {names: names.slice(), tip: ([header].concat(names.map(function(n) { return "- " + n; }))).join("\n")};
}
function _textRow(catalog, family, metricId, metric, opts, deps) {
    var fmt = deps.fmt;
    var pace = deps.pace;
    var title = metricTitle(catalog, family, metricId);
    var base = {metricId: metricId, title: title, hasData: false, layout: "text",
        headline: NO_DATA_HEADLINE, headlineTip: null, headlineToggle: false,
        trailing: null, trailingTip: null, trailingToggle: false, meter: null, note: null,
        detail: NO_DATA, detailTip: null, subtitle: "", points: [], chartNote: "",
        breakdown: null, resets: null, unknown: null, interactive: false};
    if (!metric || !hasDataFor(metric))
        return base;
    if (metric.type === "text")
        return Object.assign({}, base, {hasData: true, detail: String(metric.value),
            subtitle: metric.subtitle ? String(metric.subtitle) : ""});
    if (metric.type === "badge")
        return Object.assign({}, base, {hasData: true, detail: String(metric.text)});
    if (metric.type !== "values")
        return base;
    var values = metric.values;
    var word = VALUE_WORDS[family + "." + metricId] || null;
    var isResets = metricId === RESETS_METRIC;
    var breakdown = _usagePeriod(catalog, family, metricId) ? _breakdownFor(metric) : null;
    var resets = isResets ? _resetsFor(family, metric) : null;
    if (resets)
        resets.entries = expiryEntries(metric.expiriesAt, opts.now, fmt, pace, opts.resetMode, opts.timeFormat);
    var unknown = _usagePeriod(catalog, family, metricId) ? _unknownFor(metric) : null;
    var interactive = !!(breakdown || (resets && hasDataFor(metric)));
    return Object.assign({}, base, {hasData: true,
        detail: _valuesDetail(values, word, fmt),
        detailTip: (breakdown || resets) ? null : _valuesTip(catalog, family, metricId, values, fmt),
        breakdown: breakdown, resets: resets, unknown: unknown, interactive: interactive});
}
function _chartRow(catalog, family, metricId, metric) {
    var title = metricTitle(catalog, family, metricId);
    var base = {metricId: metricId, title: title, hasData: false, layout: "text",
        headline: NO_DATA_HEADLINE, headlineTip: null, headlineToggle: false,
        trailing: null, trailingTip: null, trailingToggle: false, meter: null, note: null,
        detail: NO_DATA, detailTip: null, subtitle: "", points: [], chartNote: "",
        breakdown: null, resets: null, unknown: null, interactive: false};
    if (!metric || !hasDataFor(metric))
        return base;
    return Object.assign({}, base, {hasData: true, layout: "chart",
        detail: "", points: metric.points.map(function(p) {
            return {label: String(p.label || ""), value: Number(p.value) || 0,
                readout: p.valueLabel ? String(p.valueLabel) : String(p.value)};
        }), chartNote: metric.note ? String(metric.note) : ""});
}
function rowModel(catalog, family, metricId, metric, opts, deps) {
    var def = metricDef(catalog, family, metricId);
    var kind = def ? def.kind : null;
    if (metric && metric.type === "chart")
        return _chartRow(catalog, family, metricId, metric);
    if (metric && metric.type === "progress")
        return _meterRow(catalog, family, metricId, metric, opts, deps);
    if (metric && (metric.type === "values" || metric.type === "text" || metric.type === "badge"))
        return _textRow(catalog, family, metricId, metric, opts, deps);
    if (!metric && kind === "progress")
        return _meterRow(catalog, family, metricId, null, opts, deps);
    if (!metric && kind === "chart")
        return _chartRow(catalog, family, metricId, null);
    return _textRow(catalog, family, metricId, null, opts, deps);
}
function condensedFlags(layouts) {
    var list = Array.isArray(layouts) ? layouts : [];
    var text = list.map(function(kind) { return kind !== "meter"; });
    return list.map(function(kind, i) { return i > 0 && text[i - 1] && text[i]; });
}
function sections(layout, catalog, state, opts, deps) {
    var fmt = deps.fmt;
    var out = [];
    var order = layout && Array.isArray(layout.order) ? layout.order : [];
    for (var i = 0; i < order.length; i++) {
        var cardId = order[i];
        var slot = layout.cards ? layout.cards[cardId] : null;
        if (!slot || !slot.enabled)
            continue;
        var family = Catalog.familyOf(cardId);
        var def = providerDef(catalog, family);
        if (!def)
            continue;
        var card = cardById(state, cardId);
        var metrics = card && card.metrics ? card.metrics : {};
        var split = deps.layout.displayMetrics(slot);
        var build = function(metricId) {
            return rowModel(catalog, family, metricId, metrics[metricId] || null, opts, deps);
        };
        var always = split.alwaysVisible.map(build);
        var expanded = split.onDemand.map(build);
        var flags = function(rows) {
            var marks = condensedFlags(rows.map(function(r) { return r.layout; }));
            for (var k = 0; k < rows.length; k++)
                rows[k].condensedTop = marks[k];
            return rows;
        };
        var links = Array.isArray(def.links) ? def.links : [];
        var refreshing = isRefreshing(state ? state.refresh : null, cardId);
        out.push({cardId: cardId, family: family,
            label: card && card.label ? String(card.label) : String(def.displayName || family),
            plan: card && card.plan ? String(card.plan) : null,
            refreshing: refreshing,
            warning: card && card.error && card.error.message ? String(card.error.message) : null,
            staleness: refreshing ? null : stalenessHint(card ? card.fetchedAt : null, opts.now, fmt),
            always: flags(always), expanded: flags(expanded), links: links,
            showCaret: expanded.length > 0 || links.length > 0,
            isExpanded: !!slot.expanded,
            lastClaim: card && card.lastClaim ? card.lastClaim : null});
    }
    return {sections: out, isEmpty: out.length === 0};
}
function spendVisible(layout, showTotalSpend, catalog) {
    if (!showTotalSpend || !layout)
        return false;
    var order = Array.isArray(layout.order) ? layout.order : [];
    for (var i = 0; i < order.length; i++) {
        var slot = layout.cards ? layout.cards[order[i]] : null;
        if (slot && slot.enabled && Catalog.isSpend(catalog, Catalog.familyOf(order[i])))
            return true;
    }
    return false;
}
function spendProviders(layout, catalog) {
    var out = [];
    var seen = {};
    var order = layout && Array.isArray(layout.order) ? layout.order : [];
    for (var i = 0; i < order.length; i++) {
        var family = Catalog.familyOf(order[i]);
        if (seen[family] || !Catalog.isSpend(catalog, family) || order[i] !== family)
            continue;
        var slot = layout.cards ? layout.cards[order[i]] : null;
        if (!slot || !slot.enabled)
            continue;
        var def = providerDef(catalog, family);
        seen[family] = true;
        out.push({id: family, displayName: def ? String(def.displayName || family) : family,
            spend: true});
    }
    return out;
}
function joinList(names) {
    var list = (Array.isArray(names) ? names : []).map(String);
    if (list.length === 0)
        return "";
    if (list.length === 1)
        return list[0];
    if (list.length === 2)
        return list[0] + " and " + list[1];
    return list.slice(0, -1).join(", ") + " and " + list[list.length - 1];
}
function spendInfoTip(providers) {
    var names = (Array.isArray(providers) ? providers : []).map(function(p) {
        return String(p.displayName || p.id);
    });
    return "Only includes " + joinList(names) + ".";
}
function updateBannerModel(state) {
    var update = state && state.update ? state.update : null;
    var version = state && state.daemon ? state.daemon.version : null;
    var latest = update ? update.latest : null;
    if (!latest || latest === version || latest === (update ? update.snoozed : null))
        return null;
    return {version: String(latest), installable: !!(update && update.installable)};
}
function footerModel(state, now) {
    var refresh = state && state.refresh ? state.refresh : null;
    var flight = refresh && Array.isArray(refresh.inFlight) ? refresh.inFlight : [];
    var version = state && state.daemon && state.daemon.version ? String(state.daemon.version) : "";
    if (flight.length > 0)
        return {version: version, updating: true, text: "Updating…"};
    var n = now === undefined ? Date.now() : _ms(now);
    var target = refresh ? _ms(refresh.nextAt) : null;
    if (target === null && refresh && refresh.lastBatchEndedAt) {
        var ended = _ms(refresh.lastBatchEndedAt);
        target = ended === null ? null : ended + STALE_AFTER_S * 500;
    }
    if (target === null || n === null)
        return {version: version, updating: false, text: "Next update in …"};
    var totalSeconds = Math.max(0, Math.ceil((target - n) / 1000));
    if (totalSeconds >= 60)
        return {version: version, updating: false, text: "Next update in " + Math.ceil(totalSeconds / 60) + "m"};
    return {version: version, updating: false, text: "Next update in " + totalSeconds + "s"};
}
function claimTone(status) {
    if (status === "ok")
        return "positive";
    if (status === "not_needed")
        return "info";
    if (status === "unavailable")
        return "warning";
    return "critical";
}
function claimReady(lastClaim, sinceMs) {
    if (!lastClaim || !lastClaim.at)
        return null;
    var at = _ms(lastClaim.at);
    if (at === null || at < Number(sinceMs))
        return null;
    return lastClaim;
}
function trendSummary(points) {
    var list = Array.isArray(points) ? points : [];
    if (list.length === 0)
        return null;
    var peak = list[0];
    for (var i = 1; i < list.length; i++)
        if (Number(list[i].value) > Number(peak.value))
            peak = list[i];
    return {count: list.length, first: String(list[0].label || ""),
        last: String(list[list.length - 1].label || ""),
        peakLabel: String(peak.label || ""), peakReadout: String(peak.readout || peak.value)};
}
function trendReadout(points, activeIndex) {
    var list = Array.isArray(points) ? points : [];
    if (activeIndex !== null && activeIndex !== undefined && list[activeIndex])
        return String(list[activeIndex].label || "") + " · " + String(list[activeIndex].readout || "");
    var summary = trendSummary(list);
    if (!summary)
        return "";
    return "peak " + summary.peakReadout;
}
function makeUuid() {
    var hex = "0123456789abcdef";
    var out = "";
    for (var i = 0; i < 36; i++) {
        if (i === 8 || i === 13 || i === 18 || i === 23) {
            out += "-";
            continue;
        }
        if (i === 14) {
            out += "4";
            continue;
        }
        var r = Math.floor(Math.random() * 16);
        out += i === 19 ? hex[8 + (r % 4)] : hex[r];
    }
    return out;
}
