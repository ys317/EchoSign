r"""Offline desktop regressions. Uses a withdrawn window and temporary settings.

Run with: .venv\Scripts\python.exe -m unittest discover -s tests -p test_gui.py -v
No microphone, browser login, signing or webhook requests are started.
"""
from __future__ import annotations

import copy
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from echosign import gui as ui


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (ui.APP_ROOT / "build").mkdir(exist_ok=True)
        cls.temp = tempfile.TemporaryDirectory(dir=ui.APP_ROOT / "build")
        cls.root = Path(cls.temp.name)
        cls.original_paths = ui.CONFIG, ui.SECRETS
        ui.CONFIG = cls.root / "config.yaml"
        ui.SECRETS = cls.root / "secrets_local.json"
        cls.base_cfg = {
            "live_url": "https://example.com/class",
            "location": {"lat": 29.2, "lng": 119.4},
            "auto_sign": {"enabled": False, "timeout_seconds": 180},
            "rules": {"strong": ["签到", "点名"], "semantic": {"enabled": True}},
            "alert": {"webhook": {"url": "", "levels": ["high", "code"]}},
            "device": "test-device",
        }
        ui.CONFIG.write_text(yaml.safe_dump(cls.base_cfg), encoding="utf-8")
        ui.SECRETS.write_text(json.dumps({
            "skl_username": "demo-student", "skl_password": "test-password"}), encoding="utf-8")
        cls.app = ui.App()
        cls.app.withdraw()
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        cls.app.destroy()
        ui.CONFIG, ui.SECRETS = cls.original_paths
        cls.temp.cleanup()

    def setUp(self):
        self.app._loading = True
        self.app.cfg = copy.deepcopy(self.base_cfg)
        self.app.txt_rules.delete("1.0", "end")
        self.app._load_fields()
        self.app._saved_values = self.app._field_values()
        self.app._loading = False
        self.app.txt_rules.edit_modified(False)
        self.app.stop_event.clear()
        self.app.clear_log()
        for q in (self.app.log_q, self.app.task_q):
            while not q.empty():
                q.get_nowait()

    def pump_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.app.update()
            if predicate():
                return
            time.sleep(0.01)
        self.fail("GUI task did not reach the expected state")

    def test_saves_fields_without_discarding_other_settings(self):
        self.app.v_auto.set(True)
        self.app.v_sem.set(False)
        self.app.v_lat.set(" 30.25 ")
        self.app.v_user.set(" demo-updated ")
        self.assertTrue(self.app.save_cfg())
        saved = yaml.safe_load(ui.CONFIG.read_text(encoding="utf-8"))
        self.assertEqual(saved["location"]["lat"], 30.25)
        self.assertTrue(saved["auto_sign"]["enabled"])
        self.assertFalse(saved["rules"]["semantic"]["enabled"])
        self.assertEqual(saved["device"], "test-device")
        self.assertEqual(saved["alert"]["webhook"]["levels"], ["high", "code"])
        self.assertEqual(saved["auto_sign"]["timeout_seconds"], 180)
        self.assertEqual(json.loads(ui.SECRETS.read_text())["skl_username"], "demo-updated")

    def test_invalid_coordinates_do_not_write_files(self):
        original = ui.CONFIG.read_bytes(), ui.SECRETS.read_bytes()
        for value in ("not a number", "nan", "inf", "91", "-91"):
            with self.subTest(value=value):
                self.app.v_lat.set(value)
                self.assertFalse(self.app.save_cfg())
                self.assertEqual(original, (ui.CONFIG.read_bytes(), ui.SECRETS.read_bytes()))
                self.assertEqual(self.app._active_tab, "extras")
                self.assertTrue(self.app._entries["lat"].invalid)
        self.app.v_lat.set("30")
        self.app.v_lng.set("181")
        self.assertFalse(self.app.save_cfg())

    def test_actions_do_not_start_after_validation_failure(self):
        self.app.v_lng.set("invalid")
        self.app.v_hook.set("https://example.com/webhook")
        with patch.object(self.app, "_worker") as worker:
            self.app.start_monitor()
            self.app.do_login()
            self.app.test_webhook()
            worker.assert_not_called()

    def test_save_failure_has_inline_feedback(self):
        before = copy.deepcopy(self.app.cfg)
        self.app.v_url.set("https://example.com/new")
        with patch.object(Path, "write_text", side_effect=PermissionError("denied")):
            self.assertFalse(self.app.save_cfg())
        self.assertEqual(self.app.cfg, before)
        self.assertIn("保存失败", self.app._save_state.cget("text"))

    def test_switch_tracks_programmatic_changes_and_rapid_clicks(self):
        var = ui.ctk.BooleanVar(value=False)
        switch = ui.Switch(self.app, var)
        try:
            var.set(True)
            self.pump_until(lambda: switch._position == switch._x(True))
            self.assertEqual(switch.cget("fg_color"), ui.SW_ON)
            for _ in range(7):
                switch.toggle()
            self.pump_until(lambda: switch._position == switch._x(False))
            self.assertFalse(var.get())
            self.assertEqual(switch.cget("fg_color"), ui.SW_OFF)
        finally:
            switch.destroy()

    def test_live_partial_does_not_flood_log(self):
        for i in range(30):
            self.app._append_log(f"…识别中: 测试课堂内容 {i}")
        self.assertEqual(self.app.log.get("1.0", "end-1c"), "")
        self.assertIn("29", self.app._transcript.cget("text"))
        self.app._append_log("[ASR 12:00:00] 现在开始签到")
        self.assertEqual(self.app._transcript.cget("text"), "现在开始签到")
        self.app._append_log("*** 签到提醒 [code] 12:00:00: 签到码: 2330")
        self.assertEqual(self.app._metrics["code"].cget("text"), "2330")

    def test_log_retention_and_follow_toggle(self):
        self.app.v_follow.set(False)
        with patch.object(ui, "MAX_LOG_LINES", 20), patch.object(self.app.log, "see") as see:
            for i in range(70):
                self.app._append_log(f"[i] event-{i:03d}")
            see.assert_not_called()
        lines = self.app.log.get("1.0", "end-1c").splitlines()
        self.assertEqual(len(lines), 20)
        self.assertIn("event-069", lines[-1])
        self.assertIn("event-050", lines[0])
        self.app.v_follow.set(True)

    def test_busy_task_does_not_change_monitor_controls(self):
        release = threading.Event()
        self.addCleanup(release.set)
        self.assertTrue(self.app._worker(lambda: release.wait(2), kind="login"))
        with patch.object(self.app, "save_cfg") as save:
            self.app.start_monitor()
            save.assert_not_called()
        self.assertEqual(self.app._task_kind, "login")
        self.assertEqual(self.app.b_stop.cget("state"), "disabled")
        release.set()
        self.pump_until(lambda: self.app._task_kind is None)
        self.assertEqual(self.app.b_start.cget("state"), "normal")

    def test_monitor_start_stop_is_driven_by_main_thread(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def monitor():
            print("[i] ASR 就绪, Ctrl+C 停止")
            release.wait(2)

        self.assertTrue(self.app._worker(monitor, kind="monitor"))
        self.pump_until(lambda: self.app._status.cget("text") == "监控中")
        self.assertEqual(self.app._status.cget("text"), "监控中")
        self.app.stop_monitor()
        self.assertTrue(self.app.stop_event.is_set())
        self.assertEqual(self.app.b_stop.cget("state"), "disabled")
        release.set()
        self.pump_until(lambda: self.app._task_kind is None)
        self.assertEqual(self.app._status.cget("text"), "已停止")
        self.assertEqual(self.app.b_start.cget("state"), "normal")

    def test_worker_failure_is_visible_and_recovers_controls(self):
        def failing_task():
            raise RuntimeError("simulated audio failure")

        self.app._worker(failing_task, kind="monitor")
        self.pump_until(lambda: self.app._task_kind is None)
        self.assertEqual(self.app._status.cget("text"), "任务异常")
        self.assertEqual(self.app.b_start.cget("state"), "normal")
        self.assertIn("simulated audio failure", self.app.log.get("1.0", "end"))

    def test_dirty_state_and_password_visibility(self):
        self.app.v_user.set("changed")
        self.assertIn("未保存", self.app._save_state.cget("text"))
        self.app.v_user.set(self.app._saved_values[1])
        self.assertEqual(self.app._save_state.cget("text"), "已保存")
        self.assertEqual(self.app.e_pwd.cget("show"), "•")
        self.app._toggle_password()
        self.assertEqual(self.app.e_pwd.cget("show"), "")
        self.app._toggle_password()
        self.assertEqual(self.app.e_pwd.cget("show"), "•")

    def test_theme_switch_updates_history_and_remembers_choice(self):
        original_theme = self.app._appearance
        self.app._append_log("[错误] sample error")
        self.app.v_url.set("https://example.com/unsaved-edit")
        self.app.toggle_theme()
        try:
            target_theme = "light" if original_theme == "dark" else "dark"
            self.assertEqual(ui.ctk.get_appearance_mode().lower(), target_theme)
            self.assertEqual(self.app._appearance, target_theme)
            self.assertEqual(self.app.log.tag_cget("error", "foreground"),
                             self.app._theme_color(ui.RED))
            self.assertIn("sample error", self.app.log.get("1.0", "end"))
            saved = yaml.safe_load(ui.CONFIG.read_text(encoding="utf-8"))
            self.assertEqual(saved["ui"]["appearance"], target_theme)
            self.assertEqual(saved["live_url"], self.base_cfg["live_url"])
            self.assertEqual(self.app.v_url.get(), "https://example.com/unsaved-edit")
            self.assertIn("未保存", self.app._save_state.cget("text"))
        finally:
            self.app.toggle_theme()

    def test_theme_save_failure_keeps_window_usable(self):
        original_theme = self.app._appearance
        with patch.object(Path, "write_text", side_effect=PermissionError("denied")):
            self.app.toggle_theme()
        try:
            self.assertNotEqual(self.app._appearance, original_theme)
            self.assertIn("偏好保存失败", self.app._save_state.cget("text"))
            self.assertEqual(self.app.b_start.cget("state"), "normal")
        finally:
            self.app.toggle_theme()


if __name__ == "__main__":
    unittest.main()
