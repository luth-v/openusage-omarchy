import QtQuick
import qs.Commons
import qs.Ui as Ui

// One labeled row: title plus optional (i) tip on the left, the control
// slotted on the right. Separators handled by the parent section.
Item {
    id: root
    default property alias control: slot.children
    property string label: ""
    property string tip: ""
    property bool compact: false
    width: parent ? parent.width : 0
    implicitHeight: Math.max(labelBox.implicitHeight, slot.implicitHeight) + Style.space(14)
    height: implicitHeight
    Row {
        id: labelBox
        anchors.left: parent.left
        anchors.leftMargin: Style.space(12)
        anchors.right: slot.left
        anchors.rightMargin: Style.space(8)
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(6)
        Text {
            text: root.label
            color: Color.popups.text
            font.family: Style.font.family
            font.pixelSize: root.compact ? Style.font.bodySmall : Style.font.body
            elide: Text.ElideRight
            width: Math.min(implicitWidth, labelBox.width - info.width - labelBox.spacing)
            anchors.verticalCenter: parent.verticalCenter
        }
        Item {
            id: info
            visible: root.tip !== ""
            width: visible ? Style.space(14) : 0
            height: Style.space(14)
            anchors.verticalCenter: parent.verticalCenter
            Text {
                anchors.centerIn: parent
                text: "ⓘ"
                color: Qt.alpha(Color.popups.text, 0.5)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                acceptedButtons: Qt.NoButton
                Ui.PanelToolTip {
                    visible: parent.containsMouse
                    text: root.tip
                }
            }
        }
    }
    Item {
        id: slot
        anchors.right: parent.right
        anchors.rightMargin: Style.space(12)
        anchors.verticalCenter: parent.verticalCenter
        width: childrenRect.width
        height: childrenRect.height
    }
}
