import QtQuick
import qs.Commons

// One settings block: caption header over a rounded card of rows.
// Same visual language as Customize (SettingsScreen section shape).
Column {
    id: root
    default property alias rows: stack.children
    property string title: ""
    property bool showWarning: false
    property color warningColor: Color.accent
    property string warningTip: ""
    width: parent ? parent.width : 0
    spacing: Style.space(6)
    Row {
        x: Style.space(8)
        spacing: Style.space(6)
        Text {
            text: root.title
            color: Qt.alpha(Color.popups.text, 0.6)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            font.bold: true
            anchors.verticalCenter: parent.verticalCenter
        }
        Text {
            visible: root.showWarning
            text: "▲"
            color: root.warningColor
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    Rectangle {
        width: parent.width
        height: stack.implicitHeight
        radius: Style.cornerRadius
        color: Qt.alpha(Color.popups.text, 0.05)
        Column {
            id: stack
            width: parent.width
        }
    }
}
