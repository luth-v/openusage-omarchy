import QtQuick
import qs.Commons
import qs.Ui as Ui
import "../js/Dashboard.js" as Dashboard
import "../js/Theme.js" as Theme

// Rate-limit-resets timeline: one node per available credit, soonest first,
// with the Codex claim flow inline (Use → confirm → Reset/Cancel). The claim
// resolves from card.lastClaim, which the daemon writes after the claim call.
Item {
    id: root
    property var resets: null
    property var claimResult: null
    property color warningColor: Color.accent
    signal claim(string iso, string requestId)
    property string confirming: ""
    property string claiming: ""
    property var claimed: []
    property var requestIds: ({})
    property var banner: null
    property bool nothingToReset: false
    property real clickMs: 0
    property string hovered: ""
    function visibleEntries() {
        var list = root.resets && root.resets.entries ? root.resets.entries : [];
        return list.filter(function(e) { return root.claimed.indexOf(e.iso) < 0; });
    }
    function dotColor(severity) {
        return Theme.meterColor(severity, {accent: Color.accent, warning: root.warningColor, urgent: Color.urgent});
    }
    function beginConfirm(iso) {
        var ids = Object.assign({}, root.requestIds);
        if (!ids[iso])
            ids[iso] = Dashboard.makeUuid();
        root.requestIds = ids;
        root.banner = null;
        root.hovered = "";
        root.confirming = iso;
    }
    function runClaim(iso) {
        var key = root.requestIds[iso] || Dashboard.makeUuid();
        root.confirming = "";
        root.claiming = iso;
        root.clickMs = Date.now();
        root.claim(iso, key);
    }
    function applyClaim(result) {
        var status = result.status || "error";
        if (status === "ok" || status === "unavailable")
            root.claimed = root.claimed.concat([root.claiming]);
        if (status === "ok" || status === "not_needed")
            root.nothingToReset = true;
        root.banner = {text: result.message || "", tone: Dashboard.claimTone(status)};
        root.claiming = "";
    }
    onClaimResultChanged: {
        if (root.claiming !== "") {
            var ready = Dashboard.claimReady(root.claimResult, root.clickMs);
            if (ready)
                root.applyClaim(ready);
        }
    }
    implicitHeight: layout.implicitHeight
    height: implicitHeight
    width: parent ? parent.width : 0
    Column {
        id: layout
        width: parent.width
        spacing: Style.space(8)
        Rectangle {
            visible: root.banner !== null
            width: parent.width
            height: bannerText.implicitHeight + Style.space(18)
            radius: Style.cornerRadius
            color: {
                var tone = root.banner ? root.banner.tone : "";
                if (tone === "positive")
                    return Qt.alpha(Color.accent, 0.12);
                if (tone === "warning")
                    return Qt.alpha(root.warningColor, 0.12);
                if (tone === "critical")
                    return Qt.alpha(Color.urgent, 0.12);
                return Qt.alpha(Color.popups.text, 0.08);
            }
            Text {
                id: bannerText
                anchors.centerIn: parent
                width: parent.width - Style.space(18)
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.Wrap
                text: root.banner ? root.banner.text : ""
                color: {
                    var tone = root.banner ? root.banner.tone : "";
                    if (tone === "positive")
                        return Color.accent;
                    if (tone === "warning")
                        return root.warningColor;
                    if (tone === "critical")
                        return Color.urgent;
                    return Color.popups.text;
                }
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
                font.bold: true
            }
        }
        Column {
            width: parent.width
            visible: root.visibleEntries().length === 0 && root.claiming === ""
            Text {
                visible: (root.resets ? root.resets.count : 0) - root.claimed.length <= 0
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: "You have no rate limit resets"
                color: Qt.alpha(Color.popups.text, 0.65)
                font.family: Style.font.family
                font.pixelSize: Style.font.bodySmall
            }
            Column {
                visible: (root.resets ? root.resets.count : 0) - root.claimed.length > 0
                width: parent.width
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: ((root.resets ? root.resets.count : 0) - root.claimed.length) + " available"
                    color: Color.popups.text
                    font.family: Style.font.family
                    font.pixelSize: Style.font.bodySmall
                }
                Text {
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: "Expiry times unavailable"
                    color: Qt.alpha(Color.popups.text, 0.65)
                    font.family: Style.font.family
                    font.pixelSize: Style.font.caption
                }
            }
        }
        Repeater {
            model: root.visibleEntries()
            delegate: Column {
                required property var modelData
                required property int index
                width: layout.width
                height: implicitHeight
                spacing: Style.space(4)
                Item {
                    width: parent.width
                    height: entryRow.height
                    Row {
                        id: entryRow
                        width: parent.width
                        spacing: Style.space(8)
                    Rectangle {
                        width: Style.space(18)
                        height: Style.space(18)
                        radius: width / 2
                        anchors.verticalCenter: parent.verticalCenter
                        color: root.dotColor(modelData.severity)
                        Text {
                            anchors.centerIn: parent
                            text: index + 1
                            color: modelData.severity === "warning" ? "black" : "white"
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                        }
                    }
                    Text {
                        id: entryTime
                        text: modelData.time
                        color: Color.popups.text
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Item {
                        width: Math.max(8, entryRow.width - Style.space(18) - entryTime.implicitWidth - trailing.implicitWidth - entryRow.spacing * 3)
                        height: 1
                    }
                    Item {
                        id: trailing
                        width: Math.max(countdown.implicitWidth, useButton.implicitWidth)
                        height: Math.max(countdown.implicitHeight, useButton.implicitHeight)
                        anchors.verticalCenter: parent.verticalCenter
                        Text {
                            id: countdown
                            visible: !(root.resets && root.resets.claimable && root.hovered === modelData.iso && root.confirming === "" && root.claiming === "")
                            anchors.centerIn: parent
                            text: modelData.countdown || ""
                            color: Qt.alpha(Color.popups.text, 0.65)
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                        }
                        Rectangle {
                            id: useButton
                            visible: root.resets && root.resets.claimable && root.hovered === modelData.iso && root.confirming === "" && root.claiming === ""
                            anchors.centerIn: parent
                            width: useLabel.implicitWidth + Style.space(16)
                            height: useLabel.implicitHeight + Style.space(6)
                            radius: Style.cornerRadius
                            color: "transparent"
                            border.width: 1
                            border.color: Qt.alpha(Color.popups.text, 0.4)
                            opacity: root.nothingToReset ? 0.45 : 1
                            Text {
                                id: useLabel
                                anchors.centerIn: parent
                                text: "Use"
                                color: Color.popups.text
                                font.family: Style.font.family
                                font.pixelSize: Style.font.bodySmall
                            }
                            MouseArea {
                                anchors.fill: parent
                                enabled: !root.nothingToReset
                                hoverEnabled: root.nothingToReset
                                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                onClicked: root.beginConfirm(modelData.iso)
                                Ui.PanelToolTip {
                                    visible: parent.containsMouse && root.nothingToReset
                                    text: "Nothing to reset right now"
                                }
                            }
                        }
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    hoverEnabled: root.resets && root.resets.claimable
                    acceptedButtons: Qt.NoButton
                    onContainsMouseChanged: {
                        if (containsMouse)
                            root.hovered = modelData.iso;
                        else if (root.hovered === modelData.iso)
                            root.hovered = "";
                    }
                }
            }
                Rectangle {
                    visible: root.confirming === modelData.iso
                    width: parent.width
                    height: confirmLayout.implicitHeight + Style.space(20)
                    radius: Style.cornerRadius
                    color: Qt.alpha(Color.popups.text, 0.08)
                    Column {
                        id: confirmLayout
                        anchors.fill: parent
                        anchors.margins: Style.space(10)
                        spacing: Style.space(8)
                        Text {
                            text: "Use this reset?"
                            color: Color.popups.text
                            font.family: Style.font.family
                            font.pixelSize: Style.font.bodySmall
                            font.bold: true
                        }
                        Text {
                            width: parent.width
                            text: "Immediately reset your usage limits. This can't be undone."
                            color: Qt.alpha(Color.popups.text, 0.65)
                            font.family: Style.font.family
                            font.pixelSize: Style.font.caption
                            wrapMode: Text.Wrap
                        }
                        Row {
                            width: parent.width
                            height: implicitHeight
                            spacing: Style.space(8)
                            Rectangle {
                                width: (parent.width - parent.spacing) / 2
                                height: resetLabel.implicitHeight + Style.space(8)
                                radius: Style.cornerRadius
                                color: Color.accent
                                Text {
                                    id: resetLabel
                                    anchors.centerIn: parent
                                    text: "Reset"
                                    color: Color.popups.background
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.bodySmall
                                    font.bold: true
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.runClaim(modelData.iso)
                                }
                            }
                            Rectangle {
                                width: (parent.width - parent.spacing) / 2
                                height: cancelLabel.implicitHeight + Style.space(8)
                                radius: Style.cornerRadius
                                color: "transparent"
                                border.width: 1
                                border.color: Qt.alpha(Color.popups.text, 0.4)
                                Text {
                                    id: cancelLabel
                                    anchors.centerIn: parent
                                    text: "Cancel"
                                    color: Color.popups.text
                                    font.family: Style.font.family
                                    font.pixelSize: Style.font.bodySmall
                                }
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: root.confirming = ""
                                }
                            }
                        }
                    }
                }
                Row {
                    visible: root.claiming === modelData.iso
                    width: parent.width
                    height: implicitHeight
                    spacing: Style.space(8)
                    Text {
                        text: "Resetting your usage…"
                        color: Qt.alpha(Color.popups.text, 0.65)
                        font.family: Style.font.family
                        font.pixelSize: Style.font.bodySmall
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Item {
                        width: Style.space(12)
                        height: Style.space(12)
                        anchors.verticalCenter: parent.verticalCenter
                        Canvas {
                            anchors.fill: parent
                            onPaint: {
                                var ctx = getContext("2d");
                                ctx.clearRect(0, 0, width, height);
                                ctx.beginPath();
                                ctx.arc(width / 2, height / 2, width / 2 - 1, 0, 1.5 * Math.PI);
                                ctx.strokeStyle = Color.popups.text.toString();
                                ctx.lineWidth = 2;
                                ctx.stroke();
                            }
                        }
                        RotationAnimation on rotation {
                            from: 0
                            to: 360
                            duration: 900
                            loops: Animation.Infinite
                            running: root.claiming === modelData.iso
                        }
                    }
                }
            }
        }
    }
}
