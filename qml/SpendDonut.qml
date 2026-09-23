import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Format.js" as Format
import "../js/Theme.js" as Theme

// Total Spend ring plus ranked legend. Arcs and legend rows arrive
// precomputed; this draws the ring and formats the amounts.
Item {
    id: root
    property var arcs: []
    property var legend: []
    property string metric: "cost"
    property var center: ({primary: "", unit: ""})
    property string centerTip: ""
    implicitHeight: Math.max(ringBox.height, legendColumn.implicitHeight)
    height: implicitHeight
    width: parent ? parent.width : 0
    function legendText(amount) {
        if (root.metric === "tokens")
            return Format.number(amount, "count", "row");
        if (root.metric === "costPerMtok")
            return Format.costPerMtok(amount, "full");
        return Format.number(amount, "dollars", "full");
    }
    Item {
        id: ringBox
        width: Style.space(104)
        height: Style.space(104)
        Canvas {
            id: ring
            anchors.fill: parent
            onPaint: {
                var ctx = getContext("2d");
                ctx.clearRect(0, 0, width, height);
                var cx = width / 2;
                var cy = height / 2;
                var outer = width / 2 - 2;
                var inner = outer * 0.62;
                var light = Theme.isLight(Color.popups.background);
                var arcs = root.arcs || [];
                for (var i = 0; i < arcs.length; i++) {
                    var gap = 0.008;
                    var a0 = (arcs[i].start + gap - 0.25) * 2 * Math.PI;
                    var a1 = (arcs[i].end - gap - 0.25) * 2 * Math.PI;
                    if (a1 <= a0)
                        continue;
                    ctx.beginPath();
                    ctx.arc(cx, cy, outer, a0, a1);
                    ctx.arc(cx, cy, inner, a1, a0, true);
                    ctx.closePath();
                    ctx.fillStyle = Theme.spendColor(arcs[i].providerId, light);
                    ctx.fill();
                }
            }
        }
        Column {
            anchors.centerIn: parent
            spacing: 1
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.center.primary
                color: Color.popups.text
                font.family: Style.font.family
                font.pixelSize: Style.font.subtitle
                font.bold: true
            }
            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.center.unit
                color: Qt.alpha(Color.popups.text, 0.45)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
        }
        MouseArea {
            anchors.fill: parent
            hoverEnabled: root.centerTip !== ""
            Ui.PanelToolTip {
                visible: parent.containsMouse && root.centerTip !== ""
                text: root.centerTip
            }
        }
    }
    Column {
        id: legendColumn
        anchors.left: ringBox.right
        anchors.leftMargin: Style.space(18)
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        spacing: Style.space(7)
        Repeater {
            model: root.legend
            delegate: Row {
                required property var modelData
                width: legendColumn.width
                height: implicitHeight
                spacing: Style.space(7)
                Rectangle {
                    width: Style.space(8)
                    height: Style.space(8)
                    radius: width / 2
                    anchors.verticalCenter: parent.verticalCenter
                    color: Theme.spendColor(modelData.providerId, Theme.isLight(Color.popups.background))
                }
                Text {
                    text: modelData.name
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    elide: Text.ElideRight
                    width: parent.width - Style.space(8) - amount.implicitWidth - parent.spacing * 2
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    id: amount
                    text: root.legendText(modelData.amount)
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
        }
    }
    onArcsChanged: ring.requestPaint()
}
