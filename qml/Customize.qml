import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui
import "../js/Customize.js" as Customize
import "../js/Keys.js" as Keys
import "../js/Theme.js" as Theme

// Customize panel: provider list, then one provider's detail. Views read
// the service layout/catalog/state; every change is a Layout dispatch.
// Closing resets navigation (selection, scroll, dialogs), as upstream.
Ui.Panel {
    id: root
    moduleName: root.hostWidget ? root.hostWidget.moduleName : ""
    manageIpc: false
    property var hostWidget: null
    property var anchorItem: null
    readonly property var service: root.hostWidget ? root.hostWidget.service : null
    readonly property var layout: root.service ? root.service.layout : null
    readonly property var catalog: root.service ? root.service.catalog : null
    readonly property var feed: root.service ? root.service.state : null
    readonly property bool compact: root.hostWidget ? root.hostWidget.setting("density", "Default") === "Compact" : false
    readonly property bool reduceMotion: root.hostWidget ? !!root.hostWidget.setting("reduceAnimations", false) : false
    readonly property var rows: Customize.providerRows(root.layout, root.catalog, root.feed)
    readonly property var detail: root.selectedCardId ? Customize.detailFor(root.layout, root.catalog, root.selectedCardId) : null
    readonly property var slot: root.selectedCardId && root.layout && root.layout.cards ? root.layout.cards[root.selectedCardId] : null
    readonly property string detailFamily: root.selectedCardId ? Customize.familyOf(root.selectedCardId) : ""
    readonly property bool isKeyProvider: root.detailFamily === "openrouter" || root.detailFamily === "zai"
    readonly property bool isCodex: root.detailFamily === "codex"
    readonly property string keyStatus: root.feed && root.feed.secrets ? (root.feed.secrets[root.detailFamily] || "none") : "none"
    readonly property var fallbackOptions: root.feed && root.feed.pricing && root.feed.pricing.codexFallbackOptions ? root.feed.pricing.codexFallbackOptions : []
    readonly property string fallbackSelected: root.hostWidget ? root.hostWidget.setting("codexFallbackModel", "") : ""
    readonly property bool codexRefreshing: {
        var flight = root.feed && root.feed.refresh ? root.feed.refresh.inFlight : [];
        return flight.indexOf("*") >= 0 || flight.indexOf("codex") >= 0;
    }
    property string selectedCardId: ""
    property bool resetAllOpen: false
    property string themeColors: ""
    readonly property color warningColor: {
        var yellow = Theme.parseYellow(root.themeColors);
        return yellow ? yellow : Color.accent;
    }
    function openCard(cardId) {
        if (cardId && Customize.detailFor(root.layout, root.catalog, cardId))
            root.selectedCardId = cardId;
        else
            root.selectedCardId = "";
        scroller.contentY = 0;
    }
    function goBack() {
        if (root.resetAllOpen) {
            root.resetAllOpen = false;
            return;
        }
        if (root.selectedCardId !== "")
            root.openCard("");
        else if (root.hostWidget)
            root.hostWidget.openDashboard();
    }
    function confirmResetAll() {
        root.resetAllOpen = false;
        if (root.service) {
            root.service.dispatch({type: "resetAll", detected: root.service.detected});
            root.service.refresh(true);
        }
    }
    function handleTextKey(text) {
        var action = Keys.panelAction(text, {screen: "customize"});
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
    onOpenedChanged: {
        if (!root.opened) {
            root.selectedCardId = "";
            root.resetAllOpen = false;
            apiKey.reset();
            scroller.contentY = 0;
        }
    }
    Ui.KeyboardPanel {
        anchorItem: root.anchorItem
        owner: root.hostWidget || root
        bar: root.bar
        open: root.opened
        focusTarget: keys
        contentWidth: fittedContentWidth(Style.space(430))
        contentHeight: fittedContentHeight(contentColumn.implicitHeight, Style.space(780))
        Ui.PanelKeyCatcher {
            id: keys
            anchors.fill: parent
            blocked: apiKey.editing || codexSection.popupOpen
            onCloseRequested: root.goBack()
            onReturnRequested: {
                if (root.resetAllOpen) {
                    if (confirm.selectedIndex === 0)
                        root.resetAllOpen = false;
                    else
                        root.confirmResetAll();
                } else {
                    root.goBack();
                }
            }
            onMoveRequested: function(dx, dy) {
                if (root.resetAllOpen)
                    confirm.selectedIndex = confirm.selectedIndex === 0 ? 1 : 0;
            }
            onTextKey: function(t) {
                if (!root.resetAllOpen)
                    root.handleTextKey(t);
            }
            Column {
                id: contentColumn
                width: parent.width
                spacing: Style.space(10)
                Item {
                    width: parent.width
                    height: Style.space(34)
                    Rectangle {
                        id: backButton
                        anchors.left: parent.left
                        anchors.leftMargin: Style.space(10)
                        anchors.verticalCenter: parent.verticalCenter
                        width: Style.space(28)
                        height: Style.space(28)
                        radius: Style.space(14)
                        color: Qt.alpha(Color.popups.text, backMouse.containsMouse ? 0.14 : 0.08)
                        Text {
                            anchors.centerIn: parent
                            text: "‹"
                            color: Color.popups.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.title
                        }
                        MouseArea {
                            id: backMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.goBack()
                            Ui.PanelToolTip {
                                visible: parent.containsMouse
                                text: "Back"
                            }
                        }
                    }
                    Text {
                        anchors.centerIn: parent
                        text: root.detail ? root.detail.displayName : "Customize"
                        color: Color.popups.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.subtitle
                        font.bold: true
                    }
                    Rectangle {
                        anchors.right: parent.right
                        anchors.rightMargin: Style.space(10)
                        anchors.verticalCenter: parent.verticalCenter
                        width: Style.space(28)
                        height: Style.space(28)
                        radius: Style.space(14)
                        color: Qt.alpha(Color.popups.text, resetMouse.containsMouse ? 0.14 : 0.08)
                        Text {
                            anchors.centerIn: parent
                            text: "⟳"
                            color: Color.popups.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.body
                        }
                        MouseArea {
                            id: resetMouse
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: {
                                if (root.detail && root.service)
                                    root.service.dispatch({type: "resetProvider", cardId: root.selectedCardId});
                                else
                                    root.resetAllOpen = true;
                            }
                            Ui.PanelToolTip {
                                visible: parent.containsMouse
                                text: root.detail ? "Reset " + root.detail.displayName : "Reset All Customization"
                            }
                        }
                    }
                }
                StarNotice {
                    visible: root.service && root.service.starNotice !== ""
                    width: parent.width
                    notice: root.service ? root.service.starNotice : ""
                    tone: root.service ? root.service.starTone : "positive"
                    warningColor: root.warningColor
                }
                Flickable {
                    id: scroller
                    width: parent.width
                    height: Math.min(body.implicitHeight, Style.space(700))
                    contentWidth: width
                    contentHeight: body.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    Column {
                        id: body
                        width: scroller.width
                        spacing: Style.space(12)
                        Column {
                            visible: !root.detail
                            height: visible ? implicitHeight : 0
                            width: parent.width
                            spacing: Style.space(12)
                            CustomizeProviderList {
                                width: parent.width - Style.space(20)
                                anchors.horizontalCenter: parent.horizontalCenter
                                rows: root.rows
                                compact: root.compact
                                flick: scroller
                                onToggleCard: function(cardId, enabled) {
                                    if (root.service)
                                        root.service.dispatch({type: "setCardEnabled", cardId: cardId, enabled: enabled});
                                }
                                onOpenCard: function(cardId) { root.openCard(cardId); }
                                onMoveCard: function(dragged, target) {
                                    if (root.service)
                                        root.service.dispatch({type: "moveProvider", dragged: dragged, target: target});
                                }
                            }
                            CrossLink {
                                width: parent.width - Style.space(20)
                                anchors.horizontalCenter: parent.horizontalCenter
                                icon: "⚙"
                                title: "Settings"
                                subtitle: "Notifications, appearance and more"
                                onOpen: {
                                    if (root.hostWidget)
                                        root.hostWidget.openSettings();
                                }
                            }
                        }
                        Column {
                            visible: !!root.detail
                            height: visible ? implicitHeight : 0
                            width: parent.width
                            spacing: Style.space(12)
                            CustomizeProviderDetail {
                                width: parent.width - Style.space(20)
                                anchors.horizontalCenter: parent.horizontalCenter
                                detail: root.detail
                                stars: root.slot && root.slot.stars ? root.slot.stars : []
                                cardEnabled: root.slot ? !!root.slot.enabled : true
                                compact: root.compact
                                reduceMotion: root.reduceMotion
                                flick: scroller
                                onToggleMetric: function(metricId, enabled) {
                                    if (root.service)
                                        root.service.dispatch({type: "setMetricEnabled", cardId: root.selectedCardId, metricId: metricId, enabled: enabled});
                                }
                                onToggleStar: function(metricId) {
                                    if (root.service)
                                        root.service.dispatch({type: "toggleStar", cardId: root.selectedCardId, metricId: metricId});
                                }
                                onMoveMetric: function(dragged, target) {
                                    if (root.service)
                                        root.service.dispatch({type: "moveMetric", cardId: root.selectedCardId, dragged: dragged, target: target});
                                }
                                onMoveToSection: function(metricId, section) {
                                    if (root.service)
                                        root.service.dispatch({type: "setMetricSection", cardId: root.selectedCardId, metricId: metricId, section: section});
                                }
                            }
                            ApiKeySection {
                                id: apiKey
                                visible: root.isKeyProvider
                                height: visible ? implicitHeight : 0
                                width: parent.width - Style.space(20)
                                anchors.horizontalCenter: parent.horizontalCenter
                                providerId: root.detailFamily
                                displayName: root.detail ? root.detail.displayName : ""
                                status: root.keyStatus
                                compact: root.compact
                                onSave: function(provider, value) {
                                    if (root.service)
                                        root.service.setKey(provider, value);
                                }
                                onClearKey: function(provider) {
                                    if (root.service)
                                        root.service.deleteKey(provider);
                                }
                            }
                            CodexPricingSection {
                                id: codexSection
                                visible: root.isCodex
                                height: visible ? implicitHeight : 0
                                width: parent.width - Style.space(20)
                                anchors.horizontalCenter: parent.horizontalCenter
                                options: root.fallbackOptions
                                selected: root.fallbackSelected
                                loading: !root.feed
                                refreshing: root.codexRefreshing && !!root.feed
                                compact: root.compact
                                onPick: function(modelId) {
                                    if (root.hostWidget)
                                        root.hostWidget.persist("codexFallbackModel", modelId);
                                }
                            }
                        }
                    }
                }
            }
            Ui.ConfirmDialog {
                id: confirm
                anchors.fill: parent
                opened: root.resetAllOpen
                message: Customize.RESET_ALL_TITLE + "\n" + Customize.RESET_ALL_MESSAGE
                cancelText: Customize.RESET_ALL_CANCEL
                confirmText: Customize.RESET_ALL_CONFIRM
                onCanceled: root.resetAllOpen = false
                onConfirmed: root.confirmResetAll()
            }
        }
    }
}
