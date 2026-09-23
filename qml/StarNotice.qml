import QtQuick
import qs.Commons

// Transient in-Customize pill: green star confirm or orange cap denial.
// The LayoutStore clears the text on its timer; this only shows it.
Item {
    id: root
    property string notice: ""
    property string tone: "positive"
    property color warningColor: Color.accent
    visible: root.notice !== ""
    width: parent ? parent.width : 0
    height: visible ? pill.implicitHeight + Style.space(8) : 0
    Rectangle {
        id: pill
        anchors.horizontalCenter: parent.horizontalCenter
        y: Style.space(4)
        width: Math.min(label.implicitWidth + Style.space(24), parent.width - Style.space(16))
        height: label.implicitHeight + Style.space(12)
        radius: height / 2
        color: root.tone === "notice" ? root.warningColor : Color.accent
        Text {
            id: label
            anchors.centerIn: parent
            width: parent.width - Style.space(24)
            horizontalAlignment: Text.AlignHCenter
            elide: Text.ElideRight
            text: root.notice
            color: Color.background
            font.family: Style.font.family
            font.pixelSize: Style.font.bodySmall
            font.bold: true
        }
    }
}
