import QtQuick
import qs.Ui as Ui

// Labeled toggle row: a SettingsRow with the switch slotted in.
SettingsRow {
    id: root
    property bool checked: false
    signal flipped(bool value)
    Ui.ToggleSwitch {
        width: implicitWidth
        height: implicitHeight
        checked: root.checked
        onToggled: root.flipped(!root.checked)
    }
}
