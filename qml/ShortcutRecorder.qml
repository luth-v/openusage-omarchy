import QtQuick
import qs.Commons
import "../js/Settings.js" as Settings

// Click-to-record global shortcut. Shows the saved combo as chips (or the
// "Record shortcut" hint); the ✕ clears it. While recording, the parent
// must block its key catcher so combos reach this field. Emits the saved
// shell.json string plus the structured daemon payload (or nulls).
Item {
    id: root
    property string saved: ""
    property bool recording: false
    property bool invalidKey: false
    property bool compact: false
    readonly property var parsed: Settings.parseShortcut(root.saved)
    readonly property bool hasCombo: root.parsed !== null
    signal accepted(string text, var combo)
    function stop() {
        root.recording = false;
    }
    function keyName(event) {
        if (event.key >= Qt.Key_F1 && event.key <= Qt.Key_F12)
            return "F" + (event.key - Qt.Key_F1 + 1);
        if (event.text && /^[A-Za-z0-9]$/.test(event.text))
            return event.text.toUpperCase();
        var names = {};
        names[Qt.Key_Delete] = "Delete";
        names[Qt.Key_Backspace] = "Backspace";
        names[Qt.Key_Tab] = "Tab";
        names[Qt.Key_Space] = "Space";
        names[Qt.Key_Home] = "Home";
        names[Qt.Key_End] = "End";
        names[Qt.Key_PageUp] = "PageUp";
        names[Qt.Key_PageDown] = "PageDown";
        return names[event.key] || null;
    }
    implicitWidth: Style.space(180)
    implicitHeight: Style.space(28)
    width: implicitWidth
    height: implicitHeight
    Rectangle {
        anchors.fill: parent
        radius: Style.space(6)
        color: Qt.alpha(Color.popups.text, root.recording ? 0.14 : 0.08)
        border.width: root.recording ? 1 : 0
        border.color: Color.accent
        Text {
            id: hintLabel
            visible: !root.recording && !root.hasCombo
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            text: "Record shortcut"
            color: Qt.alpha(Color.popups.text, 0.5)
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
        }
        Text {
            visible: root.recording
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
            anchors.verticalCenter: parent.verticalCenter
            text: root.invalidKey ? "Unsupported key" : "Press a combo…"
            color: Color.accent
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
        }
        Text {
            visible: !root.recording && root.hasCombo
            anchors.left: parent.left
            anchors.leftMargin: Style.space(8)
            anchors.right: clearBox.left
            anchors.rightMargin: Style.space(4)
            anchors.verticalCenter: parent.verticalCenter
            elide: Text.ElideRight
            text: root.saved
            color: Color.popups.text
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
        }
        Item {
            id: clearBox
            visible: root.hasCombo && !root.recording
            anchors.right: parent.right
            anchors.rightMargin: Style.space(4)
            anchors.verticalCenter: parent.verticalCenter
            width: visible ? Style.space(20) : 0
            height: Style.space(20)
            Text {
                anchors.centerIn: parent
                text: "✕"
                color: Qt.alpha(Color.popups.text, clearMouse.containsMouse ? 0.9 : 0.5)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
            MouseArea {
                id: clearMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.accepted("", null)
            }
        }
        MouseArea {
            anchors.fill: parent
            enabled: !root.recording && !clearMouse.containsMouse
            cursorShape: Qt.PointingHandCursor
            onClicked: {
                root.recording = true;
                root.invalidKey = false;
                keys.forceActiveFocus();
            }
        }
    }
    Item {
        id: keys
        anchors.fill: parent
        focus: root.recording
        Keys.onPressed: function(event) {
            if (!root.recording)
                return;
            if (event.key === Qt.Key_Escape) {
                root.recording = false;
                event.accepted = true;
                return;
            }
            var mods = [];
            if (event.modifiers & Qt.MetaModifier)
                mods.push("SUPER");
            if (event.modifiers & Qt.ShiftModifier)
                mods.push("SHIFT");
            if (event.modifiers & Qt.ControlModifier)
                mods.push("CTRL");
            if (event.modifiers & Qt.AltModifier)
                mods.push("ALT");
            var name = root.keyName(event);
            if (mods.length === 0 || !name || !Settings.validShortcutKey(name)) {
                root.invalidKey = true;
                event.accepted = true;
                return;
            }
            var combo = Settings.shortcutPayload(mods, name);
            if (!combo) {
                root.invalidKey = true;
                event.accepted = true;
                return;
            }
            root.recording = false;
            root.accepted(Settings.formatShortcut(mods, name), combo);
            event.accepted = true;
        }
    }
}
