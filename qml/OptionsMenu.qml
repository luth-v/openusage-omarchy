import QtQuick
import "../js/Menus.js" as Menus

// Footer Options menu: Customize, Settings, Share, Check for Updates.
PopupMenu {
    id: root
    property var providers: []
    items: Menus.optionsMenuItems({providers: root.providers})
}
