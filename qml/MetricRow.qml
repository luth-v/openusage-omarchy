import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Theme.js" as Theme

// One metric row: bounded meter, unbounded value, or Usage Trend chart.
// Clicking the headline flips Used/Left; clicking a reset label flips the
// countdown format; clicking an interactive value expands its detail.
Item {
    id: root
    property var row: null
    property string cardId: ""
    property color warningColor: Color.accent
    property bool compact: false
    property var claimResult: null
    property Item menuLayer: null
    property bool dropHover: false
    property bool dimmed: false
    property var partyFill: null
    readonly property string metricId: root.row && root.row.metricId ? root.row.metricId : ""
    signal toggleDisplay()
    signal toggleReset()
    signal rowMenu(var row, string cardId, real x, real y)
    signal claim(string cardId, string iso, string requestId)
    signal rowDragStart(string metricId)
    signal rowDragMove(string metricId, var mouseItem, real x, real y)
    signal rowDragEnd(string metricId)
    signal rowDragCancel(string metricId)
    property bool detailOpen: false
    readonly property bool isMeter: root.row && root.row.layout === "meter"
    readonly property bool isChart: root.row && root.row.layout === "chart"
    readonly property real topPad: {
        if (root.isMeter)
            return root.compact ? Style.space(8) : Style.space(10);
        if (root.row && root.row.condensedTop)
            return root.compact ? Style.space(2) : Style.space(4);
        return root.compact ? Style.space(6) : Style.space(8);
    }
    readonly property real bottomPad: root.isMeter ? (root.compact ? Style.space(8) : Style.space(10)) : (root.compact ? Style.space(6) : Style.space(8))
    function severityColor(severity) {
        return Theme.meterColor(severity, {accent: Color.accent, warning: root.warningColor, urgent: Color.urgent});
    }
    implicitHeight: body.implicitHeight + root.topPad + root.bottomPad
    height: implicitHeight
    width: parent ? parent.width : 0
    opacity: root.dimmed ? 0.5 : 1
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
        id: rowMouse
        anchors.fill: parent
        hoverEnabled: true
        acceptedButtons: Qt.RightButton
        onClicked: function(mouse) {
            if (root.menuLayer) {
                var p = mapToItem(root.menuLayer, mouse.x, mouse.y);
                root.rowMenu(root.row, root.cardId, p.x, p.y);
            }
        }
    }
    Item {
        id: rowGrip
        anchors.left: parent.left
        anchors.leftMargin: Style.space(2)
        anchors.verticalCenter: parent.verticalCenter
        width: Style.space(10)
        height: Style.space(16)
        opacity: rowMouse.containsMouse ? 0.5 : 0
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
            id: rowGripMouse
            anchors.fill: parent
            anchors.margins: -Style.space(4)
            cursorShape: Qt.SizeVerCursor
            preventStealing: true
            onPressed: root.rowDragStart(root.metricId)
            onPositionChanged: function(mouse) {
                root.rowDragMove(root.metricId, rowGripMouse, mouse.x, mouse.y);
            }
            onReleased: root.rowDragEnd(root.metricId)
            onCanceled: root.rowDragCancel(root.metricId)
        }
    }
    Column {
        id: body
        width: parent.width - Style.space(28)
        anchors.horizontalCenter: parent.horizontalCenter
        y: root.topPad
        spacing: root.isMeter ? Style.space(6) : Style.space(4)
        // Meter label row: title plus the escalating pace note.
        Row {
            visible: root.isMeter
            width: parent.width
            height: implicitHeight
            spacing: Style.space(6)
            Text {
                text: root.row ? root.row.title : ""
                color: Color.popups.text
                font.family: Style.font.family
                font.pixelSize: root.compact ? Style.font.bodySmall : Style.font.body
                font.bold: true
                elide: Text.ElideRight
                width: Math.max(40, parent.width - noteBox.width - parent.spacing)
            }
            Item {
                id: noteBox
                width: noteRow.implicitWidth
                height: noteRow.implicitHeight
                anchors.verticalCenter: parent.verticalCenter
                Row {
                    id: noteRow
                    spacing: 3
                    Canvas {
                        id: flame
                        visible: root.row && root.row.note && root.row.note.tone === "flame"
                        width: Style.space(10)
                        height: Style.space(12)
                        anchors.verticalCenter: parent.verticalCenter
                        onPaint: {
                            var ctx = getContext("2d");
                            ctx.clearRect(0, 0, width, height);
                            ctx.beginPath();
                            ctx.moveTo(width * 0.5, height * 0.02);
                            ctx.bezierCurveTo(width * 0.62, height * 0.3, width * 0.86, height * 0.45, width * 0.86, height * 0.68);
                            ctx.bezierCurveTo(width * 0.86, height * 0.9, width * 0.68, height, width * 0.5, height);
                            ctx.bezierCurveTo(width * 0.32, height, width * 0.14, height * 0.9, width * 0.14, height * 0.68);
                            ctx.bezierCurveTo(width * 0.14, height * 0.5, width * 0.3, height * 0.42, width * 0.34, height * 0.28);
                            ctx.bezierCurveTo(width * 0.36, height * 0.2, width * 0.42, height * 0.1, width * 0.5, height * 0.02);
                            ctx.fillStyle = Color.urgent.toString();
                            ctx.fill();
                        }
                    }
                    Text {
                        visible: root.row && root.row.note && root.row.note.text !== null && root.row.note.text !== undefined
                        text: root.row && root.row.note && root.row.note.text ? root.row.note.text : ""
                        color: Qt.alpha(Color.popups.text, 0.65)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: root.row && root.row.note && root.row.note.tip !== null
                    cursorShape: root.row && root.row.note && root.row.note.action ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: {
                        if (root.row && root.row.note && root.row.note.action)
                            root.toggleReset();
                    }
                    Ui.PanelToolTip {
                        visible: parent.containsMouse && root.row && root.row.note && root.row.note.tip
                        text: root.row && root.row.note && root.row.note.tip ? root.row.note.tip : ""
                    }
                }
            }
        }
        Meter {
            visible: root.isMeter
            width: parent.width
            fraction: root.row && root.row.meter ? root.row.meter.fraction : 0
            fill: root.partyFill !== null && root.partyFill !== undefined ? root.partyFill : (root.row && root.row.meter ? root.severityColor(root.row.meter.severity) || Color.accent : Color.accent)
            hasData: root.row ? !!root.row.hasData : false
            tick: root.row && root.row.meter ? root.row.meter.tick : null
            tip: root.row && root.row.meter && root.row.meter.tip ? root.row.meter.tip : ""
        }
        // Meter primary row: headline plus reset context.
        Row {
            visible: root.isMeter
            width: parent.width
            height: implicitHeight
            spacing: Style.space(8)
            Text {
                id: headline
                text: root.row ? root.row.headline : ""
                color: Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: root.row && root.row.headlineToggle
                    acceptedButtons: root.row && root.row.headlineToggle ? Qt.LeftButton : Qt.NoButton
                    cursorShape: root.row && root.row.headlineToggle ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.toggleDisplay()
                    Ui.PanelToolTip {
                        visible: parent.containsMouse && root.row && root.row.headlineTip
                        text: root.row && root.row.headlineTip ? root.row.headlineTip : ""
                    }
                }
            }
            Item {
                width: Math.max(8, parent.width - headline.implicitWidth - trailing.implicitWidth - parent.spacing * 2)
                height: 1
            }
            Text {
                id: trailing
                visible: text !== ""
                text: root.row && root.row.trailing ? root.row.trailing : ""
                color: Qt.alpha(Color.popups.text, 0.65)
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: root.row && !!root.row.trailingTip
                    acceptedButtons: root.row && root.row.trailingToggle ? Qt.LeftButton : Qt.NoButton
                    cursorShape: root.row && root.row.trailingToggle ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.toggleReset()
                    Ui.PanelToolTip {
                        visible: parent.containsMouse && root.row && root.row.trailingTip
                        text: root.row && root.row.trailingTip ? root.row.trailingTip : ""
                    }
                }
            }
        }
        // Unbounded row: label plus interactive value.
        Row {
            visible: !root.isMeter && !root.isChart
            width: parent.width
            height: implicitHeight
            spacing: Style.space(10)
            Row {
                spacing: Style.space(4)
                height: implicitHeight
                anchors.verticalCenter: parent.verticalCenter
                Text {
                    text: root.row ? root.row.title : ""
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                    anchors.verticalCenter: parent.verticalCenter
                }
                Canvas {
                    visible: root.row && root.row.unknown !== null
                    width: Style.space(12)
                    height: Style.space(11)
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
                            text: root.row && root.row.unknown ? root.row.unknown.tip : ""
                        }
                    }
                }
            }
            Item {
                width: Math.max(12, parent.width - parent.children[0].implicitWidth - valueBox.width - parent.spacing * 2)
                height: 1
            }
            Item {
                id: valueBox
                width: valueColumn.implicitWidth + (root.row && root.row.interactive ? Style.space(14) : 0)
                height: valueColumn.implicitHeight + (root.row && root.row.interactive ? Style.space(8) : 0)
                anchors.verticalCenter: parent.verticalCenter
                Rectangle {
                    anchors.fill: parent
                    radius: 6
                    color: Qt.alpha(Color.popups.text, 0.08)
                    opacity: valueMouse.containsMouse || root.detailOpen ? 1 : 0
                }
                Column {
                    id: valueColumn
                    anchors.centerIn: parent
                    spacing: 2
                    Row {
                        spacing: Style.space(4)
                        height: implicitHeight
                        anchors.right: parent.right
                        Rectangle {
                            visible: root.row && root.row.resets && root.row.resets.entries.length > 0
                            width: 6
                            height: 6
                            radius: 3
                            anchors.verticalCenter: parent.verticalCenter
                            color: root.row && root.row.resets && root.row.resets.entries.length > 0 ? root.severityColor(root.row.resets.entries[0].severity) : "transparent"
                        }
                        Text {
                            text: root.row ? root.row.detail : ""
                            color: Color.popups.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                            anchors.verticalCenter: parent.verticalCenter
                        }
                    }
                    Text {
                        visible: text !== ""
                        anchors.right: parent.right
                        text: root.row && root.row.subtitle ? root.row.subtitle : ""
                        color: Qt.alpha(Color.popups.text, 0.65)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.caption
                    }
                }
                MouseArea {
                    id: valueMouse
                    anchors.fill: parent
                    hoverEnabled: root.row && (root.row.interactive || !!root.row.detailTip)
                    acceptedButtons: root.row && root.row.interactive ? Qt.LeftButton : Qt.NoButton
                    cursorShape: root.row && root.row.interactive ? Qt.PointingHandCursor : Qt.ArrowCursor
                    onClicked: root.detailOpen = !root.detailOpen
                    Ui.PanelToolTip {
                        visible: parent.containsMouse && root.row && root.row.detailTip && !root.detailOpen
                        text: root.row && root.row.detailTip ? root.row.detailTip : ""
                    }
                }
            }
        }
        ModelBreakdownTip {
            visible: !root.isMeter && !root.isChart && root.detailOpen && root.row && root.row.breakdown !== null
            width: parent.width
            title: root.row ? root.row.title : ""
            breakdown: root.row ? root.row.breakdown : null
        }
        RateLimitResets {
            visible: !root.isMeter && !root.isChart && root.detailOpen && root.row && root.row.resets !== null
            width: parent.width
            resets: root.row ? root.row.resets : null
            claimResult: root.claimResult
            warningColor: root.warningColor
            onClaim: function(iso, requestId) { root.claim(root.cardId, iso, requestId); }
        }
        UsageTrend {
            visible: root.isChart
            width: parent.width
            title: root.row ? root.row.title : ""
            points: root.row ? root.row.points : []
            note: root.row ? root.row.chartNote : ""
        }
    }
}
