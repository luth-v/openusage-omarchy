import QtQuick
import qs.Commons
import qs.Ui as Ui

// Pinned footer: daemon version, refresh countdown, Options button.
Item {
    id: root
    property string version: ""
    property string text: ""
    property bool updating: false
    property bool reduceMotion: false
    property Item menuLayer: null
    signal options(real x, real y)
    signal refreshRequested()
    implicitHeight: Math.max(versionLabel.implicitHeight, optionsButton.height) + Style.space(12)
    height: implicitHeight
    width: parent ? parent.width : 0
    Rectangle {
        anchors.fill: parent
        color: Color.popups.background
    }
    Rectangle {
        width: parent.width
        height: 1
        color: Qt.alpha(Color.popups.text, 0.15)
    }
    Row {
        height: implicitHeight
        anchors.left: parent.left
        anchors.leftMargin: Style.space(14)
        anchors.right: parent.right
        anchors.rightMargin: Style.space(10)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(8)
        Text {
            id: versionLabel
            visible: text !== ""
            text: root.version !== "" ? "v" + root.version : ""
            color: Qt.alpha(Color.popups.text, 0.6)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            anchors.verticalCenter: parent.verticalCenter
        }
        Item {
            width: Math.max(8, parent.width - versionLabel.implicitWidth - statusBox.width - optionsButton.width - parent.spacing * 3)
            height: 1
        }
        Item {
            id: statusBox
            width: statusRow.implicitWidth
            height: Math.max(statusLabel.implicitHeight, Style.space(12))
            anchors.verticalCenter: parent.verticalCenter
            Row {
                id: statusRow
                spacing: Style.space(5)
                anchors.verticalCenter: parent.verticalCenter
                Text {
                    id: statusLabel
                    text: root.text
                    color: Qt.alpha(Color.popups.text, 0.6)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                    anchors.verticalCenter: parent.verticalCenter
                }
                Rectangle {
                    id: footerSpinner
                    visible: root.updating
                    width: Style.space(12)
                    height: Style.space(12)
                    radius: Style.space(6)
                    anchors.verticalCenter: parent.verticalCenter
                    color: "transparent"
                    border.width: 2
                    border.color: Qt.alpha(Color.accent, 0.35)
                    Rectangle {
                        width: parent.width
                        height: 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: Color.accent
                    }
                    RotationAnimation on rotation {
                        running: footerSpinner.visible && !root.reduceMotion
                        loops: Animation.Infinite
                        duration: 800
                        from: 0
                        to: 360
                    }
                }
            }
            MouseArea {
                id: statusMouse
                anchors.fill: parent
                enabled: !root.updating
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.refreshRequested()
                Ui.PanelToolTip {
                    visible: parent.containsMouse && !root.updating
                    text: "Refresh now (r)"
                }
            }
        }
        Item {
            id: optionsButton
            width: optionsLabel.implicitWidth + Style.space(16)
            height: optionsLabel.implicitHeight + Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            Rectangle {
                anchors.fill: parent
                radius: Style.space(6)
                color: Qt.alpha(Color.popups.text, optionsMouse.containsMouse ? 0.12 : 0)
            }
            Text {
                id: optionsLabel
                anchors.centerIn: parent
                text: "⋯"
                color: Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.body
                font.bold: true
            }
            MouseArea {
                id: optionsMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: {
                    if (root.menuLayer) {
                        var p = mapToItem(root.menuLayer, width / 2, 0);
                        root.options(p.x, p.y);
                    }
                }
                Ui.PanelToolTip {
                    visible: parent.containsMouse
                    text: "Options"
                }
            }
        }
    }
}
