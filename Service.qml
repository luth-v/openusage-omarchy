import QtQuick
import Quickshell
import Quickshell.Io
import "qml"
import "js/State.js" as State

// Long-lived service. Owns the daemon child, the state feed, the catalog,
// and the layout store. Views read state/layout and call commands.
//
// Fallback design (only if bar.shell.serviceFor(ownId) ever returns null on
// the trusted bar): BarWidget would get its own StateFeed over state.json and
// send commands through a short-lived `bin/openusage-omarchy cmd` Process that
// takes one JSON command on stdin. Not built: verified 2026-09-23 by source
// trace that shell.qml pluginShellForId gives third-party bar widgets a
// service-capable shell (allowOwnService=true), so serviceFor(ownId) works.
// Item root: plain QtObject takes no child objects in this Qt build.
Item {
    id: root
    readonly property string pluginDir: {
        var url = decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^file:\/\//, ""));
        return url.replace(/\/$/, "");
    }
    readonly property string launcher: root.pluginDir + "/bin/openusage-omarchy"
    readonly property string stateDir: {
        var base = Quickshell.env("XDG_STATE_HOME");
        if (!base)
            base = Quickshell.env("HOME") + "/.local/state";
        return base + "/openusage-omarchy";
    }
    readonly property string statePath: root.stateDir + "/state.json"
    readonly property string layoutPath: root.stateDir + "/layout.json"
    readonly property var state: feed.state
    readonly property string stateError: feed.error
    readonly property bool daemonUp: client.daemonUp
    readonly property var catalog: catalogData.value
    readonly property var layout: store.layout
    readonly property bool canUndo: store.canUndo
    readonly property string starNotice: store.starNotice
    readonly property string starTone: store.starTone
    readonly property int starNoticeTrigger: store.starNoticeTrigger
    readonly property var detected: State.detectedMap(root.state)
    readonly property var cardIds: State.cardIds(root.state)

    function refresh(force, cardId) {
        var cmd = {v: 1, cmd: "refresh", force: !!force};
        if (cardId)
            cmd.cardId = cardId;
        client.send(cmd);
    }
    function claimReset(cardId, expiry, requestId) {
        client.send({v: 1, cmd: "claimReset", cardId: cardId, expiry: expiry, requestId: requestId});
    }
    function setKey(provider, value) {
        client.send({v: 1, cmd: "setKey", provider: provider, value: value});
    }
    function deleteKey(provider) {
        client.send({v: 1, cmd: "deleteKey", provider: provider});
    }
    // Daemon-backed sends: check/update and snooze.
    function checkUpdate() {
        client.send({v: 1, cmd: "checkUpdate"});
    }
    function snoozeUpdate(version) {
        client.send({v: 1, cmd: "snoozeUpdate", version: version});
    }
    function installUpdate() {
        client.send({v: 1, cmd: "installUpdate"});
    }
    function dispatch(action) {
        store.dispatch(action);
    }
    function undo() {
        return store.undo();
    }

    QtObject {
        id: catalogData
        property var value: null
    }
    FileView {
        path: root.pluginDir + "/catalog.json"
        onLoaded: {
            try {
                catalogData.value = JSON.parse(text());
            } catch (_) {
                catalogData.value = null;
            }
        }
    }
    DaemonClient {
        id: client
        launcher: root.launcher
    }
    StateFeed {
        id: feed
        statePath: root.statePath
    }
    LayoutStore {
        id: store
        catalog: root.catalog
        layoutPath: root.layoutPath
        detected: root.detected
        cardIds: root.cardIds
    }
}
