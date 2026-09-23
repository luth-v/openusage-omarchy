import QtQuick
import Quickshell.Io
import "../js/State.js" as State

// Read-only view of state.json. The daemon is its sole writer.
// Item root: plain QtObject takes no child objects in this Qt build.
Item {
    id: root
    property string statePath: ""
    property var state: null
    property string error: ""

    function ingest(raw) {
        var result = State.parseState(raw);
        if (result.ok) {
            root.state = result.state;
            root.error = "";
        } else {
            root.state = null;
            root.error = result.error;
        }
    }

    FileView {
        path: root.statePath
        watchChanges: true
        onFileChanged: reload()
        onLoaded: root.ingest(text())
        onLoadFailed: function(err) {
            root.state = null;
            root.error = "state unreadable";
        }
    }
}
