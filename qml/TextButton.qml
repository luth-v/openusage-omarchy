import QtQuick
import qs.Commons

// Small popup button: plain, primary (accent fill) or destructive (urgent).
// The parent sets width and height; inactive buttons ignore clicks.
Rectangle {
    id: root
    property string text: ""
    property bool primary: false
    property bool destructive: false
    property bool active: true
    signal clicked()
    radius: Style.space(6)
    color: {
        if (!root.active)
            return Qt.alpha(Color.popups.text, 0.06);
        if (root.primary)
            return Color.accent;
        if (root.destructive)
            return Qt.alpha(Color.urgent, hover.containsMouse ? 0.2 : 0.1);
        return Qt.alpha(Color.popups.text, hover.containsMouse ? 0.14 : 0.08);
    }
    Text {
        anchors.centerIn: parent
        text: root.text
        color: {
            if (!root.active)
                return Qt.alpha(Color.popups.text, 0.5);
            if (root.primary)
                return Color.background;
            if (root.destructive)
                return Color.urgent;
            return Color.popups.text;
        }
        font.family: Style.font.family
        font.pixelSize: Style.font.bodySmall
        font.bold: root.primary
    }
    MouseArea {
        id: hover
        anchors.fill: parent
        hoverEnabled: root.active
        cursorShape: root.active ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: {
            if (root.active)
                root.clicked();
        }
    }
}
