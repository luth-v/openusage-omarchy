import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Settings.js" as Settings

// Codex cost-estimate picker. Options (priced models only) and the saved
// choice meet here; the daemon recomputes spend when the choice changes.
// Matches CodexPricingSection copy: title, help and the unavailable note.
Column {
    id: root
    property var options: []
    property string selected: ""
    property bool loading: false
    property bool refreshing: false
    property bool compact: false
    readonly property bool unavailable: Settings.fallbackUnavailable(root.options, root.selected)
    readonly property bool popupOpen: picker.popupOpen
    signal pick(string modelId)
    width: parent ? parent.width : 0
    spacing: Style.space(6)
    Text {
        x: Style.space(8)
        text: "Cost Estimates"
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
            spacing: Style.space(6)
            topPadding: Style.space(10)
            bottomPadding: Style.space(10)
            Row {
                width: parent.width - Style.space(24)
                anchors.horizontalCenter: parent.horizontalCenter
                height: Math.max(fallbackLabel.implicitHeight, picker.implicitHeight)
                Text {
                    id: fallbackLabel
                    text: "Fallback Model"
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: root.compact ? Style.font.bodySmall : Style.font.body
                    anchors.verticalCenter: parent.verticalCenter
                }
                Item {
                    width: Math.max(8, parent.width - fallbackLabel.implicitWidth - picker.implicitWidth - Style.space(8))
                    height: 1
                }
                Ui.Dropdown {
                    id: picker
                    value: root.selected
                    options: [{value: "", label: "None"}].concat((root.options || []).map(function(o) {
                        return {value: o.id, label: o.title};
                    })).concat(root.unavailable ? [{value: root.selected, label: "Unavailable Model"}] : [])
                    showLabel: false
                    implicitWidth: Style.space(170)
                    width: implicitWidth
                    height: implicitHeight
                    anchors.verticalCenter: parent.verticalCenter
                    onChanged: function(picked) { root.pick(picked); }
                }
            }
            Text {
                visible: root.loading || root.refreshing
                width: parent.width - Style.space(24)
                anchors.horizontalCenter: parent.horizontalCenter
                text: root.loading ? "Loading Models…" : "Recalculating Estimates…"
                color: Qt.alpha(Color.popups.text, 0.6)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
            Text {
                width: parent.width - Style.space(24)
                anchors.horizontalCenter: parent.horizontalCenter
                wrapMode: Text.Wrap
                text: "Estimate costs for models that don't have known pricing."
                color: Qt.alpha(Color.popups.text, 0.6)
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
            Text {
                visible: root.unavailable && !root.loading
                width: parent.width - Style.space(24)
                anchors.horizontalCenter: parent.horizontalCenter
                wrapMode: Text.Wrap
                text: "This model's pricing is unavailable. Choose another model or None."
                color: Color.urgent
                font.family: Style.font.family
                font.pixelSize: Style.font.caption
            }
        }
    }
}
