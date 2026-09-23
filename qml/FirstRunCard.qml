import QtQuick
import qs.Commons

// One-time first-run hint. Shows until its × button dispatches dismissHint;
// visiting Customize does not dismiss it.
Item {
    id: root
    signal openCustomize()
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
                text: "≡"
                color: Qt.alpha(Color.popups.text, 0.65)
                font.family: Style.font.family
                font.pixelSize: Style.font.title
                anchors.top: parent.top
            }
            Column {
                width: parent.width - Style.space(32) - dismissButton.width - parent.spacing * 2
                spacing: Style.space(4)
                Text {
                    text: "Welcome to OpenUsage"
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: true
                }
                Text {
                    width: parent.width
                    text: "We set you up with the AI tools found on this machine. Add or hide providers any time."
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    wrapMode: Text.Wrap
                }
                Rectangle {
                    width: openLabel.implicitWidth + Style.space(20)
                    height: openLabel.implicitHeight + Style.space(8)
                    radius: Style.cornerRadius
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.alpha(Color.popups.text, 0.4)
                    Text {
                        id: openLabel
                        anchors.centerIn: parent
                        text: "Open Customize"
                        color: Color.popups.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.openCustomize()
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
