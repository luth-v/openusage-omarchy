// Drag-reorder hit test. Pure; node-tested. Views collect row geometries
// ({id, top, bottom} in one coordinate space) and call dropTarget on
// release; the result feeds Layout.reduce moveProvider/moveMetric, whose
// adjacency rule (after the target when dragging down, before when
// dragging up) places the row. Zones locate empty-section drop targets.
function rowAt(rows, y) {
    var list = Array.isArray(rows) ? rows : [];
    for (var i = 0; i < list.length; i++) {
        var row = list[i];
        if (row && y >= row.top && y < row.bottom)
            return row.id;
    }
    return null;
}
function dropTarget(rows, y, draggedId) {
    var list = (Array.isArray(rows) ? rows : []).filter(function(row) {
        return row && row.id !== draggedId;
    });
    if (list.length === 0)
        return null;
    var hit = rowAt(list, y);
    if (hit)
        return hit;
    if (y < list[0].top)
        return list[0].id;
    return list[list.length - 1].id;
}
function zoneAt(zones, y) {
    var list = Array.isArray(zones) ? zones : [];
    for (var i = 0; i < list.length; i++) {
        var zone = list[i];
        if (zone && y >= zone.top && y < zone.bottom)
            return zone.id;
    }
    return null;
}
