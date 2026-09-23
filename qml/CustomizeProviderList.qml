import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Drag.js" as Drag

// Customize provider list: every card in layout order, on or off. Tapping
// a row (but not its grip or toggle) opens the detail; enabled rows drag
// by the grip. Drag math lives in Drag.js; this only maps pointers.
Column {
    id: root
    property var rows: []
    property bool compact: false
    property var flick: null
    property string dragId: ""
    property string hoverId: ""
    signal toggleCard(string cardId, bool enabled)
    signal openCard(string cardId)
    signal moveCard(string dragged, string target)
    function geometries() {
        var out = [];
        for (var i = 0; i < rowRep.count; i++) {
            var item = rowRep.itemAt(i);
            if (item && item.rowEnabled)
                out.push({id: item.cardId, top: item.y, bottom: item.y + item.height});
        }
        return out;
    }
    width: parent ? parent.width : 0
    Rectangle {
        width: parent.width
        height: listColumn.implicitHeight
        radius: Style.cornerRadius
        color: Qt.alpha(Color.popups.text, 0.05)
        Column {
            id: listColumn
            width: parent.width
            Repeater {
                id: rowRep
                model: root.rows
                delegate: Item {
                    required property var modelData
                    property string cardId: modelData.cardId
                    property bool rowEnabled: !!modelData.enabled
                    width: listColumn.width
                    height: Style.space(48)
                    opacity: root.dragId === cardId ? 0.5 : (rowEnabled ? 1 : 0.55)
                    Rectangle {
                        visible: root.hoverId === cardId
                        anchors.fill: parent
                        anchors.margins: Style.space(2)
                        radius: Style.space(6)
                        color: "transparent"
                        border.width: 1
                        border.color: Color.accent
                    }
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: Style.space(12)
                        anchors.rightMargin: Style.space(12)
                        spacing: Style.space(10)
                        Item {
                            id: grip
                            width: Style.space(10)
                            height: Style.space(16)
                            anchors.verticalCenter: parent.verticalCenter
                            opacity: rowEnabled ? 0.5 : 0.25
                            Repeater {
                                model: 6
                                Rectangle {
                                    required property int index
                                    width: 2
                                    height: 2
                                    radius: 1
                                    color: Color.popups.text
                                    x: (index % 2) * 4 + 1
                                    y: Math.floor(index / 2) * 5 + 1
                                }
                            }
                            MouseArea {
                                id: gripMouse
                                anchors.fill: parent
                                anchors.margins: -Style.space(6)
                                enabled: rowEnabled
                                cursorShape: Qt.SizeVerCursor
                                preventStealing: true
                                onPressed: {
                                    root.dragId = cardId;
                                    root.hoverId = "";
                                    if (root.flick)
                                        root.flick.interactive = false;
                                }
                                onPositionChanged: function(mouse) {
                                    if (root.dragId !== cardId)
                                        return;
                                    var p = gripMouse.mapToItem(listColumn, mouse.x, mouse.y);
                                    root.hoverId = Drag.dropTarget(root.geometries(), p.y, cardId) || "";
                                }
                                onReleased: {
                                    if (root.flick)
                                        root.flick.interactive = true;
                                    var target = root.hoverId;
                                    root.dragId = "";
                                    root.hoverId = "";
                                    if (target !== "" && target !== cardId)
                                        root.moveCard(cardId, target);
                                }
                                onCanceled: {
                                    if (root.flick)
                                        root.flick.interactive = true;
                                    root.dragId = "";
                                    root.hoverId = "";
                                }
                            }
                        }
                        Item {
                            width: parent.width - grip.width - toggleBox.width - chevron.width - parent.spacing * 3
                            height: parent.height
                            Row {
                                anchors.verticalCenter: parent.verticalCenter
                                spacing: Style.space(10)
                                ProviderMark {
                                    providerId: modelData.family
                                    surface: Color.popups.background
                                    fallbackColor: Color.popups.text
                                    size: Style.space(18)
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Column {
                                    spacing: 0
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        text: modelData.displayName
                                        color: Color.popups.text
                                        font.family: Style.font.family
                                        font.pixelSize: root.compact ? Style.font.bodySmall : Style.font.body
                                        font.bold: true
                                    }
                                    Text {
                                        text: modelData.metricCount + " metrics"
                                        color: Qt.alpha(Color.popups.text, 0.6)
                                        font.family: Style.font.family
                                        font.pixelSize: Style.font.caption
                                    }
                                }
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.openCard(cardId)
                            }
                        }
                        Item {
                            id: toggleBox
                            width: toggleSwitch.implicitWidth
                            height: parent.height
                            Ui.ToggleSwitch {
                                id: toggleSwitch
                                width: implicitWidth
                                height: implicitHeight
                                checked: rowEnabled
                                anchors.verticalCenter: parent.verticalCenter
                                onToggled: root.toggleCard(cardId, !rowEnabled)
                            }
                        }
                        Item {
                            id: chevron
                            width: Style.space(16)
                            height: parent.height
                            Text {
                                anchors.centerIn: parent
                                text: "›"
                                color: Qt.alpha(Color.popups.text, 0.5)
                                font.family: Style.font.family
                                font.pixelSize: Style.font.title
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.openCard(cardId)
                            }
                        }
                    }
                }
            }
        }
    }
}
