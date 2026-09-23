import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Spend.js" as Spend
import "../js/Format.js" as Format
import "../js/Dashboard.js" as Dashboard

// Cross-provider Total Spend card: metric menu, period switcher, ring with
// legend, and the quiet empty state. Period and metric persist in
// layout.json through the setSpend reducer action.
Item {
    id: root
    property var providers: []
    property var cards: []
    property string period: "today"
    property string metric: "cost"
    property string infoTip: ""
    property bool compact: false
    signal periodPicked(string period)
    signal metricPicked(string metric)
    signal shareRequested()
    readonly property var total: Spend.totalFor(root.period, root.cards, root.providers)
    readonly property var projection: Spend.projection(root.total, root.metric)
    readonly property var center: Format.totalSpendRingCenter(root.projection.centerValue, root.projection.metric)
    readonly property string centerTip: {
        var exact = root.metric === "tokens" ? Format.number(root.projection.centerValue, "count", "full")
            : root.metric === "costPerMtok" ? Format.costPerMtok(root.projection.centerValue, "full")
            : Format.number(root.projection.centerValue, "dollars", "full");
        if (root.projection.isEstimated && root.metric !== "tokens")
            return exact + " · " + Dashboard.LOCAL_ESTIMATE_NOTE;
        return exact;
    }
    readonly property var arcs: Spend.donutArcs(root.projection.slices)
    readonly property var legend: root.projection.slices.map(function(s) {
        return {providerId: s.provider.id, name: s.provider.displayName, amount: s.displayAmount};
    })
    implicitHeight: layout.implicitHeight
    height: visible ? implicitHeight : 0
    width: parent ? parent.width : 0
    Column {
        id: layout
        width: parent.width
        spacing: Style.space(6)
        Row {
            width: parent.width
            height: implicitHeight
            spacing: Style.space(5)
            Item {
                id: metricButton
                width: metricLabel.implicitWidth + Style.space(14)
                height: Math.max(metricLabel.implicitHeight, Style.space(22))
                Row {
                    id: metricLabel
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: Style.space(4)
                    Text {
                        text: Spend.METRICS[root.metric] ? Spend.METRICS[root.metric].title : "Cost"
                        color: Color.popups.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.subtitle
                        font.bold: true
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Item {
                        width: Style.space(8)
                        height: Style.space(6)
                        anchors.verticalCenter: parent.verticalCenter
                        Rectangle {
                            width: Style.space(6)
                            height: 2
                            radius: 1
                            color: Qt.alpha(Color.popups.text, 0.65)
                            anchors.left: parent.left
                            anchors.verticalCenter: parent.verticalCenter
                            rotation: 45
                        }
                        Rectangle {
                            width: Style.space(6)
                            height: 2
                            radius: 1
                            color: Qt.alpha(Color.popups.text, 0.65)
                            anchors.right: parent.right
                            anchors.verticalCenter: parent.verticalCenter
                            rotation: -45
                        }
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        var p = mapToItem(menuLayer, 0, height + 4);
                        menuLayer.open(p.x, p.y);
                    }
                }
            }
            Item {
                width: Style.space(14)
                height: Style.space(14)
                anchors.verticalCenter: parent.verticalCenter
                Rectangle {
                    anchors.fill: parent
                    radius: width / 2
                    color: "transparent"
                    border.width: 1
                    border.color: Qt.alpha(Color.popups.text, 0.45)
                }
                Text {
                    anchors.centerIn: parent
                    text: "i"
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    Ui.PanelToolTip {
                        visible: parent.containsMouse && root.infoTip !== ""
                        text: root.infoTip
                    }
                }
            }
            Text {
                text: "Share"
                color: Qt.alpha(Color.popups.text, 0.65)
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                font.underline: shareMouse.containsMouse
                anchors.verticalCenter: parent.verticalCenter
                MouseArea {
                    id: shareMouse
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: root.shareRequested()
                }
            }
        }
        Rectangle {
            width: parent.width
            radius: Style.cornerRadius
            color: Qt.alpha(Color.popups.text, 0.06)
            implicitHeight: inner.implicitHeight + Style.space(24)
            height: implicitHeight
            Column {
                id: inner
                anchors.fill: parent
                anchors.margins: Style.space(12)
                spacing: Style.space(12)
                Row {
                    width: parent.width
                    height: implicitHeight
                    spacing: 2
                    Repeater {
                        model: ["today", "yesterday", "last30"]
                        delegate: Rectangle {
                            required property string modelData
                            width: (parent.width - 4) / 3
                            height: segLabel.implicitHeight + Style.space(8)
                            radius: height / 2
                            color: root.period === modelData ? Qt.alpha(Color.popups.text, 0.14) : "transparent"
                            Text {
                                id: segLabel
                                anchors.centerIn: parent
                                text: Spend.PERIODS[modelData].short
                                color: root.period === modelData ? Color.popups.text : Qt.alpha(Color.popups.text, 0.65)
                                font.family: Style.font.family
                                font.pixelSize: Style.font.bodySmall
                                font.bold: root.period === modelData
                            }
                            MouseArea {
                                anchors.fill: parent
                                cursorShape: Qt.PointingHandCursor
                                onClicked: root.periodPicked(modelData)
                            }
                        }
                    }
                }
                Text {
                    visible: root.projection.isEmpty
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: Spend.emptyMessageFor(root.metric)
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                }
                SpendDonut {
                    visible: !root.projection.isEmpty
                    width: parent.width
                    arcs: root.arcs
                    legend: root.legend
                    metric: root.projection.metric
                    center: root.center
                    centerTip: root.centerTip
                }
            }
            Item {
                id: menuLayer
                anchors.fill: parent
                function open(x, y) {
                    metricMenu.x = Math.max(4, Math.min(x, width - metricMenu.width - 4));
                    metricMenu.y = y;
                    metricMenu.visible = true;
                }
                MouseArea {
                    anchors.fill: parent
                    visible: metricMenu.visible
                    onClicked: metricMenu.visible = false
                }
                Rectangle {
                    id: metricMenu
                    visible: false
                    width: Style.space(140)
                    height: menuColumn.implicitHeight + Style.space(8)
                    radius: Style.cornerRadius
                    color: Color.menu.background
                    border.width: 1
                    border.color: Color.menu.border
                    Column {
                        id: menuColumn
                        width: parent.width
                        height: implicitHeight
                        anchors.verticalCenter: parent.verticalCenter
                        Repeater {
                            model: ["cost", "costPerMtok", "tokens"]
                            delegate: Rectangle {
                                required property string modelData
                                width: menuColumn.width
                                height: Style.space(28)
                                color: menuMouse.containsMouse ? Color.menu.selectedBackground : "transparent"
                                Text {
                                    anchors.left: parent.left
                                    anchors.leftMargin: Style.space(12)
                                    anchors.verticalCenter: parent.verticalCenter
                                    text: (root.metric === modelData ? "✓  " : "") + Spend.METRICS[modelData].title
                                    color: menuMouse.containsMouse ? Color.menu.selectedText : Color.menu.text
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.bodySmall
                                }
                                MouseArea {
                                    id: menuMouse
                                    anchors.fill: parent
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: {
                                        metricMenu.visible = false;
                                        root.metricPicked(modelData);
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
