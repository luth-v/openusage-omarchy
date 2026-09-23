import QtQuick
import Quickshell.Io
import "../js/Layout.js" as Layout
import "../js/Notices.js" as Notices

// Sole writer of layout.json. Reducer dispatch plus session undo.
// Item root: plain QtObject takes no child objects in this Qt build.
Item {
    id: root
    property var catalog: null
    property string layoutPath: ""
    property var detected: null
    property var cardIds: []
    property var layout: null
    property var undoStack: []
    property bool canUndo: undoStack.length > 0
    property string starNotice: ""
    property string starTone: "positive"
    property int starNoticeTrigger: 0

    function ingest(raw) {
        if (!root.catalog)
            return;
        var next = Layout.merge(Layout.migrate(Layout.parse(raw)), root.catalog, root.detected);
        if (JSON.stringify(next) !== JSON.stringify(root.layout))
            root.layout = next;
    }
    function seed() {
        if (root.catalog && !root.layout)
            write(Layout.defaults(root.catalog, root.detected));
    }
    function write(next) {
        root.layout = next;
        layoutFile.setText(JSON.stringify(next));
    }
    function dispatch(action) {
        if (!root.layout || !root.catalog)
            return;
        var result = Layout.reduce(root.layout, action, root.catalog);
        if (result.notice)
            showNotice(result.notice, "pin");
        else if ((action.type === "toggleStar" || action.type === "setStar") && result.layout !== root.layout)
            showNotice({kind: hadStar(action) ? "unstarred" : "starred"}, "customize");
        if (result.clearUndo)
            root.undoStack = [];
        else if (result.undoable && result.layout !== root.layout)
            root.undoStack = Layout.pushHistory(root.undoStack, root.layout);
        if (result.layout !== root.layout)
            write(result.layout);
    }
    function undo() {
        if (!root.canUndo)
            return false;
        var popped = Layout.popHistory(root.undoStack);
        root.undoStack = popped.stack;
        if (popped.snapshot)
            write(popped.snapshot);
        return !!popped.snapshot;
    }
    function showNotice(notice, surface) {
        root.starNotice = Notices.messageFor(notice.kind) || "";
        root.starTone = Notices.toneFor(notice.kind);
        root.starNoticeTrigger++;
        clearTimer.interval = Notices.timeoutFor(surface || "pin");
        clearTimer.restart();
    }
    function hadStar(action) {
        var slot = root.layout && root.layout.cards ? root.layout.cards[action.cardId] : null;
        var stars = slot && Array.isArray(slot.stars) ? slot.stars : [];
        return stars.indexOf(action.metricId) >= 0;
    }
    onCatalogChanged: {
        if (root.catalog && !root.layout)
            layoutFile.reload();
    }
    onDetectedChanged: {
        if (root.layout && !root.layout.firstRunCompleted && root.detected)
            dispatch({type: "completeFirstRun", detected: root.detected});
    }
    onCardIdsChanged: {
        if (root.layout && root.cardIds.length > 0)
            dispatch({type: "ensureCards", cardIds: root.cardIds});
    }

    Timer {
        id: clearTimer
        interval: Notices.timeoutFor("pin")
        repeat: false
        onTriggered: root.starNotice = ""
    }
    FileView {
        id: layoutFile
        path: root.layoutPath
        watchChanges: true
        atomicWrites: true
        onLoaded: root.ingest(text())
        onLoadFailed: root.seed()
        onFileChanged: reload()
    }
}
