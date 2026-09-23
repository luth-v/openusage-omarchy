import QtQuick
import qs.Commons

Item {
    id: root
    required property string providerId
    property color surface: Color.background
    property color fallbackColor: Color.foreground
    property real size: Style.space(16)
    property bool party: false
    property bool reduceMotion: false
    width: size
    height: size
    SequentialAnimation {
        id: partyPulse
        running: root.party && !root.reduceMotion
        loops: Animation.Infinite
        onRunningChanged: {
            if (!running)
                root.scale = 1;
        }
        NumberAnimation {
            target: root
            property: "scale"
            to: 1.12
            duration: 490
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: root
            property: "scale"
            to: 0.88
            duration: 980
            easing.type: Easing.InOutSine
        }
        NumberAnimation {
            target: root
            property: "scale"
            to: 1.0
            duration: 490
            easing.type: Easing.InOutSine
        }
    }

    function channel(value) {
        var n = Number(value);
        if (!isFinite(n)) return 0;
        return n <= 0.03928 ? n / 12.92 : Math.pow((n + 0.055) / 1.055, 2.4);
    }

    function luminance(color) {
        return 0.2126 * channel(color.r) + 0.7152 * channel(color.g) + 0.0722 * channel(color.b);
    }

    readonly property bool lightSurface: surface.a > 0.4 ? luminance(surface) >= 0.5 : luminance(fallbackColor) < 0.5
    readonly property var candidates: {
        if (!providerId)
            return [];
        var list = [];
        if (lightSurface)
            list.push(Qt.resolvedUrl("../assets/" + providerId + "-light.svg"));
        list.push(Qt.resolvedUrl("../assets/" + providerId + ".svg"));
        return list;
    }
    property int candidateIndex: 0
    onCandidatesChanged: candidateIndex = 0

    Image {
        id: mark
        anchors.fill: parent
        source: root.candidateIndex < root.candidates.length ? root.candidates[root.candidateIndex] : ""
        sourceSize.width: root.size * 2
        sourceSize.height: root.size * 2
        fillMode: Image.PreserveAspectFit
        onStatusChanged: if (status === Image.Error && root.candidateIndex < root.candidates.length)
            Qt.callLater(function() { root.candidateIndex++; })
    }

    Text {
        anchors.centerIn: parent
        visible: mark.status !== Image.Ready
        text: root.providerId ? root.providerId.charAt(0).toUpperCase() : "?"
        color: root.fallbackColor
        font.family: Style.font.family
        font.pixelSize: Math.max(8, root.size - 2)
        font.bold: true
    }
}
