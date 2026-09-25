pragma Singleton
import QtQuick

QtObject {
    readonly property bool dark: appController.state.dark
    readonly property color canvas: dark ? "#191919" : "#ffffff"
    readonly property color sidebar: dark ? "#202020" : "#f7f6f5"
    readonly property color text: dark ? "#e6e6e5" : "#37352f"
    readonly property color muted: dark ? "#a4a4a0" : "#787774"
    readonly property color subtle: dark ? "#777773" : "#9b9a97"
    readonly property color border: dark ? "#323232" : "#e9e9e7"
    readonly property color hover: dark ? "#2c2c2c" : "#efefed"
    readonly property color selected: dark ? "#303030" : "#eae9e7"
    readonly property color inset: dark ? "#272727" : "#f1f1ef"
    readonly property color surface: dark ? "#272727" : "#ffffff"
    readonly property color red: dark ? "#f07878" : "#eb5757"
    readonly property color redFill: dark ? "#352727" : "#ffeceb"
    readonly property color redBorder: dark ? "#513434" : "#f4d5d5"
    readonly property color green: dark ? "#b3cfbf" : "#1c3829"
    readonly property color greenFill: dark ? "#29372d" : "#dbeddb"
    readonly property color amber: dark ? "#d4b972" : "#8f6b00"
    readonly property color amberFill: dark ? "#353021" : "#fbf3db"
    readonly property color callout: dark ? "#232323" : "#fbf3db"
    readonly property color calloutInk: dark ? "#b3b1a9" : "#8f6b00"
    readonly property string body: bodyFont
    readonly property string heading: headingFont
    readonly property string mono: monoFont
}
