import QtQuick
import qs.Commons
import qs.Ui as Ui

Ui.Panel {
    id: root
    moduleName: "luth-v.openusage"
    manageIpc: false
    property var hostWidget: null
    property var anchorItem: null
    readonly property color foreground: bar ? bar.foreground : Color.foreground
    Ui.KeyboardPanel {
        id: panel
        anchorItem: root.anchorItem; owner: root.hostWidget || root; bar: root.bar
        open: root.opened; focusTarget: keys
        contentWidth: fittedContentWidth(Style.space(430))
        contentHeight: fittedContentHeight(column.implicitHeight, Style.space(780))
        Ui.PanelKeyCatcher {
            id: keys; anchors.fill: parent
            onCloseRequested: root.close()
            onTextKey: function(t) { if (t.toLowerCase() === "r" && root.hostWidget) root.hostWidget.refresh(true); }
            Flickable {
                anchors.fill: parent; clip: true
                contentWidth: width; contentHeight: column.implicitHeight
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: column; width: parent.width; spacing: Style.space(18)
                    Text {
                        text: "OpenUsage"; color: root.foreground
                        font.family: Style.font.family; font.pixelSize: Style.space(22); font.bold: true
                    }
                    Text {
                        text: "Display: " + (root.hostWidget ? root.hostWidget.display : "Used") + "  ⇄"
                        color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.space(13)
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.hostWidget.toggleDisplay() }
                    }
                    Repeater {
                        model: root.hostWidget ? root.hostWidget.enabledProviders : []
                        delegate: ProviderCard {
                            required property var modelData
                            width: column.width; provider: modelData; hostWidget: root.hostWidget
                        }
                    }
                    Text {
                        visible: root.hostWidget && root.hostWidget.enabledProviders.length === 0
                        text: "No Providers enabled. Right-click the bar to Customize."
                        width: parent.width; wrapMode: Text.Wrap; color: Qt.alpha(root.foreground, 0.65); font.family: Style.font.family
                    }
                    Text {
                        width: parent.width; visible: text !== ""
                        text: root.hostWidget ? root.hostWidget.refreshError : ""
                        wrapMode: Text.Wrap; color: Color.urgent; font.family: Style.font.family
                    }
                    Text {
                        width: parent.width
                        text: root.hostWidget && root.hostWidget.refreshing ? "Refreshing…" : "Next update in " + Math.max(0, Math.ceil(((root.hostWidget ? root.hostWidget.nextUpdate-root.hostWidget.now : 0))/1000)) + "s · Refresh  [r]"
                        color: Qt.alpha(root.foreground, 0.65); font.family: Style.font.family; font.pixelSize: Style.space(12)
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.hostWidget.refresh(true) }
                    }
                }
            }
        }
    }
}
