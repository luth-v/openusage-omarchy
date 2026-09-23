import QtQuick
import "../js/Menus.js" as Menus

// Section-header menu: Hide, Refresh, Customize, Share Screenshot.
PopupMenu {
    id: root
    property string providerName: ""
    items: Menus.headerMenuItems({providerName: root.providerName})
}
