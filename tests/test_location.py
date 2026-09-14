"""Location acquisition contracts; all requests are mocked and collect no location."""
from __future__ import annotations

import json
import subprocess
import unittest
from unittest.mock import patch

from echosign import location


class LocationTests(unittest.TestCase):
    def setUp(self):
        self.platform = patch.object(location.sys, "platform", "win32")
        self.platform.start()
        self.addCleanup(self.platform.stop)
        self.hidden = patch.object(location, "hidden_subprocess_options",
                                   return_value={"creationflags": 0x08000000})
        self.hidden.start()
        self.addCleanup(self.hidden.stop)
        self.run_patch = patch.object(location.subprocess, "run")
        self.run = self.run_patch.start()
        self.addCleanup(self.run_patch.stop)

    def respond(self, **response):
        self.run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(response), stderr="")

    def test_correct_default_and_actual_system_coordinates(self):
        self.assertEqual((location.DEFAULT_LAT, location.DEFAULT_LNG),
                         (30.314732, 120.343727))
        self.respond(status="ok", lat=31.2, lng=121.5, accuracy_m=35.5)
        self.assertEqual(location.get_current_location(), location.Location(31.2, 121.5, 35.5))

    def test_background_command_is_hidden_with_a_total_timeout(self):
        self.respond(status="ok", lat=30, lng=120)
        location.get_current_location(timeout_s=2.5)
        args, options = self.run.call_args
        command = args[0]
        self.assertTrue(command[0].endswith("powershell.exe"))
        self.assertIn("-NoProfile", command)
        self.assertIn("-NonInteractive", command)
        self.assertEqual(command[command.index("-WindowStyle") + 1], "Hidden")
        self.assertEqual(options["creationflags"], 0x08000000)
        self.assertEqual(options["timeout"], 2.5)
        self.assertEqual(options["stdin"], subprocess.DEVNULL)
        self.assertTrue(options["capture_output"])
        self.assertFalse(options.get("shell", False))

    def test_windows_failures_are_actionable_and_never_use_defaults(self):
        for status, message in (("denied", "拒绝了定位权限"),
                                ("disabled", "定位服务已关闭"),
                                ("unavailable", "没有可用的位置数据"),
                                ("timeout", "超时"),
                                ("failed", "无法调用 Windows"),
                                ("unexpected", "无法调用 Windows"),
                                ({"invalid": "status"}, "无法调用 Windows")):
            with self.subTest(status=status):
                self.respond(status=status)
                with self.assertRaisesRegex(location.LocationError, message):
                    location.get_current_location()

    def test_hung_system_helper_times_out(self):
        self.run.side_effect = subprocess.TimeoutExpired("powershell", 0.1)
        with self.assertRaisesRegex(location.LocationError, "超时"):
            location.get_current_location(0.1)
        self.assertEqual(self.run.call_args.kwargs["timeout"], 0.1)

    def test_missing_or_unlaunchable_powershell_is_reported(self):
        for error, message in ((FileNotFoundError(), "未找到 Windows PowerShell"),
                               (PermissionError(), "无法调用 Windows")):
            with self.subTest(error=type(error).__name__):
                self.run.side_effect = error
                with self.assertRaisesRegex(location.LocationError, message):
                    location.get_current_location()

    def test_failed_helper_does_not_parse_untrusted_output(self):
        self.run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1,
            stdout='{"status":"ok","lat":30,"lng":120}', stderr="error")
        with self.assertRaisesRegex(location.LocationError, "无法调用 Windows"):
            location.get_current_location()

    def test_malformed_results_are_reported(self):
        for output in ("", "invalid JSON", "[]", "null", "42"):
            with self.subTest(output=output):
                self.run.return_value = subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=output, stderr="")
                with self.assertRaisesRegex(location.LocationError, "无法解析"):
                    location.get_current_location()

    def test_invalid_coordinates_are_rejected(self):
        for lat, lng in ((None, 120), (30, None), (True, 120), (30, False),
                         ("30", 120), (30, "120"), (float("nan"), 120),
                         (30, float("inf")), (91, 120), (-91, 120),
                         (30, 181), (30, -181), (10 ** 400, 120)):
            with self.subTest(lat=lat, lng=lng):
                self.respond(status="ok", lat=lat, lng=lng)
                with self.assertRaisesRegex(location.LocationError, "无效经纬度"):
                    location.get_current_location()

    def test_coordinate_bounds_and_zero_are_valid(self):
        for lat, lng in ((90, 180), (-90, -180), (0, 0)):
            with self.subTest(lat=lat, lng=lng):
                self.respond(status="ok", lat=lat, lng=lng)
                self.assertEqual(location.get_current_location(), location.Location(lat, lng))

    def test_unknown_accuracy_does_not_invent_precision(self):
        for accuracy in (None, -1, float("nan"), float("inf"), True, "5"):
            with self.subTest(accuracy=accuracy):
                self.respond(status="ok", lat=30, lng=120, accuracy_m=accuracy)
                self.assertIsNone(location.get_current_location().accuracy_m)

    def test_utf8_bom_from_system_output_is_accepted(self):
        self.run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout='\ufeff{"status":"ok","lat":30,"lng":120}\r\n', stderr="")
        self.assertEqual(location.get_current_location(), location.Location(30, 120))

    def test_invalid_timeout_never_starts_helper(self):
        for timeout in (0, -1, float("nan"), float("inf"), None, "invalid", True):
            with self.subTest(timeout=timeout):
                with self.assertRaisesRegex(location.LocationError, "大于 0"):
                    location.get_current_location(timeout)
        self.run.assert_not_called()

    def test_other_platforms_use_manual_coordinates(self):
        with patch.object(location.sys, "platform", "linux"):
            with self.assertRaisesRegex(location.LocationError, "手动填写"):
                location.get_current_location()
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
