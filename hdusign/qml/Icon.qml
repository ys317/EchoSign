import QtQuick

Image {
    property string name: "radar"
    property color ink: Theme.muted
    width: 18
    height: width
    sourceSize: Qt.size(width * Screen.devicePixelRatio, height * Screen.devicePixelRatio)
    source: "image://icons/" + name + "/" + encodeURIComponent(ink.toString())
    smooth: true
    cache: true
    fillMode: Image.PreserveAspectFit
}
