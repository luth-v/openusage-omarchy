// Number and time text. Ports MetricFormatter.swift and Formatters.swift.
// No Intl use: manual en_US group and compact so QML and node agree.
var IMMINENT = "soon";
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
function clampPercent(value) {
    var n = Number(value);
    if (!isFinite(n))
        return 0;
    return Math.min(100, Math.max(0, n));
}
function _groupInt(digits) {
    var out = "";
    var count = 0;
    for (var i = digits.length - 1; i >= 0; i--) {
        out = digits.charAt(i) + out;
        count++;
        if (count % 3 === 0 && i > 0)
            out = "," + out;
    }
    return out || "0";
}
function _grouped(value, fracDigits) {
    var neg = value < 0;
    var abs = Math.abs(value);
    var fixed = abs.toFixed(fracDigits);
    var parts = fixed.split(".");
    var head = _groupInt(parts[0]);
    var out = fracDigits > 0 ? head + "." + parts[1] : head;
    return neg ? "-" + out : out;
}
function _trim1(value) {
    var rounded = Math.round(Number(value) * 10) / 10;
    if (!isFinite(rounded) || rounded === 0)
        return "0";
    var neg = rounded < 0;
    var abs = Math.abs(rounded);
    if (abs === Math.round(abs))
        return (neg ? "-" : "") + _groupInt(String(Math.round(abs)));
    var fixed = abs.toFixed(1);
    var parts = fixed.split(".");
    return (neg ? "-" : "") + _groupInt(parts[0]) + "." + parts[1];
}
function _compact(value) {
    var abs = Math.abs(value);
    var neg = value < 0 ? "-" : "";
    var scaled = 0;
    var suffix = "";
    if (abs >= 1000000000) {
        scaled = abs / 1000000000;
        suffix = "B";
    } else if (abs >= 1000000) {
        scaled = abs / 1000000;
        suffix = "M";
    } else if (abs >= 1000) {
        scaled = abs / 1000;
        suffix = "K";
    } else {
        return _trim1(value);
    }
    var r1 = Math.round(scaled * 10) / 10;
    var head = r1 === Math.round(r1) ? String(Math.round(r1)) : r1.toFixed(1);
    return neg + head + suffix;
}
function currency(amount, fractionDigits) {
    var frac = fractionDigits === undefined ? 2 : fractionDigits;
    var n = Number(amount);
    if (!isFinite(n))
        n = 0;
    var neg = n < 0;
    var text = _grouped(Math.abs(n), frac);
    return neg ? "-$" + text : "$" + text;
}
function number(value, kind, style) {
    var n = Number(value);
    if (!isFinite(n))
        n = 0;
    if (kind === "percent")
        return String(Math.round(clampPercent(n))) + "%";
    if (kind === "dollars") {
        if (Math.abs(n) >= 1000 && style !== "full")
            return "$" + _compact(n);
        if (style === "tray")
            return (n < 0 ? "-$" : "$") + _groupInt(String(Math.abs(Math.round(n))));
        return currency(n, 2);
    }
    if (Math.abs(n) >= 1000 && style !== "full")
        return _compact(n);
    return _trim1(n);
}
function stringFor(valueObj, style) {
    var text = number(valueObj.number, valueObj.kind, style);
    var label = valueObj && valueObj.label ? String(valueObj.label) : "";
    if (!label)
        return text;
    return text + " " + label;
}
function costPerMtok(value, style) {
    return number(value, "dollars", style) + "/MTok";
}
function totalSpendRingCenter(value, metric) {
    var n = Number(value);
    if (!isFinite(n))
        n = 0;
    if (metric === "cost")
        return {primary: number(n, "dollars", "tray"), unit: "dollars"};
    if (metric === "costPerMtok") {
        var head = Math.abs(n) >= 1000 ? "$" + _compact(n) : currency(n, 2);
        return {primary: head, unit: "MTok"};
    }
    var abs = Math.abs(n);
    var scaled = n;
    var unit = "tokens";
    if (abs >= 1000000000) {
        scaled = n / 1000000000;
        unit = "billion";
    } else if (abs >= 1000000) {
        scaled = n / 1000000;
        unit = "million";
    } else if (abs >= 1000) {
        scaled = n / 1000;
        unit = "thousand";
    }
    return {primary: _trim1(scaled), unit: unit};
}
function compactDuration(seconds) {
    var s = Number(seconds);
    if (!isFinite(s) || s <= 0)
        return null;
    var totalMinutes = Math.max(1, Math.ceil(s / 60));
    var days = Math.floor(totalMinutes / 1440);
    var hours = Math.floor((totalMinutes % 1440) / 60);
    var minutes = totalMinutes % 60;
    if (days > 0)
        return days + "d " + hours + "h";
    if (hours > 0)
        return minutes > 0 ? hours + "h " + minutes + "m" : hours + "h";
    return minutes + "m";
}
function _isDate(x) {
    return Object.prototype.toString.call(x) === "[object Date]";
}
function _toDate(x) {
    if (_isDate(x))
        return x;
    if (typeof x === "number")
        return new Date(x);
    if (typeof x === "string") {
        var d = new Date(x);
        return isNaN(d.getTime()) ? null : d;
    }
    return null;
}
function monthDayLabel(date) {
    var d = _toDate(date);
    if (!d)
        return "";
    return MONTHS[d.getMonth()] + " " + d.getDate();
}
function _pad2(n) {
    return (n < 10 ? "0" : "") + n;
}
function shortTime(date, timeFormat) {
    var d = _toDate(date);
    if (!d)
        return "";
    var mode = String(timeFormat || "Auto");
    var use24 = mode === "24h" || mode === "24-hour";
    var h = d.getHours();
    var m = _pad2(d.getMinutes());
    if (use24)
        return _pad2(h) + ":" + m;
    var suffix = h < 12 ? "AM" : "PM";
    var h12 = h % 12 === 0 ? 12 : h % 12;
    return h12 + ":" + m + " " + suffix;
}
function normalizeResetMode(mode) {
    var s = String(mode || "relative").toLowerCase();
    if (s === "absolute" || s === "exact time" || s === "exact")
        return "absolute";
    return "relative";
}
function _startOfDay(d) {
    return new Date(d.getFullYear(), d.getMonth(), d.getDate());
}
function whenLabel(at, mode, now, timeFormat) {
    var target = _toDate(at);
    var ref = _toDate(now) || new Date();
    if (!target)
        return null;
    var kind = normalizeResetMode(mode);
    if (kind === "relative") {
        var seconds = (target.getTime() - ref.getTime()) / 1000;
        if (!isFinite(seconds))
            return null;
        if (seconds <= 300)
            return IMMINENT;
        return compactDuration(seconds);
    }
    if (target.getTime() - ref.getTime() <= 0)
        return IMMINENT;
    var dayDiff = Math.round((_startOfDay(target).getTime() - _startOfDay(ref).getTime()) / 86400000);
    var time = shortTime(target, timeFormat || "Auto");
    if (dayDiff <= 0)
        return "today at " + time;
    if (dayDiff === 1)
        return "tomorrow at " + time;
    return monthDayLabel(target) + " at " + time;
}
function deadlineLabel(prefix, at, mode, now, timeFormat) {
    var when = whenLabel(at, mode, now, timeFormat);
    if (!when)
        return null;
    if (when === IMMINENT)
        return String(prefix) + " " + when;
    if (normalizeResetMode(mode) === "relative")
        return String(prefix) + " in " + when;
    return String(prefix) + " " + when;
}
function resetRelativeLabel(until, now) {
    return deadlineLabel("Resets", until, "relative", now);
}
function resetAbsoluteLabel(at, now, timeFormat) {
    return deadlineLabel("Resets", at, "absolute", now, timeFormat);
}
