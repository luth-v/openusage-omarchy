import QtQuick
import qs.Commons
import qs.Ui as Ui
import "Model.js" as Model

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
                    Text { text: "Customize"; color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.space(22); font.bold: true }
                    Text {
                        text: "Display: " + (root.hostWidget ? root.hostWidget.display : "Used") + "  ⇄"
                        color: root.foreground; font.family: Style.font.family
                        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.hostWidget.toggleDisplay() }
                    }
                    Text {
                        width: parent.width; wrapMode: Text.Wrap
                        text: "The highest Used Metric leads automatically. Star one extra Metric per Provider for the bar. Use the arrows to change order."
                        color: Qt.alpha(root.foreground, 0.65); font.family: Style.font.family; font.pixelSize: Style.space(12)
                    }
                    Repeater {
                        id: providerList
                        model: root.hostWidget ? root.hostWidget.orderedProviders : Model.providers
                        delegate: Column {
                            id: provider
                            required property var modelData
                            required property int index
                            width: column.width; spacing: Style.space(8)
                            readonly property var record: root.hostWidget ? root.hostWidget.records[modelData.id] : null
                            readonly property var lead: Model.lead(record)
                            Row {
                                width: parent.width; height: Style.space(26); spacing: Style.space(8)
                                ProviderMark {
                                    providerId: provider.modelData.id
                                    surface: Color.popups.background
                                    fallbackColor: root.foreground
                                    size: Style.space(16)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Text {
                                    id: providerName
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: (root.hostWidget && root.hostWidget.providerEnabled(provider.modelData.id) ? "☑  " : "☐  ") + provider.modelData.name
                                    color: root.foreground; font.family: Style.font.family; font.bold: true
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.hostWidget.toggleProvider(provider.modelData.id) }
                                }
                                Item {
                                    width: Math.max(Style.space(8), parent.width - Style.space(16) - providerName.implicitWidth - Style.space(48))
                                    height: 1
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "↑"
                                    color: root.foreground
                                    opacity: provider.index === 0 ? 0.3 : 1
                                    font.family: Style.font.family; font.bold: true
                                    MouseArea {
                                        anchors.fill: parent; anchors.margins: -6
                                        enabled: provider.index > 0
                                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                        onClicked: root.hostWidget.moveProvider(provider.modelData.id, -1)
                                    }
                                }
                                Text {
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: "↓"
                                    color: root.foreground
                                    opacity: provider.index === providerList.count - 1 ? 0.3 : 1
                                    font.family: Style.font.family; font.bold: true
                                    MouseArea {
                                        anchors.fill: parent; anchors.margins: -6
                                        enabled: provider.index < providerList.count - 1
                                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                        onClicked: root.hostWidget.moveProvider(provider.modelData.id, 1)
                                    }
                                }
                            }
                            Text {
                                visible: !provider.record || !provider.record.limits.length
                                text: "Metrics appear after login and refresh"
                                color: Qt.alpha(root.foreground, 0.65); font.family: Style.font.family; font.pixelSize: Style.space(12)
                            }
                            Repeater {
                                model: provider.record ? provider.record.limits : []
                                delegate: Text {
                                    required property var modelData
                                    readonly property bool isLead: provider.lead && provider.lead.label === modelData.label
                                    readonly property bool sticky: root.hostWidget && root.hostWidget.stars[provider.modelData.id] === modelData.label
                                    width: provider.width; height: Style.space(28)
                                    text: (sticky || isLead ? "★  " : "☆  ") + modelData.title + (isLead ? " · Lead" : "") + (sticky ? " · Sticky" : "")
                                    color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.space(13)
                                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.hostWidget.toggleStar(provider.modelData.id, parent.modelData.label) }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
