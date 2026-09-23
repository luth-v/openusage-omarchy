import QtQuick

// Party mode: Konami toggles a cycle through theme colours on the meter
// fills. No transparency, no display link when off or under Reduce
// Animations (static first colour). Item root: QtObject takes no child
// objects in this Qt build.
Item {
    id: root
    property bool active: false
    property var colors: []
    property bool reduceMotion: false
    property int index: 0
    readonly property var current: root.active && root.colors.length > 0 ? root.colors[root.index % root.colors.length] : null
    onActiveChanged: root.index = 0
    Timer {
        interval: 450
        repeat: true
        running: root.active && !root.reduceMotion && root.colors.length > 1
        onTriggered: root.index = (root.index + 1) % root.colors.length
    }
}
