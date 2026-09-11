import QtQuick
import qs.Commons
import "Model.js" as Model

Column {
    id: root
    required property var provider
    required property var hostWidget
    readonly property var record: hostWidget.records[provider.id] || null
    readonly property color foreground: hostWidget.bar ? hostWidget.bar.foreground : Color.foreground
    readonly property color urgent: hostWidget.bar ? hostWidget.bar.urgent : Color.urgent
    spacing: Style.space(8)
    Row {
        width: parent.width; spacing: Style.space(8)
        ProviderMark {
            providerId: root.provider.id
            surface: Color.popups.background
            fallbackColor: root.foreground
            size: Style.space(18)
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - Style.space(26)
            text: root.provider.name + (root.record && root.record.tierLabel ? " · " + root.record.tierLabel : "")
            color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.space(16); font.bold: true
            wrapMode: Text.Wrap
        }
    }
    Text {
        width: parent.width
        visible: text !== ""
        text: Model.status(root.record)
        color: Qt.alpha(root.foreground, 0.65); font.family: Style.font.family; font.pixelSize: Style.space(12); wrapMode: Text.Wrap
    }
    Repeater {
        model: root.record ? root.record.limits : []
        delegate: Column {
            id: metric
            required property var modelData
            width: root.width
            spacing: Style.space(4)
            readonly property string severity: Model.pace(modelData, root.hostWidget.now)
            readonly property color paceColor: severity === "alarm" ? root.urgent : severity === "ahead" ? root.hostWidget.warningColor : root.foreground
            Item {
                width: parent.width; height: Style.space(22)
                Text {
                    anchors.left: parent.left; anchors.right: value.left; anchors.rightMargin: Style.space(8)
                    text: metric.modelData.title; elide: Text.ElideRight
                    color: root.foreground; font.family: Style.font.family; font.pixelSize: Style.space(13)
                }
                Text {
                    id: value; anchors.right: parent.right
                    text: Model.percent(metric.modelData.percent, root.hostWidget.display) + " " + root.hostWidget.display
                    color: metric.paceColor; font.family: Style.font.family; font.pixelSize: Style.space(13)
                }
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.hostWidget.toggleDisplay() }
            }
            Rectangle {
                width: parent.width; height: Style.space(5); radius: height/2
                color: Qt.alpha(root.foreground, 0.15)
                Rectangle {
                    width: parent.width * Model.displayed(metric.modelData.percent, root.hostWidget.display)
                    height: parent.height; radius: height/2; color: metric.paceColor
                }
            }
            Text {
                width: parent.width
                text: root.hostWidget.resetStyle === "exact" && isFinite(Date.parse(metric.modelData.resetsAt))
                    ? "Resets " + Qt.formatDateTime(new Date(metric.modelData.resetsAt), "ddd, d MMM yyyy HH:mm t")
                    : "Resets · " + Model.countdown(metric.modelData.resetsAt, root.hostWidget.now)
                color: Qt.alpha(root.foreground, 0.65); font.family: Style.font.family; font.pixelSize: Style.space(11)
                wrapMode: Text.Wrap
                MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.hostWidget.toggleReset() }
            }
        }
    }
}
