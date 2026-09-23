import QtQuick
import "../js/Menus.js" as Menus

// Metric-row menu: Hide, Star/Unstar, Refresh, Customize.
PopupMenu {
    id: root
    property bool starrable: false
    property bool starred: false
    property string providerName: ""
    items: Menus.rowMenuItems({starrable: root.starrable, starred: root.starred, providerName: root.providerName})
}
