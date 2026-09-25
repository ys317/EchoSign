"""Offline Qt input/queue responsiveness benchmark, not a frame-rate guarantee."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QObject, QPointF, Qt, QTimer, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest
import shiboken6

from hdusign.demo import DemoController, prepare_demo
from hdusign.qt_app import create_engine


def summary(samples):
    ordered = sorted(samples)
    return dict(count=len(samples), median_ms=round(statistics.median(samples), 3),
                p95_ms=round(ordered[min(len(ordered) - 1, int(len(ordered) * .95))], 3),
                max_ms=round(max(samples), 3))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/qt-profile.json')
    args = parser.parse_args()
    messages = []
    qInstallMessageHandler(lambda kind, ctx, msg: messages.append(msg))
    app = QGuiApplication([])
    app.setQuitOnLastWindowClosed(False)
    with tempfile.TemporaryDirectory() as tmp:
        prepare_demo(Path(tmp))
        c = DemoController(Path(tmp))
        c._clock.stop()
        c.populate_monitor()
        engine, window = create_engine(c, app)
        QTest.qWait(350)
        report = dict(renderer=str(window.rendererInterface().graphicsApi()),
                      dpi=window.devicePixelRatio(),
                      scenario='160 messages per 33 ms; alternating partial transcripts and ordinary logs; simulated services only')
        for expanded in (False, True):
            window.setProperty('activityExpanded', expanded)
            QTest.qWait(100)
            scroll = window.findChild(QObject, 'documentScroll')
            if expanded:
                scroll.setProperty('contentY', max(0, scroll.property('contentHeight') - scroll.height()))
            drains, events, clicks = [], [], []
            index = 0
            previous = time.perf_counter()

            def heartbeat():
                nonlocal previous
                now = time.perf_counter()
                events.append((now - previous) * 1000)
                previous = now

            def burst():
                nonlocal index
                index += 1
                for row in range(160):
                    c.log_queue.put(f'…识别中: 实时转写 {index}-{row}' if row % 2 else f'[i] 模拟活动 {index}-{row}')
                start = time.perf_counter()
                c.drain()
                drains.append((time.perf_counter() - start) * 1000)
                if index % 4 == 0:
                    # Real input dispatch through Qt, including sidebar layout.
                    button = window.findChild(QObject, 'focusButton')
                    pos = button.mapToScene(QPointF(button.width() / 2, button.height() / 2)).toPoint()
                    before = bool(window.property('collapsed'))
                    start = time.perf_counter()
                    QTest.mouseClick(window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
                    assert bool(window.property('collapsed')) != before
                    clicks.append((time.perf_counter() - start) * 1000)

            pulse, producer = QTimer(), QTimer()
            pulse.setTimerType(Qt.TimerType.PreciseTimer)
            producer.setTimerType(Qt.TimerType.PreciseTimer)
            pulse.timeout.connect(heartbeat)
            producer.timeout.connect(burst)
            pulse.start(16)
            producer.start(33)
            c._drain_timer.stop()
            QTest.qWait(3500)
            pulse.stop()
            producer.stop()
            report['expanded' if expanded else 'collapsed'] = dict(
                batches=index, queue_batch=summary(drains), input_dispatch=summary(clicks),
                event_loop_interval=summary(events),
                retained_logs=c.log_model.count, queued=c.log_queue.qsize())
        c.shutdown()
        shiboken6.delete(engine)
        shiboken6.delete(c)
    report['qml_warnings'] = messages
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if messages:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
