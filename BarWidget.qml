import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui
import "qml" as Q
import "js/Strip.js" as Strip
import "js/Format.js" as Format

// Final strip: user Stars in Text or Bars style over service state.
Ui.BarWidget {
    id: root
    moduleName: "luth-v.openusage-omarchy"
    readonly property var service: bar && bar.shell && typeof bar.shell.serviceFor === "function" ? bar.shell.serviceFor(moduleName) : null
    readonly property var feed: service ? service.state : null
    readonly property var layout: service ? service.layout : null
    readonly property var catalog: service ? service.catalog : null
    readonly property string display: setting("display", "Left")
    readonly property string resetDisplay: setting("resetDisplay", "Countdown")
    readonly property string style: setting("style", "Text")
    readonly property var strip: Strip.build(root.layout, root.catalog, root.feed, root.display, Format)
    readonly property bool serviceMissing: !service
    readonly property bool daemonDown: service && !service.daemonUp
    readonly property bool showBars: root.style === "Bars" && root.strip.bars.length > 0
    readonly property var barsGeo: Strip.barsLayout(Style.space(18), Math.max(1, root.strip.bars.length))
    readonly property color markSurface: bar ? bar.background : Color.background
    readonly property var manifestDefaults: manifestData.value || {}
    readonly property string tooltip: {
        if (root.serviceMissing)
            return "OpenUsage · enable the service in shell.json plugins[]";
        if (root.daemonDown)
            return "OpenUsage · service not running";
        return root.strip.accessibilityText || "OpenUsage · waiting for first refresh";
    }

    function persist(key, value) {
        var entry = {id: root.moduleName};
        for (var existing in root.settings)
            if (existing !== "id")
                entry[existing] = root.settings[existing];
        entry[key] = value;
        root.writeEntry(entry);
    }
    function writeEntry(entry) {
        root.settings = entry;
        if (root.bar && root.bar.shell && typeof root.bar.shell.updateEntryInline === "function")
            root.bar.shell.updateEntryInline(root.moduleName, entry);
    }
    function resetSettingsToDefaults() {
        var entry = {id: root.moduleName};
        for (var key in root.manifestDefaults)
            entry[key] = root.manifestDefaults[key];
        root.writeEntry(entry);
    }
    function toggleDisplay() {
        persist("display", display === "Used" ? "Left" : "Used");
    }
    function toggleResetDisplay() {
        persist("resetDisplay", resetDisplay === "Countdown" ? "Exact Time" : "Countdown");
    }
    function refresh() {
        if (service)
            service.refresh(true);
    }
    function open() {
        dashboard.active = true;
        if (dashboard.item)
            dashboard.item.open();
    }
    function close() {
        if (dashboard.item)
            dashboard.item.close();
    }
    function toggle() {
        dashboard.active = true;
        if (dashboard.item)
            dashboard.item.toggle();
    }
    function openCustomize(cardId) {
        if (dashboard.item)
            dashboard.item.close();
        if (settings.item)
            settings.item.close();
        customize.active = true;
        if (customize.item) {
            customize.item.openCard(cardId || "");
            customize.item.open();
        }
    }
    function openSettings() {
        if (dashboard.item)
            dashboard.item.close();
        if (customize.item)
            customize.item.close();
        settings.active = true;
        if (settings.item)
            settings.item.open();
    }
    function openDashboard() {
        if (customize.item)
            customize.item.close();
        if (settings.item)
            settings.item.close();
        dashboard.active = true;
        if (dashboard.item)
            dashboard.item.open();
    }

    implicitWidth: button.implicitWidth
    implicitHeight: button.implicitHeight
    Loader {
        id: dashboard
        active: false
        source: "qml/Dashboard.qml"
        onLoaded: {
            item.hostWidget = root;
            item.anchorItem = button;
            item.bar = root.bar;
        }
    }
    Loader {
        id: customize
        active: false
        source: "qml/Customize.qml"
        onLoaded: {
            item.hostWidget = root;
            item.anchorItem = button;
            item.bar = root.bar;
        }
    }
    Loader {
        id: settings
        active: false
        source: "qml/Settings.qml"
        onLoaded: {
            item.hostWidget = root;
            item.anchorItem = button;
            item.bar = root.bar;
        }
    }
    QtObject {
        id: manifestData
        property var value: null
    }
    FileView {
        path: decodeURIComponent(Qt.resolvedUrl("./manifest.json").toString().replace(/^file:\/\//, ""))
        onLoaded: {
            try {
                manifestData.value = JSON.parse(text()).barWidget.defaults || {};
            } catch (_) {
                manifestData.value = {};
            }
        }
    }
    IpcHandler {
        target: "luth-v.openusage-omarchy"
        function open(): void { root.open(); }
        function close(): void { root.close(); }
        function toggle(): void { root.toggle(); }
        function customize(): void { root.openCustomize(); }
        function settings(): void { root.openSettings(); }
        function refresh(): void { root.refresh(); }
    }
    Grid {
        id: stripGrid
        visible: !root.showBars
        anchors.centerIn: parent
        rows: root.vertical ? Math.max(1, root.strip.groups.length) : 1
        columns: root.vertical ? 1 : Math.max(1, root.strip.groups.length)
        rowSpacing: Style.space(4)
        columnSpacing: Style.space(11)
        Repeater {
            model: root.strip.groups
            delegate: Row {
                required property var modelData
                spacing: Style.space(4)
                height: Math.max(mark.height, label.height)
                Q.ProviderMark {
                    id: mark
                    providerId: modelData.family
                    surface: root.markSurface
                    fallbackColor: button.foreground
                    size: Style.space(14)
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    id: label
                    text: modelData.text
                    color: button.foreground
                    font.family: button.fontFamily
                    font.pixelSize: Style.font.body
                    font.bold: true
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }
    Item {
        id: barsGlyph
        visible: root.showBars
        anchors.centerIn: parent
        width: root.barsGeo.side
        height: root.barsGeo.side
        Repeater {
            model: root.strip.bars
            delegate: Item {
                required property var modelData
                required property int index
                readonly property var fill: Strip.fill(root.barsGeo.trackW, modelData.fraction)
                x: root.barsGeo.trackX
                y: root.barsGeo.yOffset + index * (root.barsGeo.trackH + root.barsGeo.gap)
                width: root.barsGeo.trackW
                height: root.barsGeo.trackH
                Rectangle {
                    anchors.fill: parent
                    radius: root.barsGeo.rx
                    color: Qt.alpha(button.foreground, 0.16)
                }
                Rectangle {
                    visible: fill.fillW > 0
                    width: fill.fillW
                    height: parent.height
                    radius: root.barsGeo.rx
                    color: button.foreground
                }
                Rectangle {
                    visible: fill.fillW > 0 && fill.remainderW > 0 && fill.dividerX !== null
                    x: fill.dividerX
                    width: fill.remainderW
                    height: parent.height
                    radius: root.barsGeo.rx
                    color: Qt.alpha(button.foreground, 0.24)
                }
            }
        }
    }
    Ui.WidgetButton {
        id: button
        anchors.fill: parent
        bar: root.bar
        labelVisible: root.strip.isEmpty
        text: "OpenUsage"
        tooltipText: root.tooltip
        horizontalMargin: 8.75
        fixedWidth: root.vertical || root.strip.isEmpty ? -1 : (root.showBars ? barsGlyph.width : stripGrid.implicitWidth) + Style.spaceReal(8.75) * 2
        fixedHeight: root.vertical && !root.strip.isEmpty ? (root.showBars ? barsGlyph.height : stripGrid.implicitHeight) + Style.spaceReal(6) * 2 : -1
        onPressed: function(b) {
            if (b === Qt.MiddleButton)
                root.refresh();
            else if (b === Qt.RightButton)
                root.openCustomize();
            else
                root.toggle();
        }
    }
}
