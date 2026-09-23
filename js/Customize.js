// Customize view model. Pure; node-tested. Ports LayoutStore+Customization
// (provider rows, detail split) and the PopoverTopBar Reset All copy.
// Detail lists every metric the card supports, in metric order, split by
// section — even when the card is off (dimmed-but-editable, as upstream).
var RESET_ALL_TITLE = "Reset All Customization?";
var RESET_ALL_MESSAGE = "Turns providers back on for the tools you have installed and resets every provider's metrics and order. Are you sure?";
var RESET_ALL_CONFIRM = "Reset All";
var RESET_ALL_CANCEL = "Cancel";
var EMPTY_ZONE_TEXT = "Drag metrics here";
var STAR_LIMIT = 2;
function familyOf(cardId) {
    var cut = String(cardId).indexOf(":");
    return cut < 0 ? String(cardId) : String(cardId).slice(0, cut);
}
function providerDef(catalog, family) {
    var list = catalog && Array.isArray(catalog.providers) ? catalog.providers : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === family)
            return list[i];
    return null;
}
function stateLabel(state, cardId) {
    var list = state && Array.isArray(state.cards) ? state.cards : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].cardId === cardId && list[i].label)
            return String(list[i].label);
    return null;
}
function cardDisplayName(catalog, state, cardId) {
    var named = stateLabel(state, cardId);
    if (named)
        return named;
    var def = providerDef(catalog, familyOf(cardId));
    if (def && def.displayName)
        return String(def.displayName);
    return String(cardId);
}
// Every card in layout order, on or off: {cardId, family, displayName,
// enabled, metricCount}. The count is the catalog total, not the enabled
// count (LayoutStore.metricCount).
function providerRows(layout, catalog, state) {
    var order = layout && Array.isArray(layout.order) ? layout.order : [];
    var out = [];
    for (var i = 0; i < order.length; i++) {
        var cardId = order[i];
        var def = providerDef(catalog, familyOf(cardId));
        if (!def)
            continue;
        var slot = layout.cards ? layout.cards[cardId] : null;
        if (!slot)
            continue;
        var metrics = Array.isArray(def.metrics) ? def.metrics : [];
        out.push({cardId: cardId, family: familyOf(cardId),
            displayName: cardDisplayName(catalog, state, cardId),
            enabled: !!slot.enabled, metricCount: metrics.length});
    }
    return out;
}
function metricTitle(catalog, family, metricId) {
    var def = providerDef(catalog, family);
    var list = def && Array.isArray(def.metrics) ? def.metrics : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === metricId)
            return String(list[i].metricLabel || list[i].label || metricId);
    return String(metricId);
}
function metricStarrable(catalog, family, metricId) {
    var def = providerDef(catalog, family);
    var list = def && Array.isArray(def.metrics) ? def.metrics : [];
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === metricId)
            return list[i].starrable === true;
    return false;
}
// The detail for one card, or null when unknown. Rows carry their section,
// star state and on/off flag in metric order.
function detailFor(layout, catalog, cardId) {
    var def = providerDef(catalog, familyOf(cardId));
    var slot = layout && layout.cards ? layout.cards[cardId] : null;
    if (!def || !slot)
        return null;
    var known = {};
    var metrics = Array.isArray(def.metrics) ? def.metrics : [];
    for (var i = 0; i < metrics.length; i++)
        if (metrics[i] && metrics[i].id)
            known[metrics[i].id] = true;
    var off = {};
    var disabled = Array.isArray(slot.disabled) ? slot.disabled : [];
    for (var d = 0; d < disabled.length; d++)
        off[disabled[d]] = true;
    var alwaysSet = {};
    var always = Array.isArray(slot.alwaysVisible) ? slot.alwaysVisible : [];
    for (var a = 0; a < always.length; a++)
        alwaysSet[always[a]] = true;
    var stars = Array.isArray(slot.stars) ? slot.stars : [];
    var family = familyOf(cardId);
    var rows = [];
    var order = Array.isArray(slot.metricOrder) ? slot.metricOrder : [];
    for (var m = 0; m < order.length; m++) {
        var id = order[m];
        if (!known[id])
            continue;
        rows.push({metricId: id, title: metricTitle(catalog, family, id),
            starrable: metricStarrable(catalog, family, id),
            starred: stars.indexOf(id) >= 0, enabled: !off[id],
            always: !!alwaysSet[id]});
    }
    return {cardId: cardId, family: family,
        displayName: cardDisplayName(catalog, null, cardId),
        enabled: !!slot.enabled,
        always: rows.filter(function(r) { return r.always; }),
        onDemand: rows.filter(function(r) { return !r.always; })};
}
// True when a star tap would hit the per-provider cap, so the view can
// shake the star at once instead of waiting for the LayoutStore notice.
function starDeniedPreview(stars, metricId, starrable) {
    var list = Array.isArray(stars) ? stars : [];
    if (!starrable || list.indexOf(metricId) >= 0)
        return false;
    return list.length >= STAR_LIMIT;
}
// Presence-only hint for the API Key section (never a value).
function keyStatusText(source) {
    switch (String(source || "none")) {
    case "keyring": return "Saved in keyring";
    case "file": return "Saved in file";
    case "env": return "From your environment";
    default: return "";
    }
}
function keyStatusSet(source) {
    return String(source || "none") !== "none";
}
