"""Focused contracts for scheduling a future live lesson."""
from __future__ import annotations

import datetime as dt
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from echosign import gui
from echosign.live import LiveCourse


ZONE = dt.timezone(dt.timedelta(hours=8))
NOW = dt.datetime(2026, 9, 22, 12, 0, tzinfo=ZONE).timestamp()


class _Var:
    def __init__(self, value=""):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


class _Widget:
    def __init__(self):
        self.calls = []

    def configure(self, **kwargs):
        self.calls.append(kwargs)


def future_course() -> LiveCourse:
    start = dt.datetime(2026, 9, 23, 8, 55, tzinfo=ZONE).timestamp()
    end = dt.datetime(2026, 9, 23, 9, 40, tzinfo=ZONE).timestamp()
    return LiveCourse("123", "网络安全", start, end, teacher="王老师", tecl_id="456")


class ScheduledMonitorTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(gui.App)
        self.app._scheduled_course = None
        self.app._task_kind = None
        self.app._closing = False
        self.app._loading = False
        self.app._live_courses = []
        self.app._live_course_lookup = {}
        self.app.b_monitor = _Widget()
        self.app._dot = _Widget()
        self.app._status = _Widget()
        self.app._live_course_hint = _Widget()
        self.app._transcript = _Widget()
        self.app._transcript_hint = _Widget()
        self.app._metrics = {"time": _Widget()}
        self.app.stop_event = threading.Event()
        self.app.v_live_course = _Var()
        self.app.v_url = _Var()
        self.app.v_live = _Var(False)
        self.app.cfg = {}
        self.logs = []
        self.app.logs = self.logs
        self.app.logline = self.logs.append

    def test_tomorrow_course_is_labelled_before_the_title(self):
        course = future_course()
        self.assertEqual(gui.App._course_label(course, now=NOW), "明日 08:55 · 网络安全 · 王老师")

    def test_future_selection_changes_the_main_action_to_schedule(self):
        course = future_course()
        self.app._live_course_lookup = {"网络安全": course}
        self.app.v_live_course.set("网络安全")
        with patch.object(gui.time, "time", return_value=NOW):
            self.app._update_monitor_button()
        self.assertEqual(self.app.b_monitor.calls[-1]["text"], "预约监控")

    def test_scheduling_stores_the_course_and_shows_a_cancellable_state(self):
        course = future_course()
        with patch.object(gui.time, "time", return_value=NOW), \
                patch.object(self.app, "save_cfg", return_value=True) as save:
            self.assertTrue(self.app._schedule_monitor(course))
        self.assertEqual(self.app._scheduled_course, course)
        save.assert_called_once_with()
        self.assertEqual(self.app.b_monitor.calls[-1]["text"], "取消预约")
        self.assertEqual(self.app._status.calls[-1]["text"], "已预约")
        self.assertIn("到点会自动启动监控", self.app._live_course_hint.calls[-1]["text"])

    def test_cancelling_clears_the_course_and_restores_the_main_action(self):
        course = future_course()
        self.app._scheduled_course = course
        with patch.object(self.app, "_write_scheduled_course", return_value=True) as write:
            self.assertTrue(self.app._cancel_scheduled_course())
        self.assertIsNone(self.app._scheduled_course)
        write.assert_called_once_with(None)
        self.assertEqual(self.app.b_monitor.calls[-1]["text"], "启动监控")
        self.assertIn("已取消", self.app._live_course_hint.calls[-1]["text"])

    def test_due_course_uses_the_normal_monitor_start_path(self):
        course = future_course()
        self.app._scheduled_course = course
        due = course.start + gui.SCHEDULE_START_DELAY + 1
        with patch.object(gui.time, "time", return_value=due), \
                patch.object(self.app, "start_monitor", return_value=True) as start:
            self.app._check_scheduled_monitor()
        self.assertIsNone(self.app._scheduled_course)
        start.assert_called_once_with()
        self.assertIn("预约课程到点", self.logs[-1])

    def test_manual_monitor_start_cancels_a_waiting_appointment(self):
        self.app._scheduled_course = future_course()
        with patch.object(self.app, "_busy", return_value=False), \
                patch.object(self.app, "_cancel_scheduled_course", return_value=True) as cancel, \
                patch.object(self.app, "save_cfg", return_value=True), \
                patch.object(self.app, "_worker", return_value=True) as worker:
            self.assertTrue(self.app.start_monitor())
        cancel.assert_called_once_with(notify=False)
        worker.assert_called_once()

    def test_scheduled_course_data_round_trips_without_credentials(self):
        course = future_course()
        data = gui.App._scheduled_course_data(course)
        self.assertEqual(gui.App._scheduled_course_from_data(data), course)
        self.assertNotIn("password", data)
        self.assertNotIn("cookies", data)

    def test_scheduled_course_is_persisted_in_the_user_config(self):
        course = future_course()
        self.app._save_state = _Widget()
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.yaml"
            with patch.object(gui, "CONFIG", path), patch.object(gui, "load_cfg", return_value={}):
                self.assertTrue(self.app._write_scheduled_course(course))
            saved = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["scheduled_course"], gui.App._scheduled_course_data(course))

    def test_restore_reselects_the_saved_course_and_direct_audio(self):
        course = future_course()
        self.app.cfg = {"scheduled_course": gui.App._scheduled_course_data(course)}
        with patch.object(self.app, "_show_scheduled_state") as show, \
                patch.object(self.app, "_update_audio_mode") as audio_mode, \
                patch.object(self.app, "_write_scheduled_course") as write:
            self.app._restore_scheduled_course()
        self.assertEqual(self.app._scheduled_course, course)
        self.assertIn("courseId=123", self.app.v_url.get())
        self.assertTrue(self.app.v_live.get())
        audio_mode.assert_called_once_with()
        show.assert_called_once_with(restored=True)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
