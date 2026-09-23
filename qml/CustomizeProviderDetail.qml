import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Customize.js" as Customize
import "../js/Drag.js" as Drag

// One provider's metrics: Always Visible and On Demand cards. Rows carry
// grip, name, star and toggle; dragging a row onto the other card's rows
// (or its empty drop zone) moves it across. Dimmed but editable when the
// card is off, as upstream.
Column {
    id: root
    property var detail: null
    property var stars: []
    property bool cardEnabled: true
    property bool compact: false
    property bool reduceMotion: false
    property var flick: null
    property string dragId: ""
    property string hoverId: ""
    property string hoverZone: ""
    signal toggleMetric(string metricId, bool enabled)
    signal toggleStar(string metricId)
    signal moveMetric(string dragged, string target)
    signal moveToSection(string metricId, string section)
    function geometries() {
        var out = [];
        for (var s = 0; s < sectionRep.count; s++) {
            var sec = sectionRep.itemAt(s);
            if (!sec)
                continue;
            for (var i = 0; i < sec.rowsCount; i++) {
                var row = sec.rowItem(i);
                if (!row)
                    continue;
                var p = row.mapToItem(root, 0, 0);
                out.push({id: row.metricId, top: p.y, bottom: p.y + row.height});
            }
        }
        return out;
    }
    function zones() {
        var out = [];
        for (var s = 0; s < sectionRep.count; s++) {
            var sec = sectionRep.itemAt(s);
            if (!sec || sec.rowsCount > 0 || !sec.zoneItem)
                continue;
            var p = sec.zoneItem.mapToItem(root, 0, 0);
            out.push({id: sec.sectionId, top: p.y, bottom: p.y + sec.zoneItem.height});
        }
        return out;
    }
    function dragMove(metricId, mouse, mouseItem) {
        if (root.dragId !== metricId)
            return;
        var p = mouseItem.mapToItem(root, mouse.x, mouse.y);
        root.hoverZone = Drag.zoneAt(root.zones(), p.y) || "";
        root.hoverId = root.hoverZone === "" ? Drag.dropTarget(root.geometries(), p.y, metricId) || "" : "";
    }
    function dragEnd(metricId) {
        if (root.flick)
            root.flick.interactive = true;
        var zone = root.hoverZone;
        var target = root.hoverId;
        root.dragId = "";
        root.hoverId = "";
        root.hoverZone = "";
        if (zone !== "")
            root.moveToSection(metricId, zone);
        else if (target !== "" && target !== metricId)
            root.moveMetric(metricId, target);
    }
    width: parent ? parent.width : 0
    spacing: Style.space(12)
    opacity: root.cardEnabled ? 1 : 0.6
    Repeater {
        id: sectionRep
        model: [
            {title: "Always Visible", section: "alwaysVisible", rows: root.detail ? root.detail.always : []},
            {title: "On Demand", section: "onDemand", rows: root.detail ? root.detail.onDemand : []}
        ]
        delegate: Column {
            required property var modelData
            property string sectionId: modelData.section
            property int rowsCount: innerRep.count
            property Item zoneItem: zone
            function rowItem(i) {
                return innerRep.itemAt(i);
            }
            width: root.width
            spacing: Style.space(6)
            Text {
                x: Style.space(8)
                text: modelData.title
                color: Qt.alpha(Color.popups.text, 0.6)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                font.bold: true
            }
            Rectangle {
                width: parent.width
                height: sectionColumn.implicitHeight
                radius: Style.cornerRadius
                color: Qt.alpha(Color.popups.text, 0.05)
                Column {
                    id: sectionColumn
                    width: parent.width
                    Item {
                        id: zone
                        visible: innerRep.count === 0
                        width: parent.width - Style.space(16)
                        anchors.horizontalCenter: parent.horizontalCenter
                        height: visible ? Style.space(46) : 0
                        y: Style.space(8)
                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                var ctx = getContext("2d");
                                ctx.clearRect(0, 0, width, height);
                                ctx.setLineDash([3, 3]);
                                ctx.strokeStyle = Qt.alpha(Color.popups.text, 0.4).toString();
                                ctx.lineWidth = 1;
                                ctx.beginPath();
                                if (ctx.roundRect)
                                    ctx.roundRect(1, 1, width - 2, height - 2, 8);
                                else
                                    ctx.rect(1, 1, width - 2, height - 2);
                                ctx.stroke();
                            }
                        }
                        Rectangle {
                            visible: root.hoverZone === sectionId
                            anchors.fill: parent
                            radius: 8
                            color: "transparent"
                            border.width: 1
                            border.color: Color.accent
                        }
                        Text {
                            anchors.centerIn: parent
                            text: Customize.EMPTY_ZONE_TEXT
                            color: Qt.alpha(Color.popups.text, 0.5)
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }
                    }
                    Repeater {
                        id: innerRep
                        model: modelData.rows
                        delegate: Item {
                            required property var modelData
                            property string metricId: modelData.metricId
                            width: sectionColumn.width
                            height: Style.space(38)
                            opacity: root.dragId === metricId ? 0.5 : 1
                            Rectangle {
                                visible: root.hoverId === metricId
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
                                    opacity: 0.5
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
                                        cursorShape: Qt.SizeVerCursor
                                        preventStealing: true
                                        onPressed: {
                                            root.dragId = metricId;
                                            root.hoverId = "";
                                            root.hoverZone = "";
                                            if (root.flick)
                                                root.flick.interactive = false;
                                        }
                                        onPositionChanged: function(mouse) {
                                            root.dragMove(metricId, mouse, gripMouse);
                                        }
                                        onReleased: root.dragEnd(metricId)
                                        onCanceled: {
                                            if (root.flick)
                                                root.flick.interactive = true;
                                            root.dragId = "";
                                            root.hoverId = "";
                                            root.hoverZone = "";
                                        }
                                    }
                                }
                                Text {
                                    text: modelData.title
                                    color: modelData.enabled ? Color.popups.text : Qt.alpha(Color.popups.text, 0.5)
                                    font.family: Style.font.family
                                    font.pixelSize: root.compact ? Style.font.bodySmall : Style.font.body
                                    elide: Text.ElideRight
                                    width: parent.width - grip.width - starBox.width - toggleBox.width - parent.spacing * 3
                                    anchors.verticalCenter: parent.verticalCenter
                                }
                                Item {
                                    id: starBox
                                    width: Style.space(22)
                                    height: Style.space(22)
                                    anchors.verticalCenter: parent.verticalCenter
                                    Text {
                                        visible: modelData.starrable
                                        anchors.centerIn: parent
                                        text: modelData.starred ? "★" : "☆"
                                        color: modelData.starred ? Color.accent : Qt.alpha(Color.popups.text, 0.55)
                                        font.family: Style.font.family
                                        font.pixelSize: Style.font.body
                                    }
                                    SequentialAnimation {
                                        id: shakeAnim
                                        NumberAnimation {
                                            target: starBox
                                            property: "x"
                                            from: 0
                                            to: -4
                                            duration: 40
                                        }
                                        NumberAnimation {
                                            target: starBox
                                            property: "x"
                                            from: -4
                                            to: 4
                                            duration: 60
                                        }
                                        NumberAnimation {
                                            target: starBox
                                            property: "x"
                                            from: 4
                                            to: -3
                                            duration: 60
                                        }
                                        NumberAnimation {
                                            target: starBox
                                            property: "x"
                                            from: -3
                                            to: 0
                                            duration: 50
                                        }
                                    }
                                    MouseArea {
                                        anchors.fill: parent
                                        visible: modelData.starrable
                                        cursorShape: Qt.PointingHandCursor
                                        onClicked: {
                                            if (!root.reduceMotion && Customize.starDeniedPreview(root.stars, metricId, modelData.starrable))
                                                shakeAnim.start();
                                            root.toggleStar(metricId);
                                        }
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
                                        checked: !!modelData.enabled
                                        anchors.verticalCenter: parent.verticalCenter
                                        onToggled: root.toggleMetric(metricId, !modelData.enabled)
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
    }
}
