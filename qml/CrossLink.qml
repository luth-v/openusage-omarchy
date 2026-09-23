import QtQuick
import qs.Commons

// "Wrong door" cross-link between Customize and Settings (upstream
// ScreenCrossLinkRow): icon, title, subtitle, chevron. Taps open it.
Rectangle {
    id: root
    property string icon: ""
    property string title: ""
    property string subtitle: ""
    signal open()
    height: Style.space(52)
    radius: Style.cornerRadius
    color: Qt.alpha(Color.popups.text, linkMouse.containsMouse ? 0.1 : 0.05)
    Row {
        anchors.fill: parent
        anchors.leftMargin: Style.space(12)
        anchors.rightMargin: Style.space(12)
        spacing: Style.space(10)
        Text {
            text: root.icon
            color: Qt.alpha(Color.popups.text, 0.7)
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            anchors.verticalCenter: parent.verticalCenter
        }
        Column {
            spacing: 0
            anchors.verticalCenter: parent.verticalCenter
            Text {
                text: root.title
                color: Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                font.bold: true
            }
            Text {
                text: root.subtitle
                color: Qt.alpha(Color.popups.text, 0.6)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
        }
        Item {
            width: Math.max(8, parent.width - parent.children[0].implicitWidth - parent.children[1].implicitWidth - parent.children[3].implicitWidth - parent.spacing * 3)
            height: 1
        }
        Text {
            text: "›"
            color: Qt.alpha(Color.popups.text, 0.5)
            font.family: Style.font.family
            font.pixelSize: Style.font.title
            anchors.verticalCenter: parent.verticalCenter
        }
    }
    MouseArea {
        id: linkMouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.open()
    }
}
