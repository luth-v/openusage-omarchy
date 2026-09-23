import QtQuick
import qs.Commons
import qs.Ui as Ui

// Labeled picker row: a SettingsRow with the dropdown slotted in.
SettingsRow {
    id: root
    property string value: ""
    property var options: []
    readonly property bool popupOpen: drop.popupOpen
    signal picked(string value)
    Ui.Dropdown {
        id: drop
        value: root.value
        options: root.options
        showLabel: false
        implicitWidth: Style.space(150)
        width: implicitWidth
        height: implicitHeight
        onChanged: function(selected) { root.picked(selected); }
    }
}
