// Customize layout model. Pure reducer plus defaults, merge, and undo.
// Schema: {schema, order:[cardId], cards:{cardId:{enabled,metricOrder,
// disabled,alwaysVisible,stars,expanded}}, spend:{period,metric},
// firstRunCompleted}. metricOrder
// holds all known metrics; disabled tracks off; alwaysVisible tracks section.
var SCHEMA = "openusage-omarchy.layout.v1";
var STAR_LIMIT = 2;
var UNDO_LIMIT = 40;
var STARTER_SET = ["claude", "codex", "cursor"];
var SPEND_PERIODS = ["today", "yesterday", "last30"];
var SPEND_METRICS = ["cost", "costPerMtok", "tokens"];
function normalizeSpend(raw) {
    var period = raw && typeof raw.period === "string" ? raw.period : "today";
    var metric = raw && typeof raw.metric === "string" ? raw.metric : "cost";
    if (SPEND_PERIODS.indexOf(period) < 0)
        period = "today";
    if (SPEND_METRICS.indexOf(metric) < 0)
        metric = "cost";
    return {period: period, metric: metric};
}
function familyOf(cardId) {
    if (typeof cardId !== "string")
        return "";
    var cut = cardId.indexOf(":");
    return cut < 0 ? cardId : cardId.slice(0, cut);
}
function clone(obj) {
    return JSON.parse(JSON.stringify(obj));
}
function _providers(catalog) {
    if (!catalog || !Array.isArray(catalog.providers))
        return [];
    return catalog.providers;
}
function _provider(catalog, family) {
    var list = _providers(catalog);
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === family)
            return list[i];
    return null;
}
function _metrics(def) {
    return def && Array.isArray(def.metrics) ? def.metrics : [];
}
function _cardDefaults(def) {
    var metrics = _metrics(def);
    var order = [];
    var disabled = [];
    var always = [];
    var stars = [];
    for (var i = 0; i < metrics.length; i++) {
        var m = metrics[i];
        if (!m || !m.id)
            continue;
        order.push(m.id);
        if (m.defaultOn === false)
            disabled.push(m.id);
        if (m.placement === "alwaysVisible")
            always.push(m.id);
        if (m.defaultStar && m.starrable && stars.length < STAR_LIMIT)
            stars.push(m.id);
    }
    return {metricOrder: order, disabled: disabled, alwaysVisible: always, stars: stars};
}
function defaults(catalog, detected) {
    var list = _providers(catalog);
    var order = [];
    var cards = {};
    var useDetected = detected && typeof detected === "object";
    var anyDetected = false;
    if (useDetected) {
        for (var i = 0; i < list.length; i++) {
            var p = list[i];
            if (p && detected[p.id] && p.autoEnable !== false)
                anyDetected = true;
        }
    }
    for (var k = 0; k < list.length; k++) {
        var def = list[k];
        if (!def || !def.id)
            continue;
        order.push(def.id);
        var base = _cardDefaults(def);
        var enabled;
        if (useDetected && anyDetected)
            enabled = !!detected[def.id] && def.autoEnable !== false;
        else if (useDetected && !anyDetected)
            enabled = STARTER_SET.indexOf(def.id) >= 0;
        else
            enabled = STARTER_SET.indexOf(def.id) >= 0;
        if (def.id === "ollama")
            enabled = false;
        cards[def.id] = {enabled: enabled, metricOrder: base.metricOrder, disabled: base.disabled, alwaysVisible: base.alwaysVisible, stars: base.stars, expanded: false};
    }
    return {schema: SCHEMA, order: order, cards: cards, spend: {period: "today", metric: "cost"}, firstRunCompleted: !!useDetected, hintDismissed: false};
}
function normalizedMetricIds(saved, validIds) {
    var valid = {};
    var i;
    for (i = 0; i < validIds.length; i++)
        valid[validIds[i]] = true;
    var seen = {};
    var out = [];
    if (Array.isArray(saved)) {
        for (i = 0; i < saved.length; i++) {
            if (valid[saved[i]] && !seen[saved[i]]) {
                seen[saved[i]] = true;
                out.push(saved[i]);
            }
        }
    }
    for (i = 0; i < validIds.length; i++) {
        if (!seen[validIds[i]])
            out.push(validIds[i]);
    }
    return out;
}
function _filterIds(ids, validSet) {
    var out = [];
    if (!Array.isArray(ids))
        return out;
    var seen = {};
    for (var i = 0; i < ids.length; i++) {
        if (validSet[ids[i]] && !seen[ids[i]]) {
            seen[ids[i]] = true;
            out.push(ids[i]);
        }
    }
    return out;
}
function _normalizeCard(raw, def, detected) {
    var metrics = _metrics(def);
    var validIds = metrics.map(function(m) { return m.id; });
    var validSet = {};
    var i;
    for (i = 0; i < validIds.length; i++)
        validSet[validIds[i]] = true;
    var known = {};
    if (raw && Array.isArray(raw.metricOrder)) {
        for (i = 0; i < raw.metricOrder.length; i++)
            known[raw.metricOrder[i]] = true;
    }
    var order = normalizedMetricIds(raw ? raw.metricOrder : [], validIds);
    var disabled = _filterIds(raw ? raw.disabled : [], validSet);
    var always = _filterIds(raw ? raw.alwaysVisible : [], validSet);
    var stars = [];
    var starSeen = {};
    if (raw && Array.isArray(raw.stars)) {
        for (i = 0; i < raw.stars.length; i++) {
            var id = raw.stars[i];
            if (validSet[id] && !starSeen[id] && stars.length < STAR_LIMIT)
                stars.push(id);
            starSeen[id] = true;
        }
    }
    var starrable = {};
    for (i = 0; i < metrics.length; i++)
        if (metrics[i] && metrics[i].starrable)
            starrable[metrics[i].id] = true;
    stars = stars.filter(function(id) { return starrable[id]; });
    for (i = 0; i < metrics.length; i++) {
        var m = metrics[i];
        if (!m || known[m.id] || !validSet[m.id])
            continue;
        if (m.defaultOn === false && disabled.indexOf(m.id) < 0)
            disabled.push(m.id);
        if (m.placement === "alwaysVisible") {
            if (always.indexOf(m.id) < 0)
                always.push(m.id);
        } else {
            var cut = always.indexOf(m.id);
            if (cut >= 0)
                always.splice(cut, 1);
        }
    }
    var enabled = !!(raw && raw.enabled);
    if (!raw && detected && typeof detected === "object")
        enabled = !!detected[def.id] && def.autoEnable !== false;
    if (def.id === "ollama" && !raw)
        enabled = false;
    return {enabled: enabled, metricOrder: order, disabled: disabled, alwaysVisible: always, stars: stars, expanded: !!(raw && raw.expanded)};
}
function parse(raw) {
    try {
        var data = typeof raw === "string" ? JSON.parse(raw) : raw;
        return data && typeof data === "object" ? data : null;
    } catch (_) {
        return null;
    }
}
function migrate(raw) {
    if (!raw || typeof raw !== "object")
        return null;
    if (raw.schema !== SCHEMA)
        return null;
    var out = clone(raw);
    if (!Array.isArray(out.order))
        out.order = [];
    if (!out.cards || typeof out.cards !== "object")
        out.cards = {};
    out.firstRunCompleted = !!out.firstRunCompleted;
    out.spend = normalizeSpend(out.spend);
    return out;
}
function merge(stored, catalog, detected) {
    var list = _providers(catalog);
    var byId = {};
    var i;
    for (i = 0; i < list.length; i++)
        if (list[i] && list[i].id)
            byId[list[i].id] = list[i];
    if (!stored || typeof stored !== "object")
        return defaults(catalog, detected && typeof detected === "object" ? detected : null);
    var base = migrate(stored) || defaults(catalog, null);
    var order = [];
    var seen = {};
    for (i = 0; i < base.order.length; i++) {
        var id = base.order[i];
        var fam = familyOf(id);
        if (byId[fam] && !seen[id]) {
            seen[id] = true;
            order.push(id);
        }
    }
    for (i = 0; i < list.length; i++) {
        if (list[i] && !seen[list[i].id]) {
            seen[list[i].id] = true;
            order.push(list[i].id);
        }
    }
    for (var key in base.cards) {
        if (base.cards.hasOwnProperty(key) && byId[familyOf(key)] && !seen[key]) {
            seen[key] = true;
            order.push(key);
        }
    }
    var cards = {};
    for (i = 0; i < order.length; i++) {
        var cardId = order[i];
        var family = familyOf(cardId);
        cards[cardId] = _normalizeCard(base.cards[cardId] || null, byId[family], detected);
        if (base.cards[cardId] && typeof base.cards[cardId].enabled === "boolean")
            cards[cardId].enabled = !!base.cards[cardId].enabled;
    }
    var hintDismissed = base.hintDismissed;
    if (hintDismissed !== true && hintDismissed !== false)
        hintDismissed = !!base.firstRunCompleted;
    return {schema: SCHEMA, order: order, cards: cards, spend: normalizeSpend(base.spend), firstRunCompleted: !!base.firstRunCompleted, hintDismissed: hintDismissed};
}
function ensureCards(layout, catalog, cardIds) {
    if (!layout || !Array.isArray(cardIds))
        return layout;
    var next = clone(layout);
    var changed = false;
    for (var i = 0; i < cardIds.length; i++) {
        var cardId = cardIds[i];
        if (typeof cardId !== "string" || next.cards[cardId])
            continue;
        var family = familyOf(cardId);
        var def = _provider(catalog, family);
        if (!def)
            continue;
        var base = next.cards[family];
        if (base) {
            next.cards[cardId] = {enabled: !!base.enabled, metricOrder: base.metricOrder.slice(), disabled: (base.disabled || []).slice(), alwaysVisible: (base.alwaysVisible || []).slice(), stars: (base.stars || []).slice(), expanded: false};
        } else {
            var d = _cardDefaults(def);
            next.cards[cardId] = {enabled: false, metricOrder: d.metricOrder, disabled: d.disabled, alwaysVisible: d.alwaysVisible, stars: d.stars, expanded: false};
        }
        // New Accounts go right after their family's existing cards, so a
        // second config dir never reorders what the user already arranged.
        var at = -1;
        for (var k = 0; k < next.order.length; k++)
            if (familyOf(next.order[k]) === family)
                at = k;
        if (at >= 0)
            next.order.splice(at + 1, 0, cardId);
        else
            next.order.push(cardId);
        changed = true;
    }
    return changed ? next : layout;
}
function firstRunComplete(layout, catalog, detected) {
    if (!layout || layout.firstRunCompleted || !detected || typeof detected !== "object")
        return layout;
    var fresh = defaults(catalog, detected);
    var next = clone(layout);
    for (var i = 0; i < fresh.order.length; i++) {
        var id = fresh.order[i];
        if (next.cards[id])
            next.cards[id].enabled = !!(fresh.cards[id] && fresh.cards[id].enabled);
    }
    next.firstRunCompleted = true;
    return next;
}
function reordered(ids, dragged, target) {
    if (dragged === target)
        return null;
    var from = ids.indexOf(dragged);
    var to = ids.indexOf(target);
    if (from < 0 || to < 0)
        return null;
    var next = ids.slice();
    next.splice(from, 1);
    var adjusted = next.indexOf(target);
    if (adjusted < 0)
        return null;
    next.splice(from < to ? adjusted + 1 : adjusted, 0, dragged);
    return next;
}
function _ok(layout, notice, undoable, clearUndo) {
    return {layout: layout, notice: notice || null, undoable: undoable !== false, clearUndo: !!clearUndo};
}
function reduce(layout, action, catalog) {
    if (!layout || !action || typeof action.type !== "string")
        return _ok(layout, null, false);
    var type = action.type;
    if (type === "moveProvider") {
        var nextOrder = reordered(layout.order || [], action.dragged, action.target);
        if (!nextOrder)
            return _ok(layout, null, false);
        var moved = clone(layout);
        moved.order = nextOrder;
        return _ok(moved, null, true);
    }
    if (type === "setCardEnabled") {
        var card = layout.cards[action.cardId];
        if (!card || !!card.enabled === !!action.enabled)
            return _ok(layout, null, false);
        var toggled = clone(layout);
        toggled.cards[action.cardId].enabled = !!action.enabled;
        return _ok(toggled, null, true);
    }
    if (type === "setExpanded") {
        var exp = layout.cards[action.cardId];
        if (!exp || !!exp.expanded === !!action.expanded)
            return _ok(layout, null, false);
        var swapped = clone(layout);
        swapped.cards[action.cardId].expanded = !!action.expanded;
        return _ok(swapped, null, false);
    }
    if (type === "setMetricEnabled") {
        var host = layout.cards[action.cardId];
        if (!host || host.metricOrder.indexOf(action.metricId) < 0)
            return _ok(layout, null, false);
        var off = (host.disabled || []).indexOf(action.metricId) >= 0;
        if (!!action.enabled === !off)
            return _ok(layout, null, false);
        var flipped = clone(layout);
        var list = flipped.cards[action.cardId].disabled || [];
        if (action.enabled)
            flipped.cards[action.cardId].disabled = list.filter(function(id) { return id !== action.metricId; });
        else if (list.indexOf(action.metricId) < 0)
            list.push(action.metricId);
        return _ok(flipped, null, true);
    }
    if (type === "setMetricSection") {
        var section = layout.cards[action.cardId];
        if (!section || section.metricOrder.indexOf(action.metricId) < 0)
            return _ok(layout, null, false);
        var wantAlways = action.section === "alwaysVisible";
        var isAlways = (section.alwaysVisible || []).indexOf(action.metricId) >= 0;
        if (wantAlways === isAlways)
            return _ok(layout, null, false);
        var reSectioned = clone(layout);
        var always = reSectioned.cards[action.cardId].alwaysVisible || [];
        if (wantAlways)
            always.push(action.metricId);
        else
            reSectioned.cards[action.cardId].alwaysVisible = always.filter(function(id) { return id !== action.metricId; });
        return _ok(reSectioned, null, true);
    }
    if (type === "moveMetric") {
        var mhost = layout.cards[action.cardId];
        if (!mhost)
            return _ok(layout, null, false);
        var morder = mhost.metricOrder || [];
        if (morder.indexOf(action.dragged) < 0 || morder.indexOf(action.target) < 0)
            return _ok(layout, null, false);
        if (action.dragged === action.target)
            return _ok(layout, null, false);
        var alwaysSet = {};
        var i;
        for (i = 0; i < (mhost.alwaysVisible || []).length; i++)
            alwaysSet[mhost.alwaysVisible[i]] = true;
        var targetAlways = !!alwaysSet[action.target];
        var nextAlways = (mhost.alwaysVisible || []).slice();
        var hasDragged = !!alwaysSet[action.dragged];
        if (targetAlways && !hasDragged)
            nextAlways.push(action.dragged);
        else if (!targetAlways && hasDragged)
            nextAlways = nextAlways.filter(function(id) { return id !== action.dragged; });
        var partitioned = morder.filter(function(id) { return nextAlways.indexOf(id) >= 0; }).concat(morder.filter(function(id) { return nextAlways.indexOf(id) < 0; }));
        var movedMetric = reordered(partitioned, action.dragged, action.target) || partitioned;
        var memberChanged = (nextAlways.indexOf(action.dragged) >= 0) !== hasDragged;
        var orderChanged = JSON.stringify(movedMetric) !== JSON.stringify(morder);
        if (!memberChanged && !orderChanged)
            return _ok(layout, null, false);
        var reorderedLayout = clone(layout);
        reorderedLayout.cards[action.cardId].metricOrder = movedMetric;
        reorderedLayout.cards[action.cardId].alwaysVisible = nextAlways;
        return _ok(reorderedLayout, null, true);
    }
    if (type === "setStar" || type === "toggleStar") {
        var shost = layout.cards[action.cardId];
        if (!shost)
            return _ok(layout, null, false);
        var family = familyOf(action.cardId);
        var def = null;
        var metrics = [];
        if (catalog) {
            var p = _provider(catalog, family);
            metrics = _metrics(p);
            for (var k = 0; k < metrics.length; k++)
                if (metrics[k] && metrics[k].id === action.metricId)
                    def = metrics[k];
        }
        if (catalog && !def)
            return _ok(layout, null, false);
        var stars = shost.stars || [];
        var has = stars.indexOf(action.metricId) >= 0;
        var want = type === "toggleStar" ? !has : !!action.starred;
        if (want === has)
            return _ok(layout, null, false);
        if (want) {
            if (def && !def.starrable)
                return _ok(layout, null, false);
            if (stars.length >= STAR_LIMIT)
                return _ok(layout, {kind: "starDenied"}, false);
            var added = clone(layout);
            var list2 = added.cards[action.cardId].stars || [];
            list2.push(action.metricId);
            var rank = {};
            var mo = added.cards[action.cardId].metricOrder || [];
            for (var r = 0; r < mo.length; r++)
                rank[mo[r]] = r;
            list2.sort(function(a, b) { return (rank[a] === undefined ? 999 : rank[a]) - (rank[b] === undefined ? 999 : rank[b]); });
            return _ok(added, null, true);
        }
        var removed = clone(layout);
        removed.cards[action.cardId].stars = (removed.cards[action.cardId].stars || []).filter(function(id) { return id !== action.metricId; });
        return _ok(removed, null, true);
    }
    if (type === "resetProvider") {
        var rhost = layout.cards[action.cardId];
        if (!rhost)
            return _ok(layout, null, false);
        var rdef = catalog ? _provider(catalog, familyOf(action.cardId)) : null;
        if (!rdef)
            return _ok(layout, null, false);
        var base = _cardDefaults(rdef);
        var reset = clone(layout);
        reset.cards[action.cardId] = {enabled: !!rhost.enabled, metricOrder: base.metricOrder, disabled: base.disabled, alwaysVisible: base.alwaysVisible, stars: base.stars, expanded: false};
        return _ok(reset, null, true, true);
    }
    if (type === "resetAll") {
        var fresh2 = defaults(catalog, action.detected && typeof action.detected === "object" ? action.detected : null);
        if (!action.detected)
            fresh2.firstRunCompleted = !!layout.firstRunCompleted;
        fresh2.hintDismissed = layout.hintDismissed === false ? false : true;
        fresh2.spend = normalizeSpend(layout.spend);
        return _ok(fresh2, null, true, true);
    }
    if (type === "setSpend") {
        var current = normalizeSpend(layout.spend);
        var period = typeof action.period === "string" ? action.period : current.period;
        var metric = typeof action.metric === "string" ? action.metric : current.metric;
        if (SPEND_PERIODS.indexOf(period) < 0)
            period = current.period;
        if (SPEND_METRICS.indexOf(metric) < 0)
            metric = current.metric;
        if (period === current.period && metric === current.metric)
            return _ok(layout, null, false);
        var spendNext = clone(layout);
        spendNext.spend = {period: period, metric: metric};
        return _ok(spendNext, null, false);
    }
    if (type === "dismissHint") {
        if (layout.hintDismissed)
            return _ok(layout, null, false);
        var hinted = clone(layout);
        hinted.hintDismissed = true;
        return _ok(hinted, null, false);
    }
    if (type === "completeFirstRun")
        return _ok(firstRunComplete(layout, catalog, action.detected), null, false);
    if (type === "ensureCards")
        return _ok(ensureCards(layout, catalog, action.cardIds), null, false);
    return _ok(layout, null, false);
}
function enabledMetrics(card) {
    if (!card)
        return [];
    var off = {};
    var disabled = card.disabled || [];
    for (var i = 0; i < disabled.length; i++)
        off[disabled[i]] = true;
    return (card.metricOrder || []).filter(function(id) { return !off[id]; });
}
function displayMetrics(card) {
    var enabled = enabledMetrics(card);
    var alwaysSet = {};
    var always = card ? card.alwaysVisible || [] : [];
    for (var i = 0; i < always.length; i++)
        alwaysSet[always[i]] = true;
    var top = enabled.filter(function(id) { return alwaysSet[id]; });
    var rest = enabled.filter(function(id) { return !alwaysSet[id]; });
    if (top.length === 0 && rest.length > 0)
        return {alwaysVisible: rest, onDemand: []};
    return {alwaysVisible: top, onDemand: rest};
}
function pushHistory(stack, snapshot) {
    var next = (Array.isArray(stack) ? stack.slice() : []);
    next.push(clone(snapshot));
    while (next.length > UNDO_LIMIT)
        next.shift();
    return next;
}
function popHistory(stack) {
    var next = (Array.isArray(stack) ? stack.slice() : []);
    var snapshot = next.length > 0 ? next.pop() : null;
    return {stack: next, snapshot: snapshot};
}
function canUndo(stack) {
    return Array.isArray(stack) && stack.length > 0;
}
