import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui as Ui
import "../js/Settings.js" as Settings
import "../js/Keys.js" as Keys

// Settings panel: app-wide preferences in upstream sections, minus the
// ADR 0005 omissions (no theme, transparency, sync, telemetry or screen
// share rows). Every row persists to shell.json through the host widget;
// daemon-backed rows also send a command the pass-8 daemon will apply.
Ui.Panel {
    id: root
    moduleName: root.hostWidget ? root.hostWidget.moduleName : ""
    manageIpc: false
    property var hostWidget: null
    property var anchorItem: null
    readonly property var service: root.hostWidget ? root.hostWidget.service : null
    readonly property bool compact: root.hostWidget ? root.hostWidget.setting("density", "Default") === "Compact" : false
    readonly property string logPath: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/openusage-omarchy/openusage-omarchy.log"
    readonly property string logDir: (Quickshell.env("XDG_STATE_HOME") || Quickshell.env("HOME") + "/.local/state") + "/openusage-omarchy"
    readonly property bool anyPopupOpen: styleDrop.popupOpen || densityDrop.popupOpen || timeDrop.popupOpen || displayDrop.popupOpen || resetDrop.popupOpen || logDrop.popupOpen
    property bool resetOpen: false
    property string logActionError: ""
    function goBack() {
        if (root.resetOpen) {
            root.resetOpen = false;
            return;
        }
        if (recorder.recording) {
            recorder.stop();
            return;
        }
        if (root.hostWidget)
            root.hostWidget.openDashboard();
    }
    function resetAllSettings() {
        root.resetOpen = false;
        if (root.service) {
            root.service.dispatch({type: "resetAll", detected: root.service.detected});
            root.service.dispatch({type: "setSpend", period: "today", metric: "cost"});
        }
        if (root.hostWidget) {
            root.hostWidget.resetSettingsToDefaults();
            root.service.refresh(true);
        }
    }
    function handleTextKey(text) {
        var action = Keys.panelAction(text, {screen: "settings"});
        if (action === "undo" && root.service)
            root.service.undo();
        else if (action === "refresh" && root.service)
            root.service.refresh(true);
        else if (action === "settings" && root.hostWidget)
            root.hostWidget.openDashboard();
    }
    onOpenedChanged: {
        if (!root.opened) {
            root.resetOpen = false;
            root.logActionError = "";
            recorder.stop();
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
            blocked: recorder.recording || root.anyPopupOpen
            onCloseRequested: root.goBack()
            onReturnRequested: {
                if (root.resetOpen) {
                    if (confirm.selectedIndex === 0)
                        root.resetOpen = false;
                    else
                        root.resetAllSettings();
                } else {
                    root.goBack();
                }
            }
            onMoveRequested: function(dx, dy) {
                if (root.resetOpen)
                    confirm.selectedIndex = confirm.selectedIndex === 0 ? 1 : 0;
            }
            onTextKey: function(t) {
                if (!root.resetOpen)
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
                        text: "Settings"
                        color: Color.popups.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.subtitle
                        font.bold: true
                    }
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
                        width: scroller.width - Style.space(20)
                        anchors.horizontalCenter: parent.horizontalCenter
                        spacing: Style.space(12)
                        SettingsSection {
                            title: "General"
                            SettingsToggle {
                                label: "Show Total Spend"
                                compact: root.compact
                                checked: root.hostWidget ? !!root.hostWidget.setting("showTotalSpend", true) : true
                                onFlipped: function(next) { root.hostWidget.persist("showTotalSpend", next); }
                            }
                            SettingsRow {
                                label: "Global Shortcut"
                                compact: root.compact
                                ShortcutRecorder {
                                    id: recorder
                                    saved: root.hostWidget ? root.hostWidget.setting("shortcut", "") : ""
                                    compact: root.compact
                                    onAccepted: function(text, combo) {
                                        root.hostWidget.persist("shortcut", text);
                                    }
                                }
                            }
                        }
                        SettingsSection {
                            title: "Appearance"
                            SettingsPicker {
                                id: styleDrop
                                label: "Icon Style"
                                compact: root.compact
                                value: root.hostWidget ? root.hostWidget.setting("style", "Text") : "Text"
                                options: Settings.STYLE_OPTIONS
                                onPicked: function(next) { root.hostWidget.persist("style", next); }
                            }
                            SettingsPicker {
                                id: densityDrop
                                label: "Density"
                                compact: root.compact
                                value: root.hostWidget ? root.hostWidget.setting("density", "Default") : "Default"
                                options: Settings.DENSITY_OPTIONS
                                onPicked: function(next) { root.hostWidget.persist("density", next); }
                            }
                            SettingsToggle {
                                label: "Reduce Animations"
                                compact: root.compact
                                checked: root.hostWidget ? !!root.hostWidget.setting("reduceAnimations", false) : false
                                onFlipped: function(next) { root.hostWidget.persist("reduceAnimations", next); }
                            }
                            SettingsPicker {
                                id: timeDrop
                                label: "Time Format"
                                compact: root.compact
                                value: root.hostWidget ? root.hostWidget.setting("timeFormat", "Auto") : "Auto"
                                options: Settings.TIME_FORMAT_OPTIONS
                                onPicked: function(next) { root.hostWidget.persist("timeFormat", next); }
                            }
                        }
                        SettingsSection {
                            title: "Usage Display"
                            SettingsPicker {
                                id: displayDrop
                                label: "Show Usage As"
                                compact: root.compact
                                value: root.hostWidget ? root.hostWidget.setting("display", "Left") : "Left"
                                options: Settings.DISPLAY_OPTIONS
                                onPicked: function(next) { root.hostWidget.persist("display", next); }
                            }
                            SettingsPicker {
                                id: resetDrop
                                label: "Reset Times"
                                compact: root.compact
                                value: root.hostWidget ? root.hostWidget.setting("resetDisplay", "Countdown") : "Countdown"
                                options: Settings.RESET_OPTIONS
                                onPicked: function(next) { root.hostWidget.persist("resetDisplay", next); }
                            }
                            SettingsToggle {
                                label: "Always Show Pacing"
                                tip: "Show how you're pacing on every metric, not just ones near their limit"
                                compact: root.compact
                                checked: root.hostWidget ? !!root.hostWidget.setting("alwaysShowPacing", false) : false
                                onFlipped: function(next) { root.hostWidget.persist("alwaysShowPacing", next); }
                            }
                        }
                        SettingsSection {
                            title: "Notifications"
                            Repeater {
                                model: Settings.NOTIFICATIONS
                                delegate: SettingsToggle {
                                    required property var modelData
                                    label: modelData.label
                                    tip: modelData.tip
                                    compact: root.compact
                                    checked: root.hostWidget ? !!root.hostWidget.setting(modelData.key, false) : false
                                    onFlipped: function(next) { root.hostWidget.persist(modelData.key, next); }
                                }
                            }
                        }
                        SettingsSection {
                            title: "Updates"
                            SettingsToggle {
                                label: "Update Automatically"
                                compact: root.compact
                                checked: root.hostWidget ? root.hostWidget.setting("updateAuto", true) !== false : true
                                onFlipped: function(next) { root.hostWidget.persist("updateAuto", next); }
                            }
                            SettingsToggle {
                                label: "Beta Updates"
                                tip: "Receive pre-release builds before they ship to everyone"
                                compact: root.compact
                                checked: root.hostWidget ? !!root.hostWidget.setting("betaUpdates", false) : false
                                onFlipped: function(next) { root.hostWidget.persist("betaUpdates", next); }
                            }
                            SettingsToggle {
                                label: "Update with Omarchy"
                                tip: Settings.UPDATE_WITH_OMARCHY_NOTE
                                compact: root.compact
                                checked: root.hostWidget ? !!root.hostWidget.setting("updateWithOmarchy", false) : false
                                onFlipped: function(next) { root.hostWidget.persist("updateWithOmarchy", next); }
                            }
                            Item {
                                width: parent.width
                                height: Style.space(40)
                                TextButton {
                                    anchors.centerIn: parent
                                    width: parent.width - Style.space(24)
                                    height: Style.space(28)
                                    text: "Check for Updates…"
                                    onClicked: {
                                        if (root.service)
                                            root.service.checkUpdate();
                                    }
                                }
                            }
                        }
                        SettingsSection {
                            title: "Advanced"
                            SettingsPicker {
                                id: logDrop
                                label: "Log Level"
                                compact: root.compact
                                value: root.hostWidget ? root.hostWidget.setting("logLevel", "Info") : "Info"
                                options: Settings.LOG_LEVEL_OPTIONS
                                onPicked: function(next) {
                                    root.hostWidget.persist("logLevel", next);
                                }
                            }
                            Item {
                                width: parent.width
                                height: Style.space(40)
                                TextButton {
                                    anchors.centerIn: parent
                                    anchors.horizontalCenterOffset: -(width / 2 + Style.space(4))
                                    width: (parent.width - Style.space(24) - Style.space(8)) / 2
                                    height: Style.space(28)
                                    text: "Copy Log Path"
                                    onClicked: {
                                        copyProc.command = ["wl-copy", root.logPath];
                                        copyProc.running = true;
                                    }
                                }
                                TextButton {
                                    anchors.centerIn: parent
                                    anchors.horizontalCenterOffset: width / 2 + Style.space(4)
                                    width: (parent.width - Style.space(24) - Style.space(8)) / 2
                                    height: Style.space(28)
                                    text: "Show Log in Files"
                                    onClicked: Qt.openUrlExternally("file://" + root.logDir)
                                }
                            }
                            Text {
                                visible: root.logActionError !== ""
                                height: visible ? implicitHeight : 0
                                width: parent.width - Style.space(24)
                                x: Style.space(12)
                                wrapMode: Text.Wrap
                                text: root.logActionError
                                color: Color.urgent
                                font.family: Style.font.family
                                font.pixelSize: Style.font.caption
                            }
                            Item {
                                width: parent.width
                                height: Style.space(44)
                                TextButton {
                                    anchors.centerIn: parent
                                    width: parent.width - Style.space(24)
                                    height: Style.space(28)
                                    text: "Reset All Settings…"
                                    destructive: true
                                    onClicked: root.resetOpen = true
                                }
                            }
                        }
                        CrossLink {
                            width: parent.width
                            icon: "☰"
                            title: "Customize"
                            subtitle: "Choose what's visible and where"
                            onOpen: {
                                if (root.hostWidget)
                                    root.hostWidget.openCustomize();
                            }
                        }
                    }
                }
            }
            Ui.ConfirmDialog {
                id: confirm
                anchors.fill: parent
                opened: root.resetOpen
                message: Settings.RESET_SETTINGS_TITLE + "\n" + Settings.RESET_SETTINGS_MESSAGE
                cancelText: "Cancel"
                confirmText: "Reset"
                onCanceled: root.resetOpen = false
                onConfirmed: root.resetAllSettings()
            }
        }
    }
    Process {
        id: copyProc
        onExited: function(code, status) {
            running = false;
            root.logActionError = code === 0 ? "" : "Couldn't copy the log path to the clipboard.";
        }
    }
}
