import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    objectName: "mainWindow"
    visible: true
    width: 1180; height: 760
    minimumWidth: 960; minimumHeight: 600
    // Keep the native title bar quiet; version and executable identity belong
    // in diagnostics/about information rather than the working surface.
    title: ""
    color: Theme.canvas
    property bool collapsed: false
    property bool settingsVisible: false
    property bool activityExpanded: false
    property bool followLogs: true
    onClosing: function(event) { event.accepted = appController.requestClose() }
    Shortcut { sequence: "Ctrl+S"; onActivated: appController.save() }
    Shortcut { sequence: "Ctrl+Shift+L"; onActivated: appController.toggleTheme() }
    Connections {
        target: appController
        function onNavigateSettings(key) { window.settingsVisible = true; window.collapsed = false }
        function onNavigateCourses() { window.settingsVisible = false; window.collapsed = false }
    }

    Rectangle {
        id: sidebar
        width: window.collapsed ? 56 : 240
        anchors.top: parent.top; anchors.bottom: parent.bottom; anchors.left: parent.left
        color: Theme.sidebar
        Column {
            id: navigation
            x: 8; y: 8; width: parent.width - 16; spacing: 4
            UiButton {
                anchors.right: parent.right; width: 28; height: 28
                iconName: window.collapsed ? "expand" : "collapse"
                tooltip: window.collapsed ? "展开侧栏" : "收起侧栏"
                onClicked: window.collapsed = !window.collapsed
            }
            UiButton {
                id: accountButton
                width: parent.width; height: 36; alignLeft: true
                tooltip: "账号菜单"; onClicked: accountMenu.open()
                contentItem: Row {
                    spacing: 8
                    Rectangle {
                        width: 22; height: 22; radius: 4; color: Theme.selected
                        anchors.verticalCenter: parent.verticalCenter
                        UiText { anchors.centerIn: parent; text: appController.form.username.slice(0, 1) || "·"; font.pixelSize: 11; color: Theme.muted }
                    }
                    UiText {
                        visible: !window.collapsed; width: accountButton.width - 58
                        anchors.verticalCenter: parent.verticalCenter
                        text: appController.form.username || "登录账号"
                        elide: Text.ElideRight
                    }
                    Icon { visible: !window.collapsed; name: "chevron"; width: 12; anchors.verticalCenter: parent.verticalCenter }
                }
                Popup {
                    id: accountMenu
                    y: accountButton.height + 4; width: 208; padding: 4
                    background: Rectangle { color: Theme.surface; radius: 4; border.width: 1; border.color: Theme.border }
                    contentItem: Column {
                        UiButton { width: parent.width; text: "账号设置"; alignLeft: true; onClicked: { accountMenu.close(); window.collapsed = false; window.settingsVisible = true } }
                    }
                }
            }
            UiButton {
                objectName: "navLive"
                width: parent.width; text: window.collapsed ? "" : "直播"; iconName: "camera"
                selected: !window.settingsVisible; alignLeft: !window.collapsed
                ink: selected ? Theme.text : Theme.muted
                tooltip: window.collapsed ? "直播" : ""
                onClicked: window.settingsVisible = false
            }
            UiButton {
                objectName: "navSettings"
                width: parent.width; text: window.collapsed ? "" : "设置"; iconName: "settings"
                selected: window.settingsVisible; alignLeft: !window.collapsed
                ink: selected ? Theme.text : Theme.muted
                tooltip: window.collapsed ? "设置" : ""
                onClicked: { window.settingsVisible = true; window.collapsed = false }
            }
        }
        Item {
            anchors.top: navigation.bottom; anchors.topMargin: 20
            anchors.bottom: actions.top; width: parent.width
            visible: !window.collapsed
            Column {
                id: coursesPanel
                anchors.fill: parent; anchors.leftMargin: 16; anchors.rightMargin: 16
                spacing: 8; visible: !window.settingsVisible
                Item {
                    width: parent.width; height: 28
                    UiText { text: "今明直播课"; color: Theme.muted; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
                    UiButton { text: "刷新"; width: 40; height: 26; anchors.right: parent.right; enabled: !appController.state.busy; onClicked: appController.refreshCourses() }
                }
                ListView {
                    id: courseList
                    objectName: "courseList"
                    width: parent.width
                    height: Math.min(contentHeight, Math.max(100, coursesPanel.height - courseHint.implicitHeight - 60))
                    clip: true; reuseItems: true; spacing: 6
                    model: appController.courses
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                    delegate: ItemDelegate {
                        id: courseDelegate
                        required property var entry
                        width: courseList.width
                        height: courseContent.implicitHeight + 20
                        padding: 10
                        enabled: !appController.state.busy
                        hoverEnabled: true
                        onClicked: appController.selectCourse(entry.url)
                        background: Rectangle {
                            radius: 4
                            color: appController.state.selectedUrl === courseDelegate.entry.url ? Theme.selected : courseDelegate.hovered ? Theme.hover : "transparent"
                        }
                        contentItem: Column {
                            id: courseContent
                            spacing: 4
                            RowLayout {
                                width: parent.width
                                UiText { Layout.fillWidth: true; text: courseDelegate.entry.title; elide: Text.ElideRight; font.pixelSize: 13 }
                                UiText { text: courseDelegate.entry.time; font.family: Theme.mono; font.pixelSize: 11; color: Theme.subtle }
                            }
                            UiText { width: parent.width; text: "•  " + courseDelegate.entry.summary; font.pixelSize: 12; color: Theme.muted; elide: Text.ElideRight }
                            UiText { visible: text.length > 0; width: parent.width; text: courseDelegate.entry.detail; font.pixelSize: 12; color: Theme.muted; elide: Text.ElideRight }
                        }
                    }
                }
                UiText { id: courseHint; width: parent.width; text: appController.state.courseHint; wrapMode: Text.Wrap; color: Theme.subtle; font.pixelSize: 11; lineHeight: 1.5 }
            }
        }
        Column {
            id: actions
            anchors.bottom: parent.bottom; anchors.bottomMargin: 24
            anchors.left: parent.left; anchors.right: parent.right; anchors.margins: window.collapsed ? 10 : 14
            spacing: 12
            UiText {
                width: parent.width; visible: !window.collapsed && text.length > 0
                text: appController.state.feedback; color: appController.state.feedbackError ? Theme.red : Theme.subtle
                font.pixelSize: 11; wrapMode: Text.Wrap
            }
            UiButton {
                objectName: "monitorButton"
                width: parent.width; height: 36
                text: window.collapsed ? "" : appController.state.actionText
                iconName: appController.state.actionIcon
                danger: appController.state.destructive
                primary: !danger
                tooltip: window.collapsed ? appController.state.actionText : ""
                enabled: !appController.state.closing && !appController.state.stopping && (!appController.state.busy || appController.state.monitoring)
                onClicked: appController.toggleMonitor()
            }
        }
    }
    Rectangle { x: sidebar.width; width: 1; height: parent.height; color: Theme.border }

    Item {
        id: main
        anchors.left: sidebar.right; anchors.leftMargin: 1
        anchors.right: parent.right; anchors.top: parent.top; anchors.bottom: parent.bottom
        Item {
            id: topbar
            height: 40; width: parent.width
            Row {
                x: 12; anchors.verticalCenter: parent.verticalCenter; spacing: 4
                UiButton {
                    objectName: "pageBreadcrumb"
                    text: window.settingsVisible ? "设置" : "课堂监控"
                    iconName: window.settingsVisible ? "settings" : "radar"
                    height: 28
                    onClicked: {
                        if (window.settingsVisible) window.settingsVisible = false
                        else documentScroll.contentY = 0
                    }
                }
            }
            Row {
                anchors.right: parent.right; anchors.rightMargin: 12; anchors.verticalCenter: parent.verticalCenter
                spacing: 2
                UiButton { objectName: "focusButton"; width: 28; height: 28; iconName: "focus"; tooltip: "聚焦页面"; onClicked: window.collapsed = !window.collapsed }
                UiButton { objectName: "activityButton"; width: 28; height: 28; iconName: "history"; tooltip: "活动记录"; onClicked: { window.activityExpanded = true; Qt.callLater(function() { documentScroll.contentY = Math.min(activityToggle.y, Math.max(0, documentScroll.contentHeight - documentScroll.height)) }) } }
                UiButton {
                    id: moreButton
                    width: 28; height: 28; iconName: "more"; tooltip: "更多选项"; onClicked: moreMenu.open()
                    Popup {
                        id: moreMenu
                        x: moreButton.width - width; y: moreButton.height + 4; width: 200; padding: 4
                        background: Rectangle { color: Theme.surface; radius: 4; border.width: 1; border.color: Theme.border }
                        contentItem: Column {
                            UiButton { width: parent.width; text: window.collapsed ? "退出聚焦" : "聚焦页面"; alignLeft: true; iconName: "focus"; onClicked: { moreMenu.close(); window.collapsed = !window.collapsed } }
                            UiButton { width: parent.width; text: appController.state.dark ? "切换浅色外观" : "切换深色外观"; alignLeft: true; iconName: "sun"; onClicked: { moreMenu.close(); appController.toggleTheme() } }
                            UiButton { width: parent.width; text: "打开设置"; alignLeft: true; iconName: "settings"; onClicked: { moreMenu.close(); window.settingsVisible = true; window.collapsed = false } }
                        }
                    }
                }
            }
        }
        Flickable {
            id: documentScroll
            objectName: "documentScroll"
            anchors.top: topbar.bottom; anchors.bottom: parent.bottom; width: parent.width
            visible: !window.settingsVisible
            clip: true; contentWidth: width; contentHeight: document.height + 64
            boundsBehavior: Flickable.StopAtBounds
            ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
            Column {
                id: document
                objectName: "document"
                x: (parent.width - width) / 2; y: 32
                width: Math.min(840, documentScroll.width - 96)
                spacing: 0
                Icon { name: "radar"; width: 36; ink: Theme.muted }
                Item { width: 1; height: 8 }
                UiText { text: "课堂监控"; font.family: Theme.heading; font.pixelSize: 32; font.weight: Font.Bold }
                Item { width: 1; height: 24 }
                Row {
                    objectName: "statusRow"
                    width: parent.width; height: 28
                    Row { width: 124; spacing: 8; anchors.verticalCenter: parent.verticalCenter; Icon { name: "status"; width: 15; anchors.verticalCenter: parent.verticalCenter } UiText { text: "状态"; color: Theme.muted } }
                    Rectangle {
                        height: 24; width: statusText.implicitWidth + 28; radius: 4; anchors.verticalCenter: parent.verticalCenter
                        color: appController.state.statusKind === "active" ? Theme.greenFill : appController.state.statusKind === "error" ? Theme.redFill : appController.state.statusKind === "waiting" ? Theme.amberFill : Theme.inset
                        UiText {
                            id: statusText; anchors.centerIn: parent
                            text: "●  " + appController.state.status; font.pixelSize: 12
                            color: appController.state.statusKind === "active" ? Theme.green : appController.state.statusKind === "error" ? Theme.red : appController.state.statusKind === "waiting" ? Theme.amber : Theme.muted
                        }
                    }
                }
                Item { width: 1; height: 8 }
                Row {
                    width: parent.width; height: 28
                    Row { width: 124; spacing: 8; anchors.verticalCenter: parent.verticalCenter; Icon { name: "clock"; width: 15; anchors.verticalCenter: parent.verticalCenter } UiText { text: appController.state.timerLabel; color: Theme.muted } }
                    Rectangle {
                        height: 24; width: timerText.implicitWidth + 16; radius: 4; color: Theme.inset
                        anchors.verticalCenter: parent.verticalCenter
                        UiText { id: timerText; text: appController.state.elapsed; anchors.centerIn: parent; font.family: Theme.mono; color: Theme.muted }
                    }
                }
                Item { width: 1; height: 32 }
                UiText { text: "实时转写内容"; color: Theme.muted; font.pixelSize: 12 }
                Item { width: 1; height: 12 }
                Item {
                    objectName: "quoteBlock"
                    width: parent.width; height: Math.max(28, transcript.contentHeight) + 8
                    Rectangle { width: 3; height: parent.height; color: Theme.text; radius: 0 }
                    TextEdit {
                        id: transcript
                        objectName: "transcript"
                        x: 17; y: 4; width: parent.width - 17; height: contentHeight
                        // Escape ASR text before applying paragraph spacing; it
                        // remains selectable and never interprets spoken markup.
                        text: "<p style='line-height:160%; margin:0;'>" + appController.state.transcript.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/\n/g, "<br>") + "</p>"
                        textFormat: TextEdit.RichText
                        color: appController.state.transcriptFinal ? Theme.text : Theme.muted
                        font.family: Theme.body; font.pixelSize: 17
                        renderType: Text.QtRendering
                        readOnly: true; selectByMouse: true; wrapMode: TextEdit.Wrap
                        selectionColor: Theme.selected; selectedTextColor: Theme.text
                    }
                }
                UiText { visible: text.length > 0; width: parent.width - 17; x: 17; topPadding: 8; text: appController.state.transcriptHint; color: Theme.subtle; font.pixelSize: 12; wrapMode: Text.Wrap }
                Item { width: 1; height: 24 }
                Rectangle {
                    objectName: "codeCard"
                    width: parent.width; height: 76; radius: 4
                    color: Theme.callout; border.width: Theme.dark ? 1 : 0; border.color: Theme.border
                    Row {
                        anchors.left: parent.left; anchors.leftMargin: 16; anchors.verticalCenter: parent.verticalCenter
                        spacing: 12
                        Icon { name: "key"; width: 20; ink: Theme.calloutInk; anchors.verticalCenter: parent.verticalCenter }
                        UiText { text: "签到码"; color: Theme.calloutInk; anchors.verticalCenter: parent.verticalCenter }
                        Row {
                            spacing: 8
                            Repeater {
                                model: 4
                                Rectangle {
                                    required property int index
                                    width: 40; height: 42; radius: 4; color: Theme.surface
                                    border.width: 1; border.color: Theme.border
                                    UiText { anchors.centerIn: parent; text: appController.state.code.length === 4 ? appController.state.code[index] : "—"; font.family: Theme.mono; font.pixelSize: 24; font.bold: true; color: appController.state.code.length ? Theme.text : Theme.subtle }
                                }
                            }
                        }
                        Item { width: 4; height: 1 }
                        UiButton { objectName: "copyButton"; anchors.verticalCenter: parent.verticalCenter; text: appController.state.copied ? "已复制" : "复制"; iconName: appController.state.copied ? "check" : "copy"; enabled: appController.state.code.length === 4; onClicked: appController.copyCode() }
                    }
                }
                Item { width: 1; height: 20 }
                UiButton {
                    id: activityToggle
                    objectName: "activityToggle"
                    width: parent.width; alignLeft: true
                    onClicked: window.activityExpanded = !window.activityExpanded
                    contentItem: Row {
                        spacing: 8
                        Icon { name: "triangle"; width: 12; rotation: window.activityExpanded ? 90 : 0; anchors.verticalCenter: parent.verticalCenter; Behavior on rotation { NumberAnimation { duration: 100 } } }
                        UiText { text: "活动记录"; color: Theme.muted; font.pixelSize: 14; anchors.verticalCenter: parent.verticalCenter }
                    }
                }
                Loader {
                    id: activityContent
                    active: window.activityExpanded
                    width: parent.width
                    sourceComponent: Column {
                    width: parent.width; spacing: 12
                    Item { width: 1; height: 4 }
                    UiText { visible: appController.activity.count === 0; text: "暂无签到记录"; color: Theme.subtle; x: 24 }
                    ListView {
                        id: activityList
                        x: 24; width: parent.width - 24; height: Math.min(contentHeight, 240)
                        model: appController.activity
                        clip: true; reuseItems: true; spacing: 8
                        onCountChanged: if (window.followLogs) Qt.callLater(positionViewAtEnd)
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Rectangle {
                            required property var entry
                            width: activityList.width; height: activityBody.height + 20; radius: 4
                            color: "transparent"; border.width: 1; border.color: Theme.border
                            Column {
                                id: activityBody; x: 12; y: 10; width: parent.width - 24; spacing: 6
                                UiText { text: entry.time; font.family: Theme.mono; font.pixelSize: 11; color: Theme.subtle }
                                UiText { width: parent.width; text: entry.text; wrapMode: Text.Wrap; color: entry.kind === "error" ? Theme.red : Theme.text }
                            }
                        }
                    }
                    Row {
                        anchors.right: parent.right; spacing: 12
                        CheckBox { text: "自动滚动"; checked: window.followLogs; onToggled: window.followLogs = checked; font.family: Theme.body; font.pixelSize: 12; palette.windowText: Theme.muted; palette.text: Theme.muted }
                        UiButton { text: "清空"; onClicked: appController.clearActivity() }
                    }
                    ListView {
                        id: logList
                        objectName: "logList"
                        width: parent.width; height: 240
                        model: appController.logs
                        clip: true; reuseItems: true
                        onCountChanged: if (window.followLogs) Qt.callLater(positionViewAtEnd)
                        ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
                        delegate: Item {
                            required property var entry
                            width: logList.width; height: Math.max(20, logText.implicitHeight) + 12
                            UiText { id: logTime; x: 4; y: 6; text: entry.time; font.family: Theme.mono; font.pixelSize: 11; color: Theme.subtle }
                            UiText { id: logText; x: 76; y: 6; width: parent.width - x - 8; text: entry.text; wrapMode: Text.Wrap; color: entry.kind === "error" ? Theme.red : entry.kind === "warning" ? Theme.amber : Theme.muted }
                        }
                        UiText { visible: appController.logs.count === 0; anchors.centerIn: parent; text: "监控开始后，活动记录会显示在这里"; color: Theme.subtle }
                    }
                    }
                }
            }
        }
        SettingsPanel {
            objectName: "settingsPage"
            anchors.top: topbar.bottom; anchors.bottom: parent.bottom
            width: parent.width
            visible: window.settingsVisible
        }
    }
}
