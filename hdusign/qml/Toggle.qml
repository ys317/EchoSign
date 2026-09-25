import QtQuick
import QtQuick.Controls

AbstractButton {
    id: control
    property string fieldKey
    property string caption
    width: parent.width
    height: 32
    checkable: true
    checked: Boolean(appController.form[fieldKey])
    onToggled: appController.setField(fieldKey, checked)
    Accessible.name: caption
    UiText { text: control.caption; color: Theme.muted; anchors.verticalCenter: parent.verticalCenter }
    Rectangle {
        width: 30; height: 18; radius: 4
        anchors.right: parent.right; anchors.verticalCenter: parent.verticalCenter
        color: control.checked ? Theme.text : Theme.border
        Rectangle {
            x: control.checked ? 14 : 3; y: 3; width: 12; height: 12; radius: 3
            color: control.checked ? Theme.canvas : Theme.muted
            Behavior on x { NumberAnimation { duration: 90 } }
        }
        border.width: control.activeFocus ? 1 : 0
        border.color: Theme.muted
    }
}
