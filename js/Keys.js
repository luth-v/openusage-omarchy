// Panel keys and the party-mode code. Plain letters work only with no
// text focus; Return and Esc move as upstream. Code is the Konami entry.
var CODE = ["up", "up", "down", "down", "left", "right", "left", "right", "b", "a"];
function panelAction(key, opts) {
    opts = opts || {};
    var name = String(key || "");
    var screen = String(opts.screen || "dashboard");
    var hasFocus = !!opts.hasFocus;
    if (name === "Escape" || name === "Esc") {
        if (screen === "dashboard")
            return "close";
        return "back";
    }
    if (name === "Return" || name === "Enter") {
        if (hasFocus)
            return null;
        if (screen === "dashboard")
            return "openCustomize";
        return "back";
    }
    if (hasFocus)
        return null;
    var lower = name.toLowerCase();
    if (lower === "z")
        return "undo";
    if (lower === "r")
        return "refresh";
    if (name === ",")
        return "settings";
    return null;
}
function createMatcher(target) {
    var want = Array.isArray(target) ? target.slice() : CODE.slice();
    var buffer = [];
    return {
        accept: function(token) {
            buffer.push(token);
            while (buffer.length > want.length)
                buffer.shift();
            if (buffer.length !== want.length)
                return false;
            for (var i = 0; i < want.length; i++) {
                if (buffer[i] !== want[i])
                    return false;
            }
            buffer = [];
            return true;
        },
        reset: function() {
            buffer = [];
        }
    };
}
