import QtQuick
import QtQuick.Controls

Flickable {
    id: panel
    clip: true
    contentWidth: width
    contentHeight: fields.height + 24
    boundsBehavior: Flickable.StopAtBounds
    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }
    Column {
        id: fields
        x: 16; y: 8; width: panel.width - 32; spacing: 12
        Item {
            width: parent.width; height: settingsHeading.implicitHeight + settingsSubtitle.implicitHeight + 12
            Column {
                anchors.left: parent.left; anchors.right: parent.right; anchors.bottom: parent.bottom
                spacing: 6
                UiText { id: settingsHeading; objectName: "settingsHeading"; text: "设置"; font.family: Theme.heading; font.pixelSize: 30; font.weight: Font.Bold }
                UiText { id: settingsSubtitle; width: parent.width; text: "账号、声音来源、签到辅助与识别规则"; color: Theme.muted; font.pixelSize: 13; wrapMode: Text.Wrap }
            }
        }
        Row {
            width: parent.width; spacing: 8
            UiButton { width: 86; text: appController.state.dark ? "浅色外观" : "深色外观"; iconName: appController.state.dark ? "sun" : "moon"; onClicked: appController.toggleTheme() }
            UiButton { text: "保存设置"; width: 94; onClicked: appController.save() }
        }
        UiText { text: "直播账号"; font.family: Theme.heading; font.pixelSize: 14 }
        Field { viewport: panel; caption: "学号 / 账号"; fieldKey: "username"; enabled: !appController.state.busy }
        Field { viewport: panel; caption: "密码"; fieldKey: "password"; secret: true; enabled: !appController.state.busy }
        UiButton { width: parent.width; text: "登录并读取课程"; primary: true; enabled: !appController.state.busy; onClicked: appController.login(false) }
        UiButton { width: parent.width; text: "单独登录直播账号"; alignLeft: true; enabled: !appController.state.busy; onClicked: appController.login(true) }
        Rectangle { width: parent.width; height: 1; color: Theme.border }
        UiText { text: "声音来源"; font.family: Theme.heading; font.pixelSize: 14 }
        Toggle { caption: "后台直播音频"; fieldKey: "live" }
        Field { viewport: panel; caption: "课程网址（选填）"; fieldKey: "url"; hint: "选课后自动填写，也可粘贴课程链接。" }
        UiButton { text: "打开课程页面 ↗"; alignLeft: true; onClicked: appController.openCourse() }
        Rectangle { width: parent.width; height: 1; color: Theme.border }
        UiText { text: "签到辅助"; font.family: Theme.heading; font.pixelSize: 14 }
        Toggle { caption: "自动签到"; fieldKey: "autoSign" }
        UiButton { width: parent.width; text: "重新登录签到"; enabled: !appController.state.busy; onClicked: appController.runAction("signin") }
        Field { viewport: panel; caption: "纬度"; fieldKey: "latitude" }
        Field { viewport: panel; caption: "经度"; fieldKey: "longitude" }
        UiButton { width: parent.width; text: "获取当前位置"; enabled: !appController.state.busy; onClicked: appController.runAction("locate") }
        UiText { width: parent.width; text: appController.state.locationHint; wrapMode: Text.Wrap; color: Theme.subtle; font.pixelSize: 11 }
        Rectangle { width: parent.width; height: 1; color: Theme.border }
        UiText { text: "识别与通知"; font.family: Theme.heading; font.pixelSize: 14 }
        Toggle { caption: "语义辅助识别"; fieldKey: "semantic" }
        UiText { text: "签到关键词（每行一项）"; color: Theme.muted; font.pixelSize: 12 }
        ScrollView {
            width: parent.width; height: 132
            TextArea {
                objectName: "field_rules"
                text: appController.form.rules
                onTextChanged: if (activeFocus) appController.setField("rules", text)
                color: Theme.text; font.family: Theme.body; font.pixelSize: 13
                wrapMode: TextEdit.Wrap; selectByMouse: true
                background: Rectangle { color: Theme.surface; radius: 4; border.width: 1; border.color: Theme.border }
            }
        }
        Field { viewport: panel; caption: "企业微信 Webhook"; fieldKey: "webhook"; secret: true }
        UiButton { width: parent.width; text: "测试推送"; enabled: !appController.state.busy; onClicked: appController.runAction("webhook") }
        UiText { text: appController.state.version; color: Theme.subtle; font.pixelSize: 11 }
    }
}
