.import "Catalog.js" as Catalog
// Context-menu items and pick routing. Pure; node-tested. Builders emit
// {kind, id, label} rows for PopupMenu; menuAction maps a pick to a
// layout dispatch, a refresh, or a panel switch. Split from Dashboard.js
// to hold the file-size cap.
function menuStarState(catalog, layout, cardId, metricId) {
    var def = Catalog.metricDef(catalog, Catalog.familyOf(cardId), metricId);
    var slot = layout && layout.cards ? layout.cards[cardId] : null;
    var stars = slot && Array.isArray(slot.stars) ? slot.stars : [];
    return {starrable: !!(def && def.starrable), starred: stars.indexOf(metricId) >= 0};
}
function rowMenuItems(opts) {
    opts = opts || {};
    var items = [{kind: "item", id: "hide", label: "Hide"}];
    if (opts.starrable)
        items.push({kind: "item", id: opts.starred ? "unstar" : "star",
            label: opts.starred ? "Unstar" : "Star for menu bar"});
    items.push({kind: "divider"});
    items.push({kind: "item", id: "refresh", label: "Refresh " + String(opts.providerName || "")});
    items.push({kind: "item", id: "customize", label: "Customize…"});
    return items;
}
function headerMenuItems(opts) {
    opts = opts || {};
    return [{kind: "item", id: "hide", label: "Hide " + String(opts.providerName || "")},
        {kind: "divider"},
        {kind: "item", id: "refresh", label: "Refresh " + String(opts.providerName || "")},
        {kind: "item", id: "customize", label: "Customize…"},
        {kind: "divider"},
        {kind: "item", id: "share", label: "Share Screenshot"}];
}
function optionsMenuItems(opts) {
    opts = opts || {};
    var providers = Array.isArray(opts.providers) ? opts.providers : [];
    return [{kind: "item", id: "customize", label: "Customize"},
        {kind: "item", id: "settings", label: "Settings"},
        {kind: "divider"},
        {kind: "submenu", id: "share", label: "Share Screenshot",
            children: providers.map(function(p) {
                return {kind: "item", id: "share:" + p.cardId, label: String(p.label || p.cardId)};
            })},
        {kind: "item", id: "checkUpdates", label: "Check for Updates…"},
        {kind: "divider"},
        {kind: "item", id: "about", label: "About OpenUsage"}];
}
function menuAction(kind, id, anchor) {
    anchor = anchor || {};
    var cardId = anchor.cardId;
    var metricId = anchor.metricId;
    if (kind === "row") {
        if (id === "hide" && cardId && metricId)
            return {route: "dispatch", action: {type: "setMetricEnabled", cardId: cardId, metricId: metricId, enabled: false}};
        if ((id === "star" || id === "unstar") && cardId && metricId)
            return {route: "dispatch", action: {type: "toggleStar", cardId: cardId, metricId: metricId}};
        if (id === "refresh" && cardId)
            return {route: "refresh", cardId: cardId};
        if (id === "customize")
            return {route: "customize", cardId: cardId || null};
    } else if (kind === "header") {
        if (id === "hide" && cardId)
            return {route: "dispatch", action: {type: "setCardEnabled", cardId: cardId, enabled: false}};
        if (id === "refresh" && cardId)
            return {route: "refresh", cardId: cardId};
        if (id === "customize")
            return {route: "customize", cardId: cardId || null};
        if (id === "share" && cardId)
            return {route: "share", cardId: cardId};
    } else if (kind === "options") {
        if (id === "customize")
            return {route: "customize", cardId: null};
        if (id === "settings")
            return {route: "settings"};
        if (id === "checkUpdates")
            return {route: "checkUpdates"};
        if (id === "about")
            return {route: "about"};
        if (typeof id === "string" && id.indexOf("share:") === 0 && id.length > 6)
            return {route: "share", cardId: id.slice(6)};
    }
    return {route: "none"};
}
