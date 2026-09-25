"""Qt Quick desktop entry point and vector icon provider."""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote

from PySide6.QtCore import QPointF, QRectF, QSize, QUrl, Qt, qInstallMessageHandler
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QImage, QPainter, QPainterPath, QPen, QPolygonF
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuick import QQuickImageProvider
from PySide6.QtQuickControls2 import QQuickStyle

from hdusign.desktop_controller import Controller
from hdusign.runtime import resource_root


class Icons(QQuickImageProvider):
    def __init__(self):
        super().__init__(QQuickImageProvider.ImageType.Image)

    def requestImage(self, identifier, size, requested):
        name, _, color = identifier.partition("/")
        edge = max(16, min(256, requested.width() if requested.isValid() else 64))
        image = QImage(edge, edge, QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.scale(edge / 24, edge / 24)
        ink = QColor(unquote(color))
        if not ink.isValid():
            ink = QColor("#787774")
        painter.setPen(QPen(ink, 1.5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))

        def line(points):
            path = QPainterPath(QPointF(*points[0]))
            for point in points[1:]:
                path.lineTo(*point)
            painter.drawPath(path)

        def circle(x, y, radius):
            painter.drawEllipse(QPointF(x, y), radius, radius)

        if name == "radar":
            circle(12, 12, 9)
            circle(12, 12, 5)
            line([(12, 12), (19, 5)])
            painter.setBrush(ink)
            circle(12, 12, 1)
            circle(7, 16, .9)
        elif name == "clock":
            circle(12, 12, 8)
            line([(12, 7), (12, 12), (16, 14)])
        elif name == "status":
            circle(12, 12, 7)
            painter.setBrush(ink)
            circle(12, 12, 2.5)
        elif name == "key":
            circle(8, 8, 4)
            line([(11, 11), (20, 20), (22, 18)])
            line([(17, 17), (19, 15)])
        elif name in ("chevron", "collapse", "expand"):
            line({"chevron": [(8, 10), (12, 14), (16, 10)],
                  "collapse": [(14, 7), (9, 12), (14, 17)],
                  "expand": [(10, 7), (15, 12), (10, 17)]}[name])
        elif name == "copy":
            painter.drawRoundedRect(QRectF(8, 8, 12, 13), 2, 2)
            line([(5, 16), (3, 16), (3, 3), (15, 3), (15, 5)])
        elif name == "check":
            line([(5, 12), (10, 17), (20, 6)])
        elif name == "more":
            painter.setBrush(ink)
            for x in (5, 12, 19):
                circle(x, 12, 1)
        elif name in ("play", "triangle"):
            painter.setBrush(ink)
            painter.drawPolygon(QPolygonF([QPointF(9, 6), QPointF(17, 12), QPointF(9, 18)]))
        elif name == "stop":
            painter.setBrush(ink)
            painter.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
        elif name == "focus":
            for points in ([(8, 3), (3, 3), (3, 8)], [(16, 3), (21, 3), (21, 8)],
                           [(3, 16), (3, 21), (8, 21)], [(21, 16), (21, 21), (16, 21)]):
                line(points)
        elif name == "history":
            painter.drawArc(QRectF(4, 4, 16, 16), -45 * 16, 290 * 16)
            line([(3, 3), (3, 9), (9, 9)])
            line([(12, 7), (12, 12), (16, 14)])
        elif name == "camera":
            painter.drawRoundedRect(QRectF(3, 6, 12, 12), 2, 2)
            line([(15, 9), (21, 6), (21, 18), (15, 15)])
        elif name == "settings":
            for y, x in ((6, 15), (12, 8), (18, 15)):
                line([(3, y), (21, y)])
                painter.setBrush(ink)
                circle(x, y, 1.7)
        elif name == "sun":
            circle(12, 12, 4)
            for a, b in (((12, 2), (12, 4)), ((12, 20), (12, 22)), ((2, 12), (4, 12)),
                         ((20, 12), (22, 12)), ((5, 5), (6, 6)), ((18, 18), (19, 19)),
                         ((5, 19), (6, 18)), ((18, 6), (19, 5))):
                line([a, b])
        elif name == "moon":
            path = QPainterPath(QPointF(16, 3))
            path.cubicTo(2, 0, 0, 19, 12, 21)
            path.cubicTo(17, 22, 22, 17, 21, 13)
            path.cubicTo(12, 18, 8, 9, 16, 3)
            painter.drawPath(path)
        painter.end()
        size.setWidth(edge)
        size.setHeight(edge)
        return image


def create_engine(controller, app=None):
    app = app or QGuiApplication.instance()
    # PySide6 wheels no longer ship the legacy bundled-font directory, while
    # Basic Controls still probes it during first initialization. Keep that
    # harmless deployment warning out of the application's diagnostics while
    # forwarding all other Qt messages to the caller's handler.
    previous_handler = qInstallMessageHandler(None)
    def forward_message(kind, context, message):
        if message.startswith("QFontDatabase: Cannot find font directory"):
            return
        if previous_handler:
            previous_handler(kind, context, message)
    qInstallMessageHandler(forward_message)
    if QQuickStyle.name() != "Basic":
        QQuickStyle.setStyle("Basic")
    # Generic families are resolved by the platform font backend. Explicitly
    # probing Qt's removed bundled-font directory emits a warning on PySide6.
    body = "sans-serif"
    heading = body
    mono = "monospace"
    app.setFont(QFont(body, 10))
    engine = QQmlApplicationEngine()
    load_errors = []
    engine.warnings.connect(lambda errors: load_errors.extend(error.toString() for error in errors))
    engine.addImageProvider("icons", Icons())
    context = engine.rootContext()
    context.setContextProperty("appController", controller)
    context.setContextProperty("bodyFont", body)
    context.setContextProperty("headingFont", heading)
    context.setContextProperty("monoFont", mono)
    # In a frozen package QML remains replaceable data next to the Qt libraries.
    qml = resource_root() / "hdusign" / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml)))
    if not engine.rootObjects():
        raise RuntimeError("无法加载 HDUSign Qt Quick 界面：\n" + "\n".join(load_errors))
    window = engine.rootObjects()[0]
    controller.closeReady.connect(window.close)
    return engine, window


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv[:1])
    app.setApplicationName("HDUSign")
    app.setOrganizationName("HDUSign")
    app.setWindowIcon(QIcon(str(resource_root() / "assets" / "hdusign.ico")))
    controller = Controller()
    engine, window = create_engine(controller, app)
    app.aboutToQuit.connect(controller.shutdown)
    result = app.exec()
    # Destroy QML before its context objects to avoid teardown binding warnings.
    window.setVisible(False)
    import shiboken6
    shiboken6.delete(engine)
    return result


def check_desktop_runtime():
    """Load packaged QML, render both themes and verify local state bindings."""
    import tempfile
    import shiboken6
    from PySide6.QtCore import QEventLoop, QTimer, qInstallMessageHandler

    messages = []
    previous = qInstallMessageHandler(lambda kind, ctx, msg: messages.append(msg))
    app = QGuiApplication.instance() or QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    controller = engine = None
    try:
        with tempfile.TemporaryDirectory(prefix="hdusign-qt-check-") as temporary:
            controller = Controller(Path(temporary), auto_load=False)
            engine, window = create_engine(controller, app)
            controller.consume(["[ASR 00:00:00] 界面离线自检", "[i] 签到码: 0123"])
            for dark in (True, False):
                controller._publish(dark=dark)
                loop = QEventLoop()
                QTimer.singleShot(200, loop.quit)
                loop.exec()
                if window.grabWindow().isNull():
                    raise RuntimeError("Qt Quick 未生成有效画面")
                if window.color().name() != ("#191919" if dark else "#ffffff"):
                    raise RuntimeError("Qt Quick 主题绑定失效")
            report = dict(renderer=str(window.rendererInterface().graphicsApi()),
                          version=__import__('PySide6').__version__, qml=True)
    finally:
        if controller:
            controller.shutdown()
        if engine:
            shiboken6.delete(engine)
        if controller:
            shiboken6.delete(controller)
        qInstallMessageHandler(previous)
    if messages:
        raise RuntimeError("Qt Quick 自检警告：" + "\n".join(messages))
    return report


if __name__ == "__main__":
    raise SystemExit(main())
