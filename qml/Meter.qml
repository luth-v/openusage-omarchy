import QtQuick
import qs.Commons
import qs.Ui as Ui

// Capsule quota meter: track, fill, and the even-pace tick. Fill color and
// geometry come from the row model; this only draws them.
Item {
    id: root
    property real fraction: 0
    property color fill: Color.accent
    property bool hasData: true
    property var tick: null
    property string tip: ""
    implicitHeight: Style.space(6)
    height: implicitHeight
    Rectangle {
        id: track
        anchors.fill: parent
        radius: height / 2
        color: Qt.alpha(Color.popups.text, 0.15)
        Rectangle {
            height: parent.height
            radius: height / 2
            width: !root.hasData || root.fraction <= 0 ? 0 : Math.max(parent.height, parent.width * Math.min(1, root.fraction))
            color: root.fill
            visible: width > 0
        }
    }
    Rectangle {
        visible: root.tick !== null && root.tick !== undefined
        width: 2
        height: parent.height + 4
        anchors.verticalCenter: parent.verticalCenter
        x: Math.min(Math.max(track.width * Number(root.tick) - 1, 0), Math.max(track.width - 2, 0))
        radius: 1
        color: Qt.alpha(Color.popups.text, 0.55)
    }
    MouseArea {
        anchors.fill: parent
        hoverEnabled: root.tip !== ""
        Ui.PanelToolTip {
            visible: parent.containsMouse && root.tip !== ""
            text: root.tip
        }
    }
}
