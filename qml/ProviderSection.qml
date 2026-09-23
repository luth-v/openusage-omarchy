import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Drag.js" as Drag

// One provider group: header with grip, mark, plan and status chrome,
// then the group's metric rows. Collapse hides the rows. The header grip
// drags the section; a hover grip on each row drags it within the card
// (across the caret while open, via the moveMetric reducer rule).
Item {
    id: root
    property var section: null
    property var claimResult: null
    property color warningColor: Color.accent
    property bool compact: false
    property bool reduceMotion: false
    property bool dropHover: false
    property var partyFill: null
    property Item menuLayer: null
    property string dragMetricId: ""
    property string hoverMetricId: ""
    signal toggleCollapse()
    signal toggleDisplay(string rowId)
    signal toggleReset(string rowId)
    signal rowMenu(var row, string cardId, real x, real y)
    signal headerMenu(real x, real y)
    signal claim(string cardId, string iso, string requestId)
    signal sectionDragStart(string cardId)
    signal sectionDragMove(var mouseItem, real x, real y)
    signal sectionDragEnd()
    signal sectionDragCancel()
    signal rowDragStart(string metricId)
    signal rowDragMove(var mouseItem, real x, real y)
    signal rowDragEnd()
    signal rowDragCancel()
    signal moveMetric(string dragged, string target)
    function rowGeometries() {
        var out = [];
        for (var i = 0; i < rowsRep.count; i++) {
            var row = rowsRep.itemAt(i);
            if (row)
                out.push({id: row.metricId, top: row.y, bottom: row.y + row.height});
        }
        return out;
    }
    function rowMove(metricId, mouseItem, x, y) {
        if (root.dragMetricId !== metricId)
            return;
        var p = mouseItem.mapToItem(rowsColumn, x, y);
        root.hoverMetricId = Drag.dropTarget(root.rowGeometries(), p.y, metricId) || "";
    }
    function rowEnd(metricId) {
        var target = root.hoverMetricId;
        root.dragMetricId = "";
        root.hoverMetricId = "";
        root.rowDragEnd();
        if (target !== "" && target !== metricId)
            root.moveMetric(metricId, target);
    }
    readonly property bool collapsed: root.section ? (root.section.showCaret && !root.section.isExpanded) : false
    readonly property var rows: {
        if (!root.section)
            return [];
        return root.section.always.concat(root.section.isExpanded ? root.section.expanded : []);
    }
    implicitHeight: column.implicitHeight
    height: implicitHeight
    width: parent ? parent.width : 0
    Column {
        id: column
        width: parent.width
        spacing: 0
        Item {
            id: header
            width: parent.width
            height: Math.max(Style.space(28), headerRow.implicitHeight) + Style.space(6)
            Rectangle {
                visible: root.dropHover
                anchors.fill: parent
                anchors.margins: Style.space(2)
                radius: Style.space(6)
                color: "transparent"
                border.width: 1
                border.color: Color.accent
            }
            MouseArea {
                anchors.fill: parent
                acceptedButtons: Qt.RightButton
                onClicked: function(mouse) {
                    if (root.menuLayer && root.section) {
                        var p = mapToItem(root.menuLayer, mouse.x, mouse.y);
                        root.headerMenu(p.x, p.y);
                    }
                }
            }
            Row {
                id: headerRow
                anchors.left: parent.left
                anchors.leftMargin: Style.space(10)
                anchors.right: parent.right
                anchors.rightMargin: Style.space(10)
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(6)
                // Drag grip: six dots, visual only in this pass.
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
                        id: sectionGripMouse
                        anchors.fill: parent
                        anchors.margins: -Style.space(6)
                        cursorShape: Qt.SizeVerCursor
                        preventStealing: true
                        onPressed: root.sectionDragStart(root.section ? root.section.cardId : "")
                        onPositionChanged: function(mouse) {
                            root.sectionDragMove(sectionGripMouse, mouse.x, mouse.y);
                        }
                        onReleased: root.sectionDragEnd()
                        onCanceled: root.sectionDragCancel()
                    }
                }
                MouseArea {
                    id: headClick
                    width: headRow.implicitWidth
                    height: Math.max(grip.height, headRow.implicitHeight)
                    acceptedButtons: root.section && root.section.showCaret ? Qt.LeftButton : Qt.NoButton
                    cursorShape: root.section && root.section.showCaret ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.toggleCollapse()
                    Row {
                        id: headRow
                        spacing: Style.space(8)
                        anchors.verticalCenter: parent.verticalCenter
                        ProviderMark {
                            providerId: root.section ? root.section.family : ""
                            surface: Color.popups.background
                            fallbackColor: Color.popups.text
                            size: 24
                            party: root.partyFill !== null && root.partyFill !== undefined
                            reduceMotion: root.reduceMotion
                            anchors.verticalCenter: parent.verticalCenter
                        }
                        Row {
                            spacing: Style.space(4)
                            anchors.verticalCenter: parent.verticalCenter
                            Text {
                                text: root.section ? root.section.label : ""
                                color: Color.popups.text
                                font.family: Style.font.family
                                font.pixelSize: Style.font.body
                                font.bold: true
                                anchors.verticalCenter: parent.verticalCenter
                            }
                            Text {
                                visible: text !== ""
                                text: root.section && root.section.plan ? root.section.plan : ""
                                color: Qt.alpha(Color.popups.text, 0.6)
                                font.family: Style.font.family
                                font.pixelSize: Style.font.bodySmall
                                anchors.verticalCenter: parent.verticalCenter
                            }
                        }
                    }
                }
                Item {
                    width: Math.max(8, parent.width - grip.width - headClick.width - statusRow.width - caretBox.width - parent.spacing * 4)
                    height: 1
                }
                Row {
                    id: statusRow
                    spacing: Style.space(6)
                    height: implicitHeight
                    anchors.verticalCenter: parent.verticalCenter
                    Text {
                        visible: root.section && root.section.staleness !== null
                        text: root.section && root.section.staleness ? root.section.staleness.label : ""
                        color: root.warningColor
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        anchors.verticalCenter: parent.verticalCenter
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: root.section && root.section.staleness !== null
                            acceptedButtons: Qt.NoButton
                            Ui.PanelToolTip {
                                visible: parent.containsMouse && root.section && root.section.staleness !== null
                                text: root.section && root.section.staleness ? root.section.staleness.tooltip : ""
                            }
                        }
                    }
                    Rectangle {
                        id: spinner
                        visible: root.section && root.section.refreshing
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
                            running: spinner.visible && !root.reduceMotion
                            loops: Animation.Infinite
                            duration: 800
                            from: 0
                            to: 360
                        }
                    }
                    Canvas {
                        visible: root.section && root.section.warning
                        width: Style.space(14)
                        height: Style.space(12)
                        anchors.verticalCenter: parent.verticalCenter
                        onPaint: {
                            var ctx = getContext("2d");
                            ctx.clearRect(0, 0, width, height);
                            ctx.beginPath();
                            ctx.moveTo(width / 2, 1);
                            ctx.lineTo(width - 1, height - 1);
                            ctx.lineTo(1, height - 1);
                            ctx.closePath();
                            ctx.fillStyle = root.warningColor.toString();
                            ctx.fill();
                            ctx.fillStyle = Color.popups.background.toString();
                            ctx.fillRect(width / 2 - 1, height * 0.35, 2, height * 0.3);
                            ctx.fillRect(width / 2 - 1, height * 0.72, 2, 2);
                        }
                        MouseArea {
                            anchors.fill: parent
                            hoverEnabled: true
                            acceptedButtons: Qt.NoButton
                            Ui.PanelToolTip {
                                visible: parent.containsMouse
                                text: root.section && root.section.warning ? root.section.warning : ""
                            }
                        }
                    }
                }
                Item {
                    id: caretBox
                    visible: root.section && root.section.showCaret
                    width: visible ? Style.space(20) : 0
                    height: Style.space(20)
                    anchors.verticalCenter: parent.verticalCenter
                    Canvas {
                        anchors.centerIn: parent
                        width: Style.space(10)
                        height: Style.space(6)
                        rotation: root.collapsed ? 180 : 0
                        onPaint: {
                            var ctx = getContext("2d");
                            ctx.clearRect(0, 0, width, height);
                            ctx.beginPath();
                            ctx.moveTo(1, height - 1);
                            ctx.lineTo(width / 2, 1);
                            ctx.lineTo(width - 1, height - 1);
                            ctx.closePath();
                            ctx.fillStyle = Qt.alpha(Color.popups.text, 0.65).toString();
                            ctx.fill();
                        }
                    }
                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: root.toggleCollapse()
                    }
                }
            }
        }
        Item {
            width: parent.width
            height: collapsed ? 0 : rowsColumn.implicitHeight
            visible: !collapsed
            clip: true
            Column {
                id: rowsColumn
                width: parent.width
                Repeater {
                    id: rowsRep
                    model: root.rows
                    MetricRow {
                        width: rowsColumn.width
                        row: modelData
                        cardId: root.section ? root.section.cardId : ""
                        warningColor: root.warningColor
                        compact: root.compact
                        partyFill: root.partyFill
                        claimResult: root.claimResult
                        menuLayer: root.menuLayer
                        dropHover: root.hoverMetricId === modelData.metricId
                        dimmed: root.dragMetricId !== "" && root.dragMetricId === modelData.metricId
                        onToggleDisplay: root.toggleDisplay(modelData.metricId)
                        onToggleReset: root.toggleReset(modelData.metricId)
                        onRowMenu: function(r, c, x, y) { root.rowMenu(r, c, x, y); }
                        onClaim: function(c, iso, req) { root.claim(c, iso, req); }
                        onRowDragStart: function(metricId) {
                            root.dragMetricId = metricId;
                            root.hoverMetricId = "";
                            root.rowDragStart(metricId);
                        }
                        onRowDragMove: function(metricId, mouseItem, x, y) {
                            root.rowMove(metricId, mouseItem, x, y);
                        }
                        onRowDragEnd: function(metricId) { root.rowEnd(metricId); }
                        onRowDragCancel: {
                            root.dragMetricId = "";
                            root.hoverMetricId = "";
                            root.rowDragCancel();
                        }
                    }
                }
            }
        }
        Row {
            visible: !root.collapsed && root.section && root.section.links && root.section.links.length > 0
            width: parent.width - Style.space(28)
            height: implicitHeight
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Style.space(12)
            bottomPadding: Style.space(6)
            Repeater {
                model: (root.section && root.section.links) ? root.section.links.slice(0, 3) : []
                Text {
                    text: modelData.label
                    color: Qt.alpha(Color.popups.text, 0.6)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.underline: linkMouse.containsMouse
                    MouseArea {
                        id: linkMouse
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: Qt.openUrlExternally(modelData.url)
                    }
                }
            }
        }
    }
}
