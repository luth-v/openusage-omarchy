import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui
import "../js/Dashboard.js" as Dashboard
import "../js/Drag.js" as Drag
import "../js/Format.js" as Format
import "../js/Keys.js" as Keys
import "../js/Notices.js" as Notices
import "../js/Layout.js" as Layout
import "../js/Menus.js" as Menus
import "../js/Pace.js" as Pace
import "../js/Theme.js" as Theme

// Dashboard composition: banner, hint, spend, sections, pinned footer,
// and the context-menu overlay. View math lives in js/; this only binds,
// forwards picks, and clamps menu positions.
Ui.Panel {
    id: root
    moduleName: root.hostWidget ? root.hostWidget.moduleName : ""
    manageIpc: false
    property var hostWidget: null
    property var anchorItem: null
    readonly property var service: root.hostWidget ? root.hostWidget.service : null
    readonly property var feed: root.service ? root.service.state : null
    readonly property var layout: root.service ? root.service.layout : null
    readonly property var catalog: root.service ? root.service.catalog : null
    readonly property string display: root.hostWidget ? root.hostWidget.setting("display", "Left") : "Left"
    readonly property string resetMode: root.hostWidget ? root.hostWidget.setting("resetDisplay", "Countdown") : "Countdown"
    readonly property string timeFormat: root.hostWidget ? root.hostWidget.setting("timeFormat", "Auto") : "Auto"
    readonly property bool alwaysShowPacing: root.hostWidget ? !!root.hostWidget.setting("alwaysShowPacing", false) : false
    readonly property bool compact: root.hostWidget ? root.hostWidget.setting("density", "Default") === "Compact" : false
    readonly property bool reduceMotion: root.hostWidget ? !!root.hostWidget.setting("reduceAnimations", false) : false
    readonly property bool showTotalSpend: root.hostWidget ? root.hostWidget.setting("showTotalSpend", true) !== false : true
    // Two clocks: `now` steps once per wall-clock minute and drives the
    // section models (their labels are minute-granular); `clock` ticks every
    // second for the footer's final-minute seconds countdown only.
    property var now: new Date()
    property var clock: new Date()
    property string themeColors: ""
    readonly property color warningColor: {
        var yellow = Theme.parseYellow(root.themeColors);
        return yellow ? yellow : Color.accent;
    }
    readonly property var model: Dashboard.sections(root.layout, root.catalog, root.feed, {
        display: root.display, resetMode: root.resetMode, now: root.now,
        timeFormat: root.timeFormat, alwaysShowPacing: root.alwaysShowPacing
    }, {fmt: Format, pace: Pace, layout: Layout})
    readonly property var banner: Dashboard.updateBannerModel(root.feed)
    readonly property var footer: Dashboard.footerModel(root.feed, root.clock)
    readonly property bool spendOn: Dashboard.spendVisible(root.layout, root.showTotalSpend, root.catalog)
    readonly property var spendProviders: Dashboard.spendProviders(root.layout, root.catalog)
    readonly property string spendPeriod: root.layout && root.layout.spend && root.layout.spend.period ? root.layout.spend.period : "today"
    readonly property string spendMetric: root.layout && root.layout.spend && root.layout.spend.metric ? root.layout.spend.metric : "cost"
    property string menuKind: ""
    property var menuAnchor: null
    property bool aboutOpen: false
    property string dragSectionId: ""
    property string hoverSectionId: ""
    property bool party: false
    property var partyMatcher: Keys.createMatcher()
    property string sharePill: ""
    function sectionGeometries() {
        var out = [];
        for (var i = 0; i < sectionsRep.count; i++) {
            var item = sectionsRep.itemAt(i);
            if (item)
                out.push({id: item.cardId, top: item.y, bottom: item.y + item.height});
        }
        return out;
    }
    function sectionDragMove(mouseItem, x, y) {
        if (root.dragSectionId === "")
            return;
        var p = mouseItem.mapToItem(contentColumn, x, y);
        root.hoverSectionId = Drag.dropTarget(root.sectionGeometries(), p.y, root.dragSectionId) || "";
    }
    function sectionDragEnd(canceled) {
        dashFlick.interactive = true;
        var dragged = root.dragSectionId;
        var target = root.hoverSectionId;
        root.dragSectionId = "";
        root.hoverSectionId = "";
        if (!canceled && dragged !== "" && target !== "" && target !== dragged && root.service)
            root.service.dispatch({type: "moveProvider", dragged: dragged, target: target});
    }
    property real menuX: 0
    property real menuY: 0
    readonly property var menuStar: Menus.menuStarState(root.catalog, root.layout,
        root.menuAnchor ? root.menuAnchor.cardId : "", root.menuAnchor ? root.menuAnchor.metricId : "")
    function openMenu(kind, anchor, x, y) {
        root.menuAnchor = anchor;
        root.menuX = x;
        root.menuY = y;
        root.menuKind = kind;
    }
    function dismissMenu() {
        root.menuKind = "";
        root.menuAnchor = null;
    }
    function menuPick(id) {
        var routed = Menus.menuAction(root.menuKind, id, root.menuAnchor);
        root.dismissMenu();
        if (routed.route === "dispatch" && root.service)
            root.service.dispatch(routed.action);
        else if (routed.route === "refresh" && root.service)
            root.service.refresh(true, routed.cardId);
        else if (routed.route === "customize" && root.hostWidget)
            root.hostWidget.openCustomize(routed.cardId);
        else if (routed.route === "settings" && root.hostWidget)
            root.hostWidget.openSettings();
        else if (routed.route === "share")
            root.shareCard(routed.cardId);
        else if (routed.route === "checkUpdates" && root.service)
            root.service.checkUpdate();
        else if (routed.route === "about")
            root.aboutOpen = true;
    }
    function shareCard(cardId) {
        for (var i = 0; i < sectionsRep.count; i++) {
            var item = sectionsRep.itemAt(i);
            if (item && item.cardId === cardId) {
                shareCapture.capture(item);
                return;
            }
        }
    }
    function feedMove(dx, dy) {
        var token = dx < 0 ? "left" : dx > 0 ? "right" : dy < 0 ? "up" : "down";
        if (root.partyMatcher.accept(token))
            root.party = !root.party;
    }
    function feedText(t) {
        var lower = String(t).toLowerCase();
        if (lower === "b" || lower === "a") {
            if (root.partyMatcher.accept(lower))
                root.party = !root.party;
        } else {
            root.partyMatcher.reset();
        }
    }
    function handleTextKey(text) {
        root.feedText(text);
        var action = Keys.panelAction(text, {screen: "dashboard"});
        if (action === "undo" && root.service)
            root.service.undo();
        else if (action === "refresh" && root.service)
            root.service.refresh(true);
        else if (action === "settings" && root.hostWidget)
            root.hostWidget.openSettings();
    }
    FileView {
        path: Quickshell.env("HOME") + "/.local/state/omarchy/current/theme/colors.toml"
        watchChanges: true
        printErrors: false
        onLoaded: root.themeColors = text()
        onLoadFailed: root.themeColors = ""
        onFileChanged: reload()
    }
    Timer {
        interval: 1000
        repeat: true
        running: root.opened
        onTriggered: {
            var d = new Date();
            root.clock = d;
            if (Math.floor(d.getTime() / 60000) !== Math.floor(root.now.getTime() / 60000))
                root.now = d;
        }
    }
    PartyMode {
        id: partyMode
        active: root.party
        reduceMotion: root.reduceMotion
        colors: [Color.accent, root.warningColor, Color.urgent]
    }
    ShareCapture {
        id: shareCapture
        onDone: function(ok) {
            if (ok) {
                root.sharePill = Notices.messageFor("copied");
                sharePillTimer.restart();
            }
        }
    }
    Timer {
        id: sharePillTimer
        interval: Notices.timeoutFor("share")
        onTriggered: root.sharePill = ""
    }
    onOpenedChanged: {
        if (root.opened) {
            root.now = new Date();
            root.clock = root.now;
            root.dismissMenu();
            root.aboutOpen = false;
        } else {
            root.aboutOpen = false;
        }
    }
    Ui.KeyboardPanel {
        anchorItem: root.anchorItem
        owner: root.hostWidget || root
        bar: root.bar
        open: root.opened
        focusTarget: keys
        contentWidth: fittedContentWidth(Style.space(430))
        contentHeight: fittedContentHeight(contentColumn.implicitHeight + footer.implicitHeight, Style.space(780))
        Ui.PanelKeyCatcher {
            id: keys
            anchors.fill: parent
            onCloseRequested: {
                if (root.aboutOpen)
                    root.aboutOpen = false;
                else if (root.menuKind !== "")
                    root.dismissMenu();
                else
                    root.close();
            }
            onReturnRequested: {
                if (root.aboutOpen)
                    root.aboutOpen = false;
                else if (root.menuKind !== "")
                    root.dismissMenu();
                else if (root.hostWidget)
                    root.hostWidget.openCustomize();
            }
            onTextKey: function(t) {
                if (root.menuKind === "" && !root.aboutOpen)
                    root.handleTextKey(t);
            }
            onMoveRequested: function(dx, dy) {
                if (root.menuKind === "" && !root.aboutOpen)
                    root.feedMove(dx, dy);
            }
            Flickable {
                id: dashFlick
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                height: parent.height - footer.implicitHeight
                contentWidth: width
                contentHeight: contentColumn.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                Column {
                    id: contentColumn
                    width: parent.width
                    spacing: Style.space(10)
                    UpdateBanner {
                        visible: root.banner !== null
                        width: parent.width
                        version: root.banner ? root.banner.version : ""
                        installable: root.banner ? root.banner.installable : false
                        onInstall: root.service ? root.service.installUpdate() : undefined
                        onDismiss: root.service && root.banner ? root.service.snoozeUpdate(root.banner.version) : undefined
                    }
                    FirstRunCard {
                        visible: root.layout && !root.layout.hintDismissed
                        width: parent.width
                        onOpenCustomize: root.hostWidget ? root.hostWidget.openCustomize() : undefined
                        onDismiss: root.service ? root.service.dispatch({type: "dismissHint"}) : undefined
                    }
                    TotalSpendCard {
                        id: spendCard
                        visible: root.spendOn
                        width: parent.width
                        providers: root.spendProviders
                        cards: root.feed && root.feed.cards ? root.feed.cards : []
                        period: root.spendPeriod
                        metric: root.spendMetric
                        infoTip: Dashboard.spendInfoTip(root.spendProviders)
                        compact: root.compact
                        onPeriodPicked: function(p) { if (root.service) root.service.dispatch({type: "setSpend", period: p}); }
                        onMetricPicked: function(picked) { if (root.service) root.service.dispatch({type: "setSpend", metric: picked}); }
                        onShareRequested: shareCapture.capture(spendCard)
                    }
                    Repeater {
                        id: sectionsRep
                        // Count model: the 1 s clock rebuilds the sections array, and a
                        // new array would recreate every delegate (dropping hover state).
                        model: root.model.sections.length
                        delegate: Column {
                            required property int index
                            readonly property var modelData: root.model.sections[index] || null
                            property string cardId: modelData ? modelData.cardId : ""
                            width: contentColumn.width
                            height: implicitHeight
                            opacity: root.dragSectionId === cardId ? 0.5 : 1
                            Rectangle {
                                visible: index > 0
                                width: parent.width - Style.space(20)
                                height: 1
                                anchors.horizontalCenter: parent.horizontalCenter
                                color: Qt.alpha(Color.popups.text, 0.15)
                            }
                            ProviderSection {
                                width: parent.width
                                section: modelData
                                claimResult: modelData ? modelData.lastClaim : null
                                warningColor: root.warningColor
                                compact: root.compact
                                reduceMotion: root.reduceMotion
                                partyFill: partyMode.current
                                dropHover: root.hoverSectionId === cardId
                                menuLayer: menuHost
                                onToggleCollapse: root.service ? root.service.dispatch({type: "setExpanded", cardId: modelData.cardId, expanded: !modelData.isExpanded}) : undefined
                                onToggleDisplay: root.hostWidget ? root.hostWidget.toggleDisplay() : undefined
                                onToggleReset: root.hostWidget ? root.hostWidget.toggleResetDisplay() : undefined
                                onMoveMetric: function(dragged, target) {
                                    if (root.service)
                                        root.service.dispatch({type: "moveMetric", cardId: modelData.cardId, dragged: dragged, target: target});
                                }
                                onSectionDragStart: function(cardId) {
                                    root.dragSectionId = cardId;
                                    root.hoverSectionId = "";
                                    dashFlick.interactive = false;
                                }
                                onSectionDragMove: function(mouseItem, x, y) {
                                    root.sectionDragMove(mouseItem, x, y);
                                }
                                onSectionDragEnd: root.sectionDragEnd(false)
                                onSectionDragCancel: root.sectionDragEnd(true)
                                onRowDragStart: dashFlick.interactive = false
                                onRowDragEnd: dashFlick.interactive = true
                                onRowDragCancel: dashFlick.interactive = true
                                onRowMenu: function(row, cardId, x, y) {
                                    root.openMenu("row", {cardId: cardId, metricId: row.metricId, label: modelData.label}, x, y);
                                }
                                onHeaderMenu: function(x, y) {
                                    root.openMenu("header", {cardId: modelData.cardId, label: modelData.label}, x, y);
                                }
                                onClaim: function(cardId, iso, requestId) {
                                    if (root.service)
                                        root.service.claimReset(cardId, iso, requestId);
                                }
                            }
                        }
                    }
                    Text {
                        visible: root.model.isEmpty
                        width: parent.width
                        horizontalAlignment: Text.AlignHCenter
                        text: Dashboard.EMPTY_DASHBOARD
                        color: Qt.alpha(Color.popups.text, 0.65)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                    }
                }
            }
            DashboardFooter {
                id: footer
                anchors.bottom: parent.bottom
                width: parent.width
                version: root.footer.version
                text: root.footer.text
                updating: root.footer.updating
                reduceMotion: root.reduceMotion
                menuLayer: menuHost
                onOptions: function(x, y) { root.openMenu("options", null, x, y); }
                onRefreshRequested: { if (root.service) root.service.refresh(true); }
            }
            Item {
                id: menuHost
                anchors.fill: parent
                MouseArea {
                    anchors.fill: parent
                    visible: root.menuKind !== ""
                    onClicked: root.dismissMenu()
                }
                RowMenu {
                    visible: root.menuKind === "row"
                    x: Math.max(4, Math.min(root.menuX, menuHost.width - implicitWidth - 4))
                    y: Math.max(4, Math.min(root.menuY, menuHost.height - implicitHeight - 4))
                    starrable: root.menuStar.starrable
                    starred: root.menuStar.starred
                    providerName: root.menuAnchor ? root.menuAnchor.label : ""
                    onPick: function(id) { root.menuPick(id); }
                }
                HeaderMenu {
                    visible: root.menuKind === "header"
                    x: Math.max(4, Math.min(root.menuX, menuHost.width - implicitWidth - 4))
                    y: Math.max(4, Math.min(root.menuY, menuHost.height - implicitHeight - 4))
                    providerName: root.menuAnchor ? root.menuAnchor.label : ""
                    onPick: function(id) { root.menuPick(id); }
                }
                OptionsMenu {
                    visible: root.menuKind === "options"
                    x: menuHost.width - implicitWidth - 4
                    y: Math.max(4, root.menuY - implicitHeight - 4)
                    providers: root.model.sections.map(function(s) { return {cardId: s.cardId, label: s.label}; })
                    onPick: function(id) { root.menuPick(id); }
                }
            }
            Item {
                visible: root.aboutOpen
                anchors.fill: parent
                MouseArea {
                    anchors.fill: parent
                    onClicked: root.aboutOpen = false
                }
                Rectangle {
                    anchors.fill: parent
                    color: Qt.alpha(Color.popups.background, 0.6)
                }
                AboutSheet {
                    anchors.fill: parent
                    version: root.footer.version
                    onClose: root.aboutOpen = false
                }
            }
            Rectangle {
                visible: root.sharePill !== ""
                anchors.top: parent.top
                anchors.topMargin: Style.space(8)
                anchors.horizontalCenter: parent.horizontalCenter
                width: sharePillLabel.implicitWidth + Style.space(20)
                height: sharePillLabel.implicitHeight + Style.space(10)
                radius: height / 2
                color: Color.popups.background
                border.width: 1
                border.color: Qt.alpha(Color.popups.text, 0.25)
                Text {
                    id: sharePillLabel
                    anchors.centerIn: parent
                    text: root.sharePill
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                }
            }
        }
    }
}
