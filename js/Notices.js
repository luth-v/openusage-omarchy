// Transient pill copy and timeouts. Ports TransientNotice use in stores.
var TIMEOUTS = {pin: 3000, share: 2500, customize: 2500};
var MESSAGES = {
    starDenied: "Up to 2 stars per provider",
    starred: "Starred for menu bar",
    unstarred: "Removed from menu bar",
    copied: "Copied to clipboard"
};
function messageFor(kind) {
    return MESSAGES[String(kind)] || null;
}
function timeoutFor(surface) {
    var key = String(surface);
    if (key === "pin" || key === "share" || key === "customize")
        return TIMEOUTS[key];
    return TIMEOUTS.customize;
}
function toneFor(kind) {
    return String(kind) === "starDenied" ? "notice" : "positive";
}
