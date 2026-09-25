"""Render the actual QML and exercise input with isolated demo services."""
from pathlib import Path
import tempfile
import unittest

import shiboken6
from PySide6.QtCore import QObject, QPointF, Qt, qInstallMessageHandler
from PySide6.QtGui import QGuiApplication
from PySide6.QtTest import QTest

from hdusign.demo import DemoController, prepare_demo
from hdusign.qt_app import create_engine

APP = QGuiApplication.instance() or QGuiApplication([])
APP.setQuitOnLastWindowClosed(False)


class QmlDesktopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        prepare_demo(self.root)
        self.c = DemoController(self.root)
        self.c._clock.stop()
        self.messages = []
        self.old_handler = qInstallMessageHandler(lambda kind, context, msg: self.messages.append(msg))
        self.engine, self.window = create_engine(self.c, APP)
        QTest.qWait(100)

    def tearDown(self):
        self.c.shutdown()
        if self.c.worker:
            self.c.worker.join(2)
        shiboken6.delete(self.engine)
        shiboken6.delete(self.c)
        self.tmp.cleanup()
        qInstallMessageHandler(self.old_handler)
        self.assertEqual(self.messages, [])

    def item(self, name):
        item = self.window.findChild(QObject, name)
        self.assertIsNotNone(item, name)
        return item

    def click(self, name):
        item = self.item(name)
        pos = item.mapToScene(QPointF(item.width() / 2, item.height() / 2)).toPoint()
        QTest.mouseClick(self.window, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, pos)
        QTest.qWait(50)

    def test_quote_is_content_height_and_clamps_document_width(self):
        self.c.populate_monitor()
        QTest.qWait(30)
        quote, transcript = self.item('quoteBlock'), self.item('transcript')
        self.assertAlmostEqual(quote.height(), max(28, transcript.property('contentHeight')) + 8)
        initial = quote.height()
        self.c.consume(['[ASR 00:00:00] ' + '这是一段很长的课堂转写。' * 60])
        QTest.qWait(30)
        self.assertGreater(quote.height(), initial * 3)
        self.c.consume(['[ASR 00:00:01] 简短转写。'])
        QTest.qWait(30)
        self.assertAlmostEqual(quote.height(), initial)
        for width in (960, 1400):
            self.window.setWidth(width)
            QTest.qWait(40)
            self.assertLessEqual(self.item('document').width(), 840)
            card, button = self.item('codeCard'), self.item('copyButton')
            self.assertLess(button.mapToItem(card, QPointF(button.width(), 0)).x(), card.width())

    def test_theme_copy_focus_and_activity_toggle_receive_mouse_input(self):
        self.c.populate_monitor()
        self.click('copyButton')
        self.assertEqual(APP.clipboard().text(), '2330')
        self.assertTrue(self.c._state['copied'])
        self.assertIsNone(self.window.findChild(QObject, 'logList'))
        self.click('activityToggle')
        self.assertTrue(self.window.property('activityExpanded'))
        self.assertIsNotNone(self.item('logList'))
        self.click('activityToggle')
        self.assertFalse(self.window.property('activityExpanded'))
        self.assertIsNone(self.window.findChild(QObject, 'logList'))
        self.click('focusButton')
        self.assertTrue(self.window.property('collapsed'))
        self.c.toggleTheme()
        QTest.qWait(30)
        self.assertEqual(self.window.color().name(), '#ffffff')
        self.assertFalse(self.window.grabWindow().isNull())

    def test_text_entry_survives_timer_and_transcript_updates(self):
        self.click('navSettings')
        field = self.item('field_username')
        self.click('field_username')
        QTest.keyClick(self.window, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
        for character in '12345':
            QTest.keyClick(self.window, ord(character))
        before = field.property('cursorPosition')
        self.c._publish(elapsed='00:00:41', transcript='新的转写')
        QTest.qWait(20)
        self.assertEqual(field.property('text'), '12345')
        self.assertEqual(field.property('cursorPosition'), before)
        self.assertEqual(self.c._form['username'], '12345')

    def test_invalid_field_is_scrolled_into_view(self):
        self.c.setField('longitude', 'NaN')
        self.c.save()
        QTest.qWait(80)
        field = self.item('field_longitude')
        self.assertTrue(self.window.property('settingsVisible'))
        self.assertTrue(field.hasActiveFocus())
        top = field.mapToScene(QPointF()).y()
        self.assertGreater(top, 160)
        self.assertLess(top + field.height(), self.window.height() - 80)

    def test_settings_is_a_workspace_page_with_existing_actions(self):
        self.click('navSettings')
        settings = self.item('settingsPage')
        self.assertTrue(settings.isVisible())
        self.assertFalse(self.item('documentScroll').isVisible())
        self.assertEqual(self.item('pageBreadcrumb').property('text'), '设置')
        self.assertGreater(settings.width(), 700)
        self.assertTrue(self.item('field_username').isVisible())
        for name in ('field_password', 'field_url', 'field_latitude', 'field_longitude',
                     'field_rules', 'field_webhook'):
            self.assertIsNotNone(self.item(name), name)
        self.assertIsNotNone(self.item('navLive'))
        self.assertIsNotNone(self.item('monitorButton'))

    def test_monitor_stop_and_close_complete_without_blocking_window(self):
        self.click('monitorButton')
        self.assertEqual(self.c._task, 'monitor')
        self.assertTrue(self.c._state['monitoring'])
        self.assertFalse(self.window.close())
        for _ in range(50):
            if not self.c._task:
                break
            QTest.qWait(20)
        self.assertFalse(self.c._task)
        self.assertFalse(self.window.isVisible())


if __name__ == '__main__':
    unittest.main()
