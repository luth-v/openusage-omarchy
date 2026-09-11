import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui
import "Model.js" as Model

Ui.BarWidget {
    id: root
    moduleName: "luth-v.openusage"
    property var records: ({})
    property double now: Date.now()
    property double nextUpdate: Date.now()
    property bool queued: false
    property bool queuedForce: false
    property string refreshError: ""
    property color warningColor: Color.accent
    readonly property string display: setting("display", "Used")
    readonly property string resetStyle: setting("resetStyle", "countdown")
    readonly property var stars: setting("stars", {})
    readonly property var providerSettings: setting("providers", {})
    readonly property var order: setting("order", [])
    readonly property int refreshSeconds: Math.max(30, Math.min(3600, Number(setting("refreshIntervalSec", 300)) || 300))
    readonly property var orderedProviders: Model.ordered(order)
    readonly property var enabledProviders: orderedProviders.filter(function(p) { return root.providerEnabled(p.id); })
    readonly property var numberedProviders: enabledProviders.filter(function(p) {
        return Model.percents(root.records[p.id], root.stars[p.id], root.display) !== "";
    })
    readonly property var stripProviders: numberedProviders.length ? numberedProviders : enabledProviders
    readonly property bool refreshing: updater.running
    readonly property color markSurface: bar ? bar.background : Color.background
    readonly property string tooltip: enabledProviders.map(function(p) {
        return Model.metrics(root.records[p.id], root.stars[p.id]).map(function(l) {
            return p.name + " · " + l.title + " · " + Model.percent(l.percent, root.display) + " " + root.display + " · " + Model.countdown(l.resetsAt, root.now);
        }).join("\n");
    }).filter(function(s) { return s !== ""; }).join("\n") || "OpenUsage · Click for Dashboard" 
    readonly property bool opened: (dashboard.item && dashboard.item.opened) || (customize.item && customize.item.opened) || false
    readonly property bool popoutSwitchClosing: (dashboard.item && dashboard.item.popoutSwitchClosing) || (customize.item && customize.item.popoutSwitchClosing) || false
    readonly property real openPanelIndicatorWidth: strip.implicitWidth
    readonly property real openPanelIndicatorHeight: Style.space(10)

    function providerEnabled(id) { return !providerSettings[id] || providerSettings[id].enabled !== false; }
    function enabled(id) { return providerEnabled(id); }
    function persist(key, value) {
        var entry = {id: root.moduleName};
        for (var existing in root.settings) if (existing !== "id") entry[existing] = root.settings[existing];
        entry[key] = value;
        root.settings = entry;
        if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
            root.bar.shell.updateEntryInline(root.moduleName, entry);
    }
    function toggleDisplay() { persist("display", display === "Used" ? "Left" : "Used"); }
    function toggleReset() { persist("resetStyle", resetStyle === "countdown" ? "exact" : "countdown"); }
    function toggleProvider(id) {
        var providers = Object.assign({}, providerSettings);
        providers[id] = Object.assign({}, providers[id] || {}, {enabled: !enabled(id)});
        persist("providers", providers);
    }
    function toggleStar(id, label) {
        var chosen = Object.assign({}, stars);
        if (chosen[id] === label) delete chosen[id]; else chosen[id] = label;
        persist("stars", chosen);
    }
    function moveProvider(id, delta) {
        persist("order", Model.move(order, id, delta));
    }
    function acceptRecord(id, raw) {
        var record = Model.parse(raw, id);
        if (!record) return;
        var copy = Object.assign({}, records);
        copy[id] = record;
        records = copy;
    }
    function refresh(force) {
        if (updater.running) { queued = true; queuedForce = queuedForce || force; return; }
        nextUpdate = Date.now() + refreshSeconds * 1000;
        updater.command = [decodeURIComponent(Qt.resolvedUrl("bin/openusage-update").toString().replace(/^file:\/\//, "")), force ? "--force" : "--limits-only"];
        updater.running = true;
    }
    function open() {
        if (customize.item) customize.item.close();
        if (dashboard.item) dashboard.item.open();
    }
    function openCustomize() {
        if (dashboard.item) dashboard.item.close();
        if (customize.item) customize.item.open();
    }
    function close() {
        if (dashboard.item) dashboard.item.close();
        if (customize.item) customize.item.close();
    }
    function closeForPopoutSwitch() {
        if (dashboard.item) dashboard.item.closeForPopoutSwitch();
        if (customize.item) customize.item.closeForPopoutSwitch();
    }
    function injectPanels() {
        [dashboard.item, customize.item].forEach(function(p) {
            if (!p) return;
            p.bar = root.bar; p.hostWidget = root; p.anchorItem = button;
        });
    }
    onBarChanged: injectPanels()
    onRefreshSecondsChanged: nextUpdate = Date.now() + refreshSeconds * 1000
    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight
    Component.onCompleted: refresh(false)

    Timer {
        interval: 1000; repeat: true; running: true
        onTriggered: {
            root.now = Date.now();
            if (root.now >= root.nextUpdate && !updater.running) root.refresh(false);
        }
    }
    Process {
        id: updater
        onExited: function(code, status) {
            root.refreshError = code === 0 ? "" : "A collector failed. Last known quotas are retained.";
            if (root.queued) {
                var force = root.queuedForce;
                root.queued = false; root.queuedForce = false;
                Qt.callLater(function() { root.refresh(force); });
            }
        }
    }
    FileView {
        path: Color.currentThemePath + "/colors.toml"
        watchChanges: true
        onFileChanged: reload()
        onLoaded: root.warningColor = Model.themeWarning(text(), Color.accent)
    }
    Instantiator {
        model: Model.providers
        delegate: QtObject {
            required property var modelData
            property FileView view: FileView {
                path: Quickshell.env("HOME") + "/.local/state/openusage/" + modelData.id + ".json"
                watchChanges: true
                onFileChanged: reload()
                onLoaded: root.acceptRecord(modelData.id, text())
            }
        }
    }
    Loader { id: dashboard; source: Qt.resolvedUrl("Dashboard.qml"); visible: false; onLoaded: root.injectPanels() }
    Loader { id: customize; source: Qt.resolvedUrl("Customize.qml"); visible: false; onLoaded: root.injectPanels() }
    IpcHandler {
        target: "luth-v.openusage"
        function open(): void { root.open(); }
        function close(): void { root.close(); }
        function customize(): void { root.openCustomize(); }
        function refresh(): void { root.refresh(true); }
    }
    Grid {
        id: strip
        anchors.centerIn: parent
        rows: root.vertical ? Math.max(1, root.stripProviders.length) : 1
        columns: root.vertical ? 1 : Math.max(1, root.stripProviders.length)
        rowSpacing: Style.space(4)
        columnSpacing: Style.space(8)
        Repeater {
            model: root.stripProviders
            delegate: Row {
                required property var modelData
                spacing: Style.space(4)
                height: Style.space(16)
                ProviderMark {
                    providerId: modelData.id
                    surface: root.markSurface
                    fallbackColor: button.foreground
                    size: Style.space(14)
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    visible: text !== ""
                    text: Model.percents(root.records[modelData.id], root.stars[modelData.id], root.display)
                    color: button.foreground
                    font.family: button.fontFamily
                    font.pixelSize: Style.font.bodySmall
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }
    Ui.WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        labelVisible: root.stripProviders.length === 0
        text: "OpenUsage"
        tooltipText: root.tooltip
        horizontalMargin: 8.75
        fixedWidth: root.vertical || root.stripProviders.length === 0 ? -1 : strip.implicitWidth + Style.spaceReal(8.75) * 2
        fixedHeight: root.vertical && root.stripProviders.length > 0 ? strip.implicitHeight + Style.spaceReal(6) * 2 : -1
        onPressed: function(b) {
            if (b === Qt.MiddleButton) root.refresh(true);
            else if (b === Qt.RightButton) root.openCustomize();
            else if (dashboard.item && dashboard.item.opened) root.close(); else root.open();
        }
    }
}
