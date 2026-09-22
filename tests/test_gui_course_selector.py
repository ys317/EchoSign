"""Focused tests for the live-course selector presentation and selection."""
from __future__ import annotations

import unittest

from echosign import gui
from echosign.live import LiveCourse, live_course_url


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


class _Entry(_Widget):
    invalid = True


class LiveCourseSelectorTests(unittest.TestCase):
    def setUp(self):
        self.app = object.__new__(gui.App)
        self.app._live_courses = []
        self.app._live_course_lookup = {}
        self.app._task_kind = None
        self.app._closing = False
        self.app.live_course_picker = _Widget()
        self.app._live_course_hint = _Widget()
        self.app.v_live_course = _Var()
        self.app.v_url = _Var()

    def test_course_label_contains_time_and_teacher_without_growing_forever(self):
        course = LiveCourse(
            "123", "这是一门名字很长的直播课程", 1790038500, 1790041200,
            teacher="王老师", classroom="第7教研楼219")
        label = gui.App._course_label(course)
        self.assertIn("王老师", label)
        self.assertIn("08:55", label)
        self.assertLessEqual(len(label), 30)

    def test_choices_are_loaded_and_selection_writes_the_existing_url_field(self):
        course = LiveCourse("123", "网络安全", 1790038500, 1790041200,
                            teacher="王老师", tecl_id="456")
        self.app._set_live_course_choices([course])
        self.assertEqual(self.app.v_live_course.get(), "请选择直播课程")
        self.assertEqual(self.app.v_url.get(), "")
        label = next(iter(self.app._live_course_lookup))
        self.assertEqual(self.app.live_course_picker.calls[-1]["state"], "readonly")
        self.assertEqual(self.app._live_course_lookup[label], course)

        self.app._entries = {"url": _Entry()}
        self.app.v_live = _Var(False)
        self.app._select_live_course(label)
        self.assertEqual(self.app.v_url.get(), live_course_url(course))
        self.assertTrue(self.app.v_live.get())
        self.assertFalse(self.app._entries["url"].invalid)

    def test_empty_results_keep_manual_url_fallback(self):
        self.app._set_live_course_choices([])
        self.assertEqual(self.app.live_course_picker.calls[-1]["state"], "disabled")
        self.assertIn("手动粘贴", self.app._live_course_hint.calls[-1]["text"])

    def test_selection_cannot_change_the_course_during_monitoring(self):
        self.app._set_live_course_choices([LiveCourse("123", "课堂", 1, 2)])
        self.app._task_kind = "monitor"
        self.app.v_url.set("previous-course")
        self.app._select_live_course(next(iter(self.app._live_course_lookup)))
        self.assertEqual(self.app.v_url.get(), "previous-course")


if __name__ == "__main__":
    unittest.main()
