import QtQuick
import QtQuick.Controls

AbstractButton {
    id: control
    property string iconName: ""
    property bool danger: false
    property bool primary: false
    property bool selected: false
    property bool alignLeft: false
    property string tooltip: ""
    property color ink: danger ? Theme.red : primary ? Theme.canvas : Theme.muted
    implicitHeight: 32
    implicitWidth: Math.max(32, label.implicitWidth + (iconName ? 26 : 0) + 20)
    hoverEnabled: true
    activeFocusOnTab: true
    Accessible.name: tooltip || text
    opacity: enabled ? 1 : 0.45
    background: Rectangle {
        radius: 4
        color: control.down || control.hovered ? (control.danger ? Theme.redFill : control.primary ? Theme.muted : Theme.hover)
               : control.primary ? Theme.text : control.selected ? Theme.selected : "transparent"
        border.width: control.danger || control.activeFocus ? 1 : 0
        border.color: control.activeFocus ? Theme.muted : Theme.redBorder
    }
    contentItem: Item {
        Row {
            anchors.verticalCenter: parent.verticalCenter
            x: control.alignLeft ? 10 : (parent.width - width) / 2
            spacing: 8
            Icon { visible: control.iconName !== ""; name: control.iconName; ink: control.ink; width: 16; anchors.verticalCenter: parent.verticalCenter }
            UiText { id: label; text: control.text; color: control.ink; anchors.verticalCenter: parent.verticalCenter }
        }
    }
    ToolTip.visible: hovered && tooltip.length > 0
    ToolTip.text: tooltip
    ToolTip.delay: 650
}
