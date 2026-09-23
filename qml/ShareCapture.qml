import QtQuick
import Quickshell
import Quickshell.Io

// Share Screenshot: grab an item, write a 0600 PNG under the runtime dir,
// copy it with wl-copy, then delete the temp file. Emits done(ok); a
// clipboard write gives no other signal that it landed.
Item {
    id: root
    signal done(bool ok)
    property var pendingItem: null
    function runtimeDir() {
        var base = Quickshell.env("XDG_RUNTIME_DIR");
        if (!base)
            base = "/tmp";
        return base + "/openusage-omarchy-share";
    }
    function capture(item) {
        if (!item || typeof item.grabToImage !== "function") {
            root.done(false);
            return;
        }
        root.pendingItem = item;
        mkdirProc.command = ["mkdir", "-p", root.runtimeDir()];
        mkdirProc.running = true;
    }
    function grabNow(item) {
        if (!item) {
            root.done(false);
            return;
        }
        item.grabToImage(function(result) {
            root.pendingItem = null;
            if (!result) {
                root.done(false);
                return;
            }
            var path = root.runtimeDir() + "/share-" + Date.now() + ".png";
            var saved = false;
            try {
                saved = result.saveToFile(path);
            } catch (_) {
                saved = false;
            }
            if (!saved) {
                root.done(false);
                return;
            }
            copyProc.command = ["sh", "-c", "chmod 600 \"$1\" 2>/dev/null; wl-copy --type image/png < \"$1\"; rc=$?; rm -f \"$1\"; exit $rc", "sh", path];
            copyProc.running = true;
        });
    }
    Process {
        id: mkdirProc
        onExited: function(code, status) {
            running = false;
            if (code === 0)
                root.grabNow(root.pendingItem);
            else {
                root.pendingItem = null;
                root.done(false);
            }
        }
    }
    Process {
        id: copyProc
        onExited: function(code, status) {
            running = false;
            root.done(code === 0);
        }
    }
}
