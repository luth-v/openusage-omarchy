// Total Spend view math. Ports TotalSpendAggregator and projection.
var PERIODS = {
    today: {key: "today", label: "Today", short: "Today", metricId: "today"},
    yesterday: {key: "yesterday", label: "Yesterday", short: "Yesterday", metricId: "yesterday"},
    last30: {key: "last30", label: "Last 30 Days", short: "30 Days", metricId: "last30"}
};
var METRICS = {
    cost: {key: "cost", title: "Cost", empty: "No cost data for this period", usesEstimate: true},
    costPerMtok: {key: "costPerMtok", title: "Cost/MTok", empty: "No cost-per-token data for this period", usesEstimate: true},
    tokens: {key: "tokens", title: "Tokens", empty: "No token data for this period", usesEstimate: false}
};
function costPerMtokFor(slice) {
    if (!slice || !(slice.amountUSD > 0) || !(slice.tokenCount > 0))
        return null;
    return slice.amountUSD / slice.tokenCount * 1000000;
}
function _spendOf(metric) {
    if (!metric || metric.type !== "values" || !Array.isArray(metric.values))
        return null;
    var amount = 0;
    var tokens = 0;
    var estimated = false;
    var hasDollars = false;
    for (var i = 0; i < metric.values.length; i++) {
        var v = metric.values[i];
        if (!v)
            continue;
        if (v.kind === "dollars") {
            hasDollars = true;
            amount += Number(v.number) || 0;
            if (v.estimated)
                estimated = true;
        } else if (v.kind === "count" && v.label === "tokens") {
            tokens += Number(v.number) || 0;
        }
    }
    if (!(amount > 0) && !(tokens > 0))
        return null;
    return {amountUSD: Math.max(0, amount), tokenCount: Math.max(0, tokens), estimated: hasDollars && estimated};
}
function totalFor(periodKey, cards, providers) {
    var period = PERIODS[periodKey] || PERIODS.today;
    var byCard = {};
    var list = Array.isArray(cards) ? cards : [];
    for (var i = 0; i < list.length; i++) {
        if (list[i] && list[i].cardId)
            byCard[list[i].cardId] = list[i];
    }
    var wanted = {};
    var ordered = [];
    if (Array.isArray(providers) && providers.length > 0) {
        for (i = 0; i < providers.length; i++) {
            var p = providers[i];
            var id = typeof p === "string" ? p : p && p.id;
            if (id && !wanted[id]) {
                wanted[id] = true;
                ordered.push(typeof p === "string" ? {id: id, displayName: id} : p);
            }
        }
    } else {
        ordered = [];
    }
    var slices = [];
    for (i = 0; i < ordered.length; i++) {
        var provider = ordered[i];
        if (provider.spend === false)
            continue;
        var card = byCard[provider.id];
        if (!card || !card.metrics)
            continue;
        var spend = _spendOf(card.metrics[period.metricId]);
        if (!spend)
            continue;
        slices.push({provider: provider, amountUSD: spend.amountUSD, tokenCount: spend.tokenCount, estimated: spend.estimated});
    }
    var totalUSD = 0;
    var totalTokens = 0;
    var isEstimated = false;
    for (i = 0; i < slices.length; i++) {
        totalUSD += slices[i].amountUSD;
        totalTokens += slices[i].tokenCount;
        if (slices[i].estimated)
            isEstimated = true;
    }
    return {period: period.key, slices: slices, totalUSD: totalUSD, totalTokens: totalTokens, isEstimated: isEstimated, isEmpty: slices.length === 0};
}
function projection(total, metricKey) {
    var key = METRICS[metricKey] ? metricKey : "cost";
    var slices = total && Array.isArray(total.slices) ? total.slices : [];
    var included = [];
    for (var i = 0; i < slices.length; i++) {
        var slice = slices[i];
        var display = null;
        if (key === "cost") {
            if (slice.amountUSD > 0)
                display = slice.amountUSD;
        } else if (key === "tokens") {
            if (slice.tokenCount > 0)
                display = slice.tokenCount;
        } else {
            display = costPerMtokFor(slice);
        }
        if (display !== null && display !== undefined)
            included.push({slice: slice, display: display});
    }
    included.sort(function(a, b) {
        if (a.display !== b.display)
            return b.display - a.display;
        var x = String(a.slice.provider.displayName || a.slice.provider.id);
        var y = String(b.slice.provider.displayName || b.slice.provider.id);
        return x < y ? -1 : x > y ? 1 : 0;
    });
    var projected = included.map(function(entry) {
        return {provider: entry.slice.provider, displayAmount: entry.display, estimated: !!entry.slice.estimated};
    });
    var center = 0;
    var estimated = false;
    if (key === "cost") {
        for (i = 0; i < included.length; i++) {
            center += included[i].slice.amountUSD;
            if (included[i].slice.estimated)
                estimated = true;
        }
    } else if (key === "tokens") {
        for (i = 0; i < included.length; i++)
            center += included[i].slice.tokenCount;
    } else {
        var usd = 0;
        var tokens = 0;
        for (i = 0; i < included.length; i++) {
            usd += included[i].slice.amountUSD;
            tokens += included[i].slice.tokenCount;
            if (included[i].slice.estimated)
                estimated = true;
        }
        center = tokens > 0 ? usd / tokens * 1000000 : 0;
    }
    return {metric: key, slices: projected, centerValue: center, isEstimated: estimated, isEmpty: projected.length === 0};
}
function emptyMessageFor(metricKey) {
    return METRICS[metricKey] ? METRICS[metricKey].empty : METRICS.cost.empty;
}
var MIN_SLICE_SHARE = 0.025;
function donutArcs(slices) {
    var list = Array.isArray(slices) ? slices : [];
    var total = 0;
    var i;
    for (i = 0; i < list.length; i++)
        total += Number(list[i].displayAmount) || 0;
    if (!(total > 0))
        return [];
    var floored = list.map(function(s) {
        return Math.max((Number(s.displayAmount) || 0) / total, MIN_SLICE_SHARE);
    });
    var sum = floored.reduce(function(a, b) { return a + b; }, 0);
    if (!(sum > 0))
        return [];
    var cursor = 0;
    return list.map(function(s, index) {
        var width = floored[index] / sum;
        var arc = {providerId: String(s.provider.id), start: cursor, end: cursor + width};
        cursor += width;
        return arc;
    });
}
function trendBars(points) {
    var list = Array.isArray(points) ? points : [];
    var max = 1;
    var i;
    for (i = 0; i < list.length; i++)
        max = Math.max(max, Number(list[i].value) || 0);
    return list.map(function(p) {
        var value = Number(p.value) || 0;
        return {label: String(p.label || ""), readout: String(p.readout || p.value),
            fraction: value <= 0 ? 0 : Math.max(0.18, Math.min(1, value / max))};
    });
}
