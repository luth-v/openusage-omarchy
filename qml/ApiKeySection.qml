import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Customize.js" as Customize

// Per-provider API key card (OpenRouter, Z.ai). Write-only: the typed key
// goes straight to the daemon over the stdin pipe and the field clears at
// once. The view only ever sees presence (the status dot and hint), never
// the value — so there is no reveal of a saved key, unlike upstream.
Column {
    id: root
    property string providerId: ""
    property string displayName: ""
    property string status: "none"
    property bool compact: false
    readonly property bool editing: keyInput.activeFocus
    readonly property bool hasKey: Customize.keyStatusSet(root.status)
    signal save(string provider, string value)
    signal clearKey(string provider)
    function reset() {
        keyInput.text = "";
        showInput = false;
        root.open = false;
    }
    property bool open: false
    property bool showInput: false
    width: parent ? parent.width : 0
    spacing: Style.space(6)
    Text {
        x: Style.space(8)
        text: "API Key"
        color: Qt.alpha(Color.popups.text, 0.6)
        font.family: Style.font.family
        font.pixelSize: Style.font.caption
        font.bold: true
    }
    Rectangle {
        width: parent.width
        height: cardColumn.implicitHeight
        radius: Style.cornerRadius
        color: Qt.alpha(Color.popups.text, 0.05)
        Column {
            id: cardColumn
            width: parent.width
            Item {
                width: parent.width
                height: Style.space(44)
                Row {
                    anchors.left: parent.left
                    anchors.leftMargin: Style.space(12)
                    anchors.right: editButton.left
                    anchors.rightMargin: Style.space(8)
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(10)
                    ProviderMark {
                        providerId: root.providerId
                        surface: Color.popups.background
                        fallbackColor: Color.popups.text
                        size: Style.space(18)
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: root.displayName
                        color: Color.popups.text
                        font.family: Style.font.family
                        font.pixelSize: root.compact ? Style.font.bodySmall : Style.font.body
                        font.bold: true
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Rectangle {
                        width: Style.space(6)
                        height: Style.space(6)
                        radius: Style.space(3)
                        anchors.verticalCenter: parent.verticalCenter
                        color: root.hasKey ? Color.accent : Color.urgent
                    }
                }
                TextButton {
                    id: editButton
                    anchors.right: parent.right
                    anchors.rightMargin: Style.space(12)
                    anchors.verticalCenter: parent.verticalCenter
                    width: Style.space(64)
                    height: Style.space(24)
                    text: root.open ? "Done" : (root.hasKey ? "Edit" : "Add")
                    onClicked: {
                        root.open = !root.open;
                        if (!root.open)
                            keyInput.text = "";
                    }
                }
            }
            Rectangle {
                visible: root.open
                width: parent.width
                height: Style.space(1)
                color: Qt.alpha(Color.popups.text, 0.12)
            }
            Column {
                visible: root.open
                width: parent.width - Style.space(24)
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: Style.space(8)
                topPadding: Style.space(10)
                bottomPadding: Style.space(12)
                Text {
                    visible: root.hasKey
                    text: Customize.keyStatusText(root.status)
                    color: Qt.alpha(Color.popups.text, 0.6)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
                Text {
                    visible: !root.hasKey
                    width: parent.width
                    wrapMode: Text.Wrap
                    text: "Add the provider key. A saved key overrides an exported one."
                    color: Qt.alpha(Color.popups.text, 0.6)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
                Row {
                    width: parent.width
                    spacing: Style.space(8)
                    Ui.TextField {
                        id: keyInput
                        width: parent.width - eyeButton.width - parent.spacing
                        placeholderText: "sk-or-v1-…"
                        password: !root.showInput
                        font.pixelSize: Style.font.bodySmall
                        onAccepted: saveButton.commit()
                    }
                    Rectangle {
                        id: eyeButton
                        width: Style.space(30)
                        height: keyInput.implicitHeight
                        radius: Style.space(6)
                        color: Qt.alpha(Color.popups.text, eyeMouse.containsMouse ? 0.14 : 0.08)
                        Text {
                            anchors.centerIn: parent
                            text: root.showInput ? "◉" : "◎"
                            color: Qt.alpha(Color.popups.text, 0.7)
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                        }
                        MouseArea {
                            id: eyeMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.showInput = !root.showInput
                        }
                    }
                }
                Row {
                    spacing: Style.space(8)
                    TextButton {
                        id: saveButton
                        function commit() {
                            var value = keyInput.text.trim();
                            if (value === "")
                                return;
                            root.save(root.providerId, value);
                            keyInput.text = "";
                        }
                        width: Style.space(90)
                        height: Style.space(26)
                        text: root.hasKey ? "Replace" : "Save"
                        primary: true
                        active: keyInput.text.trim() !== ""
                        onClicked: saveButton.commit()
                    }
                    TextButton {
                        visible: root.hasKey && root.status !== "env"
                        width: visible ? Style.space(70) : 0
                        height: Style.space(26)
                        text: "Clear"
                        destructive: true
                        onClicked: {
                            keyInput.text = "";
                            root.clearKey(root.providerId);
                        }
                    }
                }
            }
        }
    }
}
