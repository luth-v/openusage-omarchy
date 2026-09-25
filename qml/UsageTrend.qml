import QtQuick
import qs.Commons
import "../js/Spend.js" as Spend
import "../js/Dashboard.js" as Dashboard
import qs.Ui as Ui

// Usage Trend: compact day-by-day token sparkline. Hovering a day shows its
// readout; clicking expands the larger chart with the peak (or hovered day)
// readout, range, and source.
Item {
    id: root
    property string title: ""
    property var points: []
    property string note: ""
    property bool open: false
    property var activeIndex: null
    property var stripIndex: null
    readonly property var bars: Spend.trendBars(root.points)
    readonly property var summary: Dashboard.trendSummary(root.points)
    readonly property string readout: Dashboard.trendReadout(root.points, root.activeIndex)
    readonly property real stripHeight: Style.space(28)
    readonly property real detailHeight: Style.space(76)
    implicitHeight: layout.implicitHeight
    height: implicitHeight
    width: parent ? parent.width : 0
    function barHeight(fraction, height) {
        return fraction <= 0 ? 2 : Math.max(height * fraction, 2);
    }
    // One hover area per chart: nested per-bar MouseAreas lose hover to
    // whichever sibling area sits above them, so resolve the day from x.
    function indexAt(x, width) {
        var n = root.bars.length;
        if (n === 0 || width <= 0 || x < 0 || x >= width)
            return null;
        return Math.min(n - 1, Math.floor(x / width * n));
    }
    Column {
        id: layout
        width: parent.width
        spacing: Style.space(8)
        Item {
            width: parent.width
            height: headerRow.height
                Row {
                    id: headerRow
                    width: parent.width
                    height: implicitHeight
                    spacing: Style.space(8)
                Text {
                    text: root.title
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                    font.bold: true
                    anchors.verticalCenter: parent.verticalCenter
                }
                Item {
                    width: Math.max(8, parent.width - parent.children[0].implicitWidth - strip.width - parent.spacing * 2)
                    height: 1
                }
                Row {
                    id: strip
                    width: Math.min(Style.space(150), Math.max(Style.space(90), headerRow.width - headerRow.children[0].implicitWidth - Style.space(24)))
                    height: root.stripHeight
                    spacing: 1
                    anchors.verticalCenter: parent.verticalCenter
                    Repeater {
                        model: root.bars.length
                        delegate: Rectangle {
                            required property int index
                            readonly property var modelData: root.bars[index] || ({fraction: 0})
                            width: Math.max(2, (strip.width - (root.bars.length - 1)) / Math.max(1, root.bars.length))
                            height: root.barHeight(modelData.fraction, root.stripHeight)
                            anchors.bottom: parent.bottom
                            radius: 1
                            color: Color.accent
                            opacity: root.stripIndex === null || root.stripIndex === index ? 1 : 0.35
                        }
                    }
                }
            }
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.open = !root.open
                onPositionChanged: mouse => {
                    var p = mapToItem(strip, mouse.x, mouse.y);
                    root.stripIndex = p.y >= 0 && p.y <= strip.height ? root.indexAt(p.x, strip.width) : null;
                }
                onContainsMouseChanged: {
                    if (!containsMouse)
                        root.stripIndex = null;
                }
                Ui.PanelToolTip {
                    visible: parent.containsMouse && root.stripIndex !== null
                    text: Dashboard.trendReadout(root.points, root.stripIndex)
                }
            }
        }
        Column {
            visible: root.open
            width: parent.width
            height: implicitHeight
            spacing: Style.space(8)
            Row {
                width: parent.width
                height: implicitHeight
                Text {
                    text: root.title
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.subtitle
                    font.bold: true
                }
                Item {
                    width: Math.max(8, parent.width - parent.children[0].implicitWidth - readout.implicitWidth - Style.space(8))
                    height: 1
                }
                Text {
                    id: readout
                    text: root.readout
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
            }
            Item {
                width: parent.width
                height: root.detailHeight
                Row {
                    id: detailRow
                    anchors.fill: parent
                    spacing: 2
                    Repeater {
                        model: root.bars.length
                        delegate: Item {
                            required property int index
                            readonly property var modelData: root.bars[index] || ({fraction: 0})
                            width: (detailRow.width - (root.bars.length - 1) * 2) / Math.max(1, root.bars.length)
                            height: detailRow.height
                            Rectangle {
                                width: parent.width
                                height: root.barHeight(modelData.fraction, root.detailHeight)
                                anchors.bottom: parent.bottom
                                radius: 1.5
                                color: Color.accent
                                opacity: root.activeIndex === null || root.activeIndex === index ? 1 : 0.35
                            }
                        }
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: true
                    acceptedButtons: Qt.NoButton
                    onPositionChanged: mouse => root.activeIndex = root.indexAt(mouse.x, width)
                    onContainsMouseChanged: {
                        if (!containsMouse)
                            root.activeIndex = null;
                    }
                }
            }
            Row {
                width: parent.width
                height: implicitHeight
                Text {
                    text: root.summary ? root.summary.first : ""
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
                Item {
                    width: Math.max(8, parent.width - parent.children[0].implicitWidth - last.implicitWidth - Style.space(8))
                    height: 1
                }
                Text {
                    id: last
                    text: root.summary ? root.summary.last : ""
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
            }
            Text {
                visible: root.note !== ""
                width: parent.width
                text: root.note
                color: Qt.alpha(Color.popups.text, 0.45)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
                wrapMode: Text.Wrap
            }
        }
    }
}
