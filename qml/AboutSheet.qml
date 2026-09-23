import QtQuick
import qs.Commons

// Small About sheet: version, license, upstream credit, repo links.
// Quit stays omitted: it cannot exist in-process in the shell.
Item {
    id: root
    property string version: ""
    signal close()
    Column {
        anchors.centerIn: parent
        width: Math.min(parent.width - Style.space(48), Style.space(300))
        spacing: Style.space(8)
        Rectangle {
            width: parent.width
            height: card.implicitHeight + Style.space(32)
            radius: Style.cornerRadius
            color: Color.popups.background
            border.width: 1
            border.color: Qt.alpha(Color.popups.text, 0.2)
            Column {
                id: card
                width: parent.width - Style.space(32)
                anchors.centerIn: parent
                spacing: Style.space(6)
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.version !== "" ? "OpenUsage v" + root.version : "OpenUsage"
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: true
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: "License: MIT"
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: "Based on OpenUsage by Robin Ebers"
                    color: Qt.alpha(Color.popups.text, 0.8)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.WordWrap
                    text: "Maintained also by Mert & David"
                    color: Qt.alpha(Color.popups.text, 0.8)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                }
                Item {
                    width: parent.width
                    height: upstreamLink.implicitHeight
                    Text {
                        id: upstreamLink
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "Upstream on GitHub"
                        color: Color.accent
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.underline: upstreamMouse.containsMouse
                        MouseArea {
                            id: upstreamMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Qt.openUrlExternally("https://github.com/robinebers/openusage")
                        }
                    }
                }
                Item {
                    width: parent.width
                    height: portLink.implicitHeight
                    Text {
                        id: portLink
                        anchors.horizontalCenter: parent.horizontalCenter
                        text: "This port on GitHub"
                        color: Color.accent
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        font.underline: portMouse.containsMouse
                        MouseArea {
                            id: portMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: Qt.openUrlExternally("https://github.com/luth-v/openusage-omarchy")
                        }
                    }
                }
                Item {
                    width: parent.width
                    height: closeButton.height + Style.space(4)
                    Rectangle {
                        id: closeButton
                        anchors.horizontalCenter: parent.horizontalCenter
                        width: closeLabel.implicitWidth + Style.space(24)
                        height: closeLabel.implicitHeight + Style.space(10)
                        radius: height / 2
                        color: Qt.alpha(Color.accent, closeMouse.containsMouse ? 0.25 : 0.15)
                        Text {
                            id: closeLabel
                            anchors.centerIn: parent
                            text: "Close"
                            color: Color.popups.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                            font.bold: true
                        }
                        MouseArea {
                            id: closeMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.close()
                        }
                    }
                }
            }
        }
    }
}
