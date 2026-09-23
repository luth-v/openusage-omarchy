// Burn-rate pacing. Ports Support/Pace.swift and the WidgetData meter state.
// Pure; dates take Date, ms, or ISO. Eta stays in seconds; views format it.
var EXPIRY_WARNING_SEC = 7 * 24 * 60 * 60;
var EXPIRY_CRITICAL_SEC = 48 * 60 * 60;
function _isDate(x) {
    return Object.prototype.toString.call(x) === "[object Date]";
}
function _ms(x) {
    if (_isDate(x))
        return x.getTime();
    if (typeof x === "number")
        return x;
    if (typeof x === "string") {
        var t = new Date(x).getTime();
        return isNaN(t) ? null : t;
    }
    return null;
}
function minimumElapsed(periodSec) {
    var p = Number(periodSec);
    if (!isFinite(p) || p <= 0)
        return 60;
    return Math.max(60, p * 0.01);
}
function evaluate(used, limit, resetsAt, periodSec, now) {
    var u = Number(used);
    var l = Number(limit);
    var p = Number(periodSec);
    var r = _ms(resetsAt);
    var n = now === undefined ? Date.now() : _ms(now);
    if (!isFinite(u) || !isFinite(l) || !isFinite(p) || r === null || n === null)
        return null;
    if (!(l > 0 && p > 0 && u > 0))
        return null;
    var elapsed = (n - (r - p * 1000)) / 1000;
    if (!(elapsed >= minimumElapsed(p)) || !(n < r))
        return null;
    var projected = u / elapsed * p;
    if (u >= l)
        return {status: "behind", projectedUsage: projected};
    if (projected <= l * 0.9)
        return {status: "ahead", projectedUsage: projected};
    if (projected <= l)
        return {status: "onTrack", projectedUsage: projected};
    return {status: "behind", projectedUsage: projected};
}
function secondsToRunOut(used, limit, resetsAt, periodSec, now) {
    var result = evaluate(used, limit, resetsAt, periodSec, now);
    if (!result || result.status !== "behind")
        return null;
    var p = Number(periodSec);
    var rate = result.projectedUsage / p;
    if (!(rate > 0))
        return null;
    var eta = (Number(limit) - Number(used)) / rate;
    var r = _ms(resetsAt);
    var n = now === undefined ? Date.now() : _ms(now);
    if (r === null || n === null)
        return null;
    var remaining = (r - n) / 1000;
    if (!(eta > 0) || !(eta < remaining))
        return null;
    return eta;
}
function sessionSignalFor(family, metricId) {
    if (family === "claude" && metricId === "session")
        return "missingResetDate";
    if (family === "antigravity" && (metricId === "geminiPro" || metricId === "claude"))
        return "zeroUsage";
    if (family === "opencode" && metricId === "session")
        return "zeroUsage";
    return null;
}
function isFreshSession(opts) {
    opts = opts || {};
    if (!opts.sessionSignal || !opts.hasData)
        return false;
    if (opts.limit === null || opts.limit === undefined)
        return false;
    if (!(Number(opts.used) <= 0))
        return false;
    var r = opts.resetsAt === null || opts.resetsAt === undefined ? null : _ms(opts.resetsAt);
    if (opts.sessionSignal === "zeroUsage") {
        if (r === null)
            return false;
        var n = opts.now === undefined ? Date.now() : _ms(opts.now);
        return n !== null && n < r;
    }
    if (opts.sessionSignal === "missingResetDate")
        return r === null;
    return false;
}
function roundedAtPrecision(value, kind) {
    var v = Number(value);
    if (!isFinite(v))
        return 0;
    if (kind === "percent")
        return Math.round(v);
    if (kind === "count")
        return Math.round(v * 10) / 10;
    return Math.round(v * 100) / 100;
}
function _absoluteLevel(used, limit) {
    var frac = Math.min(1, Math.max(0, Number(used) / Number(limit)));
    var pct = Math.round(frac * 100);
    if (pct >= 90)
        return {kind: "level", severity: "critical"};
    if (pct >= 80)
        return {kind: "level", severity: "warning"};
    return {kind: "level", severity: "normal"};
}
function meterState(opts) {
    opts = opts || {};
    var hasData = opts.hasData !== false;
    var limit = opts.limit === undefined ? null : opts.limit;
    var used = Number(opts.used);
    if (!isFinite(used))
        used = 0;
    if (!hasData)
        return {kind: "noData"};
    if (!(limit !== null && limit !== undefined && Number(limit) > 0))
        return {kind: "level", severity: "normal"};
    var l = Number(limit);
    var kind = opts.kind || "percent";
    if (roundedAtPrecision(l - used, kind) <= 0)
        return {kind: "spent"};
    if (isFreshSession(opts))
        return _absoluteLevel(used, l);
    var periodMs = Number(opts.periodMs);
    var resetsAt = opts.resetsAt;
    if (resetsAt !== null && resetsAt !== undefined && isFinite(periodMs) && periodMs > 0) {
        var periodSec = periodMs / 1000;
        var result = evaluate(used, l, resetsAt, periodSec, opts.now);
        if (result) {
            var projected = result.projectedUsage / l;
            if (result.status === "ahead")
                return {kind: "healthy", projectedFraction: projected};
            if (result.status === "onTrack") {
                if (!(used / l >= 0.05))
                    return _absoluteLevel(used, l);
                var spare = Math.round((1 - projected) * 100);
                if (!(spare >= 1))
                    return {kind: "runningOut", etaSec: null, projectedFraction: projected};
                return {kind: "closeToLimit", spare: "~" + spare + "% spare", sparePct: spare, projectedFraction: projected};
            }
            if (!(used / l >= 0.05))
                return _absoluteLevel(used, l);
            var eta = secondsToRunOut(used, l, resetsAt, periodSec, opts.now);
            return {kind: "runningOut", etaSec: eta, projectedFraction: projected};
        }
    }
    return _absoluteLevel(used, l);
}
function severityOf(state) {
    if (!state)
        return null;
    if (state.kind === "noData")
        return null;
    if (state.kind === "spent" || state.kind === "runningOut")
        return "critical";
    if (state.kind === "closeToLimit")
        return "warning";
    if (state.kind === "healthy")
        return "normal";
    if (state.kind === "level")
        return state.severity || "normal";
    return null;
}
function tooltipOf(state) {
    if (!state)
        return null;
    if (state.kind === "noData" || state.kind === "level")
        return null;
    if (state.kind === "spent")
        return "Limit reached";
    var proj = Number(state.projectedFraction);
    if (!isFinite(proj))
        return null;
    if (state.kind === "healthy")
        return "~" + Math.round((1 - proj) * 100) + "% left at reset";
    if (state.kind === "closeToLimit")
        return "~" + Math.round(proj * 100) + "% used at reset";
    if (state.kind === "runningOut") {
        if (!(proj > 1))
            return "~100% used at reset";
        return "~" + Math.max(1, Math.round((proj - 1) * 100)) + "% over limit at reset";
    }
    return null;
}
function paceTick(opts, state) {
    opts = opts || {};
    if (!state)
        return null;
    if (state.kind === "spent" || state.kind === "noData" || state.kind === "level")
        return null;
    if (state.kind === "healthy" && !opts.alwaysShowPacing)
        return null;
    var r = opts.resetsAt === null || opts.resetsAt === undefined ? null : _ms(opts.resetsAt);
    var periodMs = Number(opts.periodMs);
    if (r === null || !isFinite(periodMs) || !(periodMs > 0))
        return null;
    var periodSec = periodMs / 1000;
    var n = opts.now === undefined ? Date.now() : _ms(opts.now);
    if (n === null || !(n < r))
        return null;
    var elapsed = (n - (r - periodSec * 1000)) / 1000;
    if (!(elapsed >= minimumElapsed(periodSec)))
        return null;
    var frac = Math.min(1, Math.max(0, elapsed / periodSec));
    return String(opts.display || "Used") === "Left" ? 1 - frac : frac;
}
function expirySeverity(secondsRemaining) {
    var s = Number(secondsRemaining);
    if (!isFinite(s))
        return "normal";
    if (s <= EXPIRY_CRITICAL_SEC)
        return "critical";
    if (s <= EXPIRY_WARNING_SEC)
        return "warning";
    return "normal";
}
