import QtQuick
import qs.Commons
import "../js/Format.js" as Format

// Model breakdown for a spend period: ranked models with cost, share and
// tokens over a share bar, plus the source note.
Item {
    id: root
    property string title: ""
    property var breakdown: null
    implicitHeight: layout.implicitHeight
    height: implicitHeight
    width: parent ? parent.width : 0
    Column {
        id: layout
        width: parent.width
        spacing: Style.space(8)
        Text {
            text: root.title
            color: Color.popups.text
            font.family: Style.font.family
            font.pixelSize: Style.font.subtitle
            font.bold: true
        }
        Column {
            width: parent.width
            height: implicitHeight
            Repeater {
                model: root.breakdown && root.breakdown.models ? root.breakdown.models.length : 0
                delegate: Column {
                    required property int index
                    readonly property var modelData: (root.breakdown && root.breakdown.models && root.breakdown.models[index]) || ({})
                    width: parent.width
                    height: implicitHeight
                    spacing: 2
                    Row {
                        width: parent.width
                        height: implicitHeight
                        Text {
                            text: modelData.name
                            color: Color.popups.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                            font.bold: true
                            elide: Text.ElideRight
                            width: parent.width - cost.implicitWidth - Style.space(8)
                        }
                        Text {
                            id: cost
                            text: modelData.cost === null || modelData.cost === undefined ? "—" : Format.number(modelData.cost, "dollars", "row")
                            color: modelData.cost === null || modelData.cost === undefined ? Qt.alpha(Color.popups.text, 0.45) : Color.popups.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                        }
                    }
                    Item {
                        width: parent.width
                        height: Math.max(percent.implicitHeight, tokens.implicitHeight)
                        Text {
                            id: percent
                            anchors.left: parent.left
                            text: modelData.percent + "%"
                            color: Qt.alpha(Color.popups.text, 0.65)
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                        }
                        Text {
                            id: tokens
                            anchors.right: parent.right
                            text: Format.stringFor({number: modelData.tokens, kind: "count", label: "tokens"}, "row")
                            color: Qt.alpha(Color.popups.text, 0.65)
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                        }
                    }
                    Rectangle {
                        width: parent.width
                        height: Style.space(5)
                        radius: height / 2
                        color: Qt.alpha(Color.popups.text, 0.15)
                        Rectangle {
                            width: parent.width * Math.min(1, Math.max(0, modelData.share))
                            height: parent.height
                            radius: height / 2
                            color: Color.accent
                        }
                    }
                    Item {
                        width: 1
                        height: Style.space(4)
                    }
                }
            }
        }
        Text {
            visible: root.breakdown && root.breakdown.note !== ""
            width: parent.width
            text: root.breakdown ? root.breakdown.note : ""
            color: Qt.alpha(Color.popups.text, 0.45)
            font.family: Style.font.family
            font.pixelSize: Style.font.caption
            wrapMode: Text.Wrap
        }
    }
}
