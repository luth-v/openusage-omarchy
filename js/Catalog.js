// Pure helpers over catalog.json. No I/O. Node-tested.
var SCHEMA = "openusage-omarchy.catalog.v1";
function providers(catalog) {
    if (!catalog || !catalog.providers || !Array.isArray(catalog.providers))
        return [];
    return catalog.providers;
}
function providerIds(catalog) {
    return providers(catalog).map(function(p) { return p.id; });
}
function provider(catalog, id) {
    var list = providers(catalog);
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === id)
            return list[i];
    return null;
}
function metricsFor(catalog, family) {
    var p = provider(catalog, family);
    if (!p || !Array.isArray(p.metrics))
        return [];
    return p.metrics;
}
function metricDef(catalog, family, metricId) {
    var list = metricsFor(catalog, family);
    for (var i = 0; i < list.length; i++)
        if (list[i] && list[i].id === metricId)
            return list[i];
    return null;
}
function familyOf(cardId) {
    if (typeof cardId !== "string")
        return "";
    var cut = cardId.indexOf(":");
    return cut < 0 ? cardId : cardId.slice(0, cut);
}
function spendFamilies(catalog) {
    return providers(catalog).filter(function(p) { return p.spend === true; })
        .map(function(p) { return p.id; });
}
function isSpend(catalog, family) {
    var p = provider(catalog, family);
    return !!p && p.spend === true;
}
function allMetricIds(catalog, family) {
    return metricsFor(catalog, family).map(function(m) { return m.id; });
}
function defaultStars(catalog, family) {
    return metricsFor(catalog, family).filter(function(m) {
        return m && m.defaultStar && m.starrable;
    }).map(function(m) { return m.id; }).slice(0, 2);
}
function defaultDisabled(catalog, family) {
    return metricsFor(catalog, family).filter(function(m) {
        return m && m.defaultOn === false;
    }).map(function(m) { return m.id; });
}
function defaultAlwaysVisible(catalog, family) {
    return metricsFor(catalog, family).filter(function(m) {
        return m && m.placement === "alwaysVisible";
    }).map(function(m) { return m.id; });
}
function displayName(catalog, family) {
    var p = provider(catalog, family);
    return p ? String(p.displayName || family) : String(family);
}
function metricLabelFor(catalog, family, metricId) {
    var def = metricDef(catalog, family, metricId);
    if (!def)
        return String(metricId);
    return String(def.metricLabel || def.label || metricId);
}
function isStarrable(catalog, family, metricId) {
    var def = metricDef(catalog, family, metricId);
    return !!def && def.starrable === true;
}
