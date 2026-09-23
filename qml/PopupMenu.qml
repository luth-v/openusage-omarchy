import QtQuick
import qs.Commons

// Generic context menu box. Items follow the Dashboard.js menu shape:
// {kind: "item", id, label, enabled}, {kind: "divider"}, or {kind:
// "submenu", id, label, enabled, children}. One submenu level.
Item {
    id: root
    property var items: []
    signal pick(string action)
    property var openSubmenu: null
    property real openSubY: 0
    implicitWidth: Style.space(220)
    implicitHeight: list.implicitHeight + Style.space(12)
    width: implicitWidth
    height: implicitHeight
    Rectangle {
        anchors.fill: parent
        radius: Style.cornerRadius
        color: Color.popups.background
        border.width: 1
        border.color: Qt.alpha(Color.popups.text, 0.2)
    }
    Column {
        id: list
        width: parent.width
        height: implicitHeight
        anchors.verticalCenter: parent.verticalCenter
        Repeater {
            model: root.items
            delegate: Item {
                required property var modelData
                required property int index
                width: list.width
                height: modelData.kind === "divider" ? Style.space(9) : label.implicitHeight + Style.space(10)
                Rectangle {
                    visible: modelData.kind === "divider"
                    anchors.centerIn: parent
                    width: parent.width - Style.space(20)
                    height: 1
                    color: Qt.alpha(Color.popups.text, 0.15)
                }
                Rectangle {
                    visible: modelData.kind !== "divider" && rowMouse.containsMouse && modelData.enabled !== false
                    anchors.fill: parent
                    color: Qt.alpha(Color.accent, 0.2)
                }
                Text {
                    id: label
                    visible: modelData.kind !== "divider"
                    anchors.left: parent.left
                    anchors.leftMargin: Style.space(12)
                    anchors.right: caret.left
                    anchors.rightMargin: Style.space(8)
                    anchors.verticalCenter: parent.verticalCenter
                    text: modelData.kind !== "divider" ? modelData.label : ""
                    color: modelData.enabled === false ? Qt.alpha(Color.popups.text, 0.4) : Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight
                }
                Text {
                    id: caret
                    visible: modelData.kind === "submenu"
                    anchors.right: parent.right
                    anchors.rightMargin: Style.space(10)
                    anchors.verticalCenter: parent.verticalCenter
                    text: "›"
                    color: modelData.enabled === false ? Qt.alpha(Color.popups.text, 0.4) : Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.body
                }
                MouseArea {
                    id: rowMouse
                    anchors.fill: parent
                    visible: modelData.kind !== "divider"
                    hoverEnabled: modelData.enabled !== false
                    cursorShape: modelData.enabled === false ? Qt.ArrowCursor : Qt.PointingHandCursor
                    onContainsMouseChanged: {
                        if (containsMouse && modelData.kind === "submenu" && modelData.enabled !== false) {
                            root.openSubmenu = modelData;
                            var p = mapToItem(root, 0, 0);
                            root.openSubY = p.y;
                        } else if (containsMouse) {
                            root.openSubmenu = null;
                        }
                    }
                    onClicked: {
                        if (modelData.kind === "item" && modelData.enabled !== false)
                            root.pick(modelData.id);
                    }
                }
            }
        }
    }
    Item {
        visible: root.openSubmenu !== null
        x: parent.width - 4
        y: root.openSubY - Style.space(6)
        width: Style.space(220)
        height: subList.implicitHeight + Style.space(12)
        Rectangle {
            anchors.fill: parent
            radius: Style.cornerRadius
            color: Color.popups.background
            border.width: 1
            border.color: Qt.alpha(Color.popups.text, 0.2)
        }
        Column {
            id: subList
            width: parent.width
            height: implicitHeight
            anchors.verticalCenter: parent.verticalCenter
            Repeater {
                model: root.openSubmenu && root.openSubmenu.children ? root.openSubmenu.children : []
                delegate: Item {
                    required property var modelData
                    width: subList.width
                    height: subLabel.implicitHeight + Style.space(10)
                    Rectangle {
                        visible: subMouse.containsMouse && modelData.enabled !== false
                        anchors.fill: parent
                        color: Qt.alpha(Color.accent, 0.2)
                    }
                    Text {
                        id: subLabel
                        anchors.left: parent.left
                        anchors.leftMargin: Style.space(12)
                        anchors.right: parent.right
                        anchors.rightMargin: Style.space(12)
                        anchors.verticalCenter: parent.verticalCenter
                        text: modelData.label
                        color: modelData.enabled === false ? Qt.alpha(Color.popups.text, 0.4) : Color.popups.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        elide: Text.ElideRight
                    }
                    MouseArea {
                        id: subMouse
                        anchors.fill: parent
                        hoverEnabled: modelData.enabled !== false
                        cursorShape: modelData.enabled === false ? Qt.ArrowCursor : Qt.PointingHandCursor
                        onClicked: {
                            if (modelData.enabled !== false)
                                root.pick(modelData.id);
                        }
                    }
                }
            }
        }
    }
}
