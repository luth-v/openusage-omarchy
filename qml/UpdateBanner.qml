import QtQuick
import qs.Commons

// "Update Available" banner above the sections. The daemon (pass 8) fills the
// model; until then this only renders.
Item {
    id: root
    property string version: ""
    property bool installable: false
    signal install()
    signal dismiss()
    implicitHeight: card.implicitHeight
    height: visible ? implicitHeight : 0
    width: parent ? parent.width : 0
    Rectangle {
        id: card
        anchors.fill: parent
        radius: Style.cornerRadius
        color: Qt.alpha(Color.popups.text, 0.06)
        implicitHeight: row.implicitHeight + Style.space(24)
        Row {
            id: row
            anchors.fill: parent
            anchors.margins: Style.space(12)
            spacing: Style.space(10)
            Text {
                text: "↓"
                color: Qt.alpha(Color.popups.text, 0.65)
                font.family: Style.font.family
                font.pixelSize: Style.font.title
                anchors.top: parent.top
            }
            Column {
                width: parent.width - Style.space(32) - dismissButton.width - parent.spacing * 2
                spacing: Style.space(4)
                Text {
                    text: "Update Available"
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: true
                }
                Text {
                    width: parent.width
                    text: "OpenUsage " + root.version + " is ready to download."
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.Wrap
                }
                Rectangle {
                    width: installLabel.implicitWidth + Style.space(20)
                    height: installLabel.implicitHeight + Style.space(8)
                    radius: Style.cornerRadius
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.alpha(Color.popups.text, root.installable ? 0.4 : 0.15)
                    Text {
                        id: installLabel
                        anchors.centerIn: parent
                        text: "Install Update"
                        color: root.installable ? Color.popups.text : Qt.alpha(Color.popups.text, 0.4)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                    }
                    MouseArea {
                        anchors.fill: parent
                        enabled: root.installable
                        cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                        onClicked: root.install()
                    }
                }
            }
            Text {
                id: dismissButton
                text: "×"
                color: Qt.alpha(Color.popups.text, 0.65)
                font.family: Style.font.family
                font.pixelSize: Style.font.title
                anchors.top: parent.top
                MouseArea {
                    anchors.fill: parent
                    anchors.margins: -4
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.dismiss()
                }
            }
        }
    }
}
