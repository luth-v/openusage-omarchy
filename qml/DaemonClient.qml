import QtQuick
import Quickshell.Io

// Owns the Python daemon child process. Restarts with capped backoff
// (1 s to 60 s). The daemon exits on stdin EOF, so a reload is clean.
// Item root: plain QtObject takes no child objects in this Qt build.
Item {
    id: root
    property string launcher: ""
    property int backoffMs: 1000
    readonly property bool daemonUp: proc.running

    function send(obj) {
        if (proc.running)
            proc.write(JSON.stringify(obj) + "\n");
    }

    Process {
        id: proc
        command: [root.launcher, "serve"]
        stdinEnabled: true
        running: true
        onStarted: root.backoffMs = 1000
        onExited: function(code, status) {
            restartTimer.interval = root.backoffMs;
            restartTimer.restart();
        }
    }
    Timer {
        id: restartTimer
        repeat: false
        onTriggered: {
            root.backoffMs = Math.min(60000, root.backoffMs * 2);
            proc.running = true;
        }
    }
}
