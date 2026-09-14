"""Attendance scheduling and cancellation without opening a real browser."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

from echosign.attendance import AutoSigner


class SchedulerTests(unittest.TestCase):
    def test_submissions_before_worker_start_create_only_one_worker(self):
        gate = threading.Event()
        thread_type = threading.Thread
        signer = AutoSigner(lambda *_: None)
        self.addCleanup(signer.close)
        self.addCleanup(gate.set)

        def delayed_thread(*, target, **kwargs):
            def delayed():
                gate.wait(3)
                target()
            return thread_type(target=delayed, **kwargs)

        with patch("echosign.attendance.threading.Thread", side_effect=delayed_thread) as factory, \
                patch.object(signer, "_sign_one") as sign:
            self.assertTrue(signer.submit("1234"))
            self.assertTrue(signer.submit("5678"))
            self.assertTrue(signer.submit("9012"))
            self.assertEqual(factory.call_count, 1)
            gate.set()
            signer.close(cancel=False)
        sign.assert_called_once_with("9012")

    def test_concurrent_submissions_are_serial_and_only_latest_waiting_code_runs(self):
        entered, release = threading.Event(), threading.Event()
        signer = AutoSigner(lambda *_: None)
        self.addCleanup(signer.close)
        self.addCleanup(release.set)
        lock = threading.Lock()
        calls = []
        active = peak = 0

        def sign(code):
            nonlocal active, peak
            with lock:
                calls.append(code)
                active += 1
                peak = max(peak, active)
            if code == "1000":
                entered.set()
                release.wait(3)
            with lock:
                active -= 1

        with patch.object(signer, "_sign_one", side_effect=sign):
            signer.submit("1000")
            self.assertTrue(entered.wait(2))
            with ThreadPoolExecutor(max_workers=12) as callers:
                self.assertTrue(all(callers.map(signer.submit, (str(n) for n in range(2000, 2060)))))
            signer.submit("9999")
            self.assertEqual(calls, ["1000"])
            release.set()
            signer.close(cancel=False)
        self.assertEqual(calls, ["1000", "9999"])
        self.assertEqual(peak, 1)
        self.assertFalse(signer.submit("3333"))

    def test_shared_stop_discards_pending_codes_and_rejects_new_work(self):
        stop, entered = threading.Event(), threading.Event()
        signer = AutoSigner(lambda *_: None, stop=stop)
        self.addCleanup(signer.close)
        self.addCleanup(stop.set)
        calls = []

        def sign(code):
            calls.append(code)
            entered.set()
            stop.wait(3)

        with patch.object(signer, "_sign_one", side_effect=sign):
            signer.submit("1234")
            self.assertTrue(entered.wait(2))
            signer.submit("5678")
            stop.set()
            signer.close()
        self.assertEqual(calls, ["1234"])
        self.assertFalse(signer.submit("9012"))

    def test_repeated_sessions_leave_no_attendance_workers(self):
        before = set(threading.enumerate())
        for _ in range(8):
            done = threading.Event()
            signer = AutoSigner(lambda *_: None)
            try:
                with patch.object(signer, "_sign_one", side_effect=lambda _: done.set()):
                    signer.submit("1234")
                    self.assertTrue(done.wait(2))
                    signer.close()
            finally:
                signer.close()
        leftovers = [thread for thread in set(threading.enumerate()) - before
                     if thread.name == "EchoSign attendance"]
        self.assertEqual(leftovers, [])

    def test_task_exception_does_not_strand_later_work(self):
        first = threading.Event()
        signer = AutoSigner(lambda *_: None)
        self.addCleanup(signer.close)
        calls = []

        def sign(code):
            calls.append(code)
            if code == "1234":
                first.set()
                raise RuntimeError("simulated failure")

        with patch.object(signer, "_sign_one", side_effect=sign), redirect_stdout(StringIO()):
            signer.submit("1234")
            self.assertTrue(first.wait(2))
            signer.submit("5678")
            signer.close(cancel=False)
        self.assertEqual(calls, ["1234", "5678"])


class ChildCancellationTests(unittest.TestCase):
    @staticmethod
    def child(entered):
        child = MagicMock()
        child.returncode = None
        child.__enter__.return_value = child
        child.poll.side_effect = lambda: (entered.set() or child.returncode)
        child.kill.side_effect = lambda: setattr(child, "returncode", -9)
        return child

    def test_stop_terminates_running_child_without_starting_pending_code(self):
        stop, entered = threading.Event(), threading.Event()
        child = self.child(entered)
        notifications = []
        signer = AutoSigner(lambda *args: notifications.append(args), stop=stop)
        self.addCleanup(signer.close)
        self.addCleanup(stop.set)
        with patch("echosign.attendance.subprocess.Popen", return_value=child) as launch, \
                patch.object(signer, "_terminate_child", side_effect=lambda process: process.kill()) as terminate, \
                redirect_stdout(StringIO()):
            signer.submit("1234")
            self.assertTrue(entered.wait(2))
            signer.submit("5678")
            stop.set()
            signer.close()
        self.assertEqual(launch.call_count, 1)
        terminate.assert_called_once_with(child)
        self.assertEqual(child.returncode, -9)
        self.assertEqual(notifications, [])

    def test_deadline_terminates_child_and_reports_unknown_without_retry(self):
        child = self.child(threading.Event())
        notifications = []
        signer = AutoSigner(lambda *args: notifications.append(args), timeout_s=0.01)
        with patch("echosign.attendance.subprocess.Popen", return_value=child) as launch, \
                patch.object(signer, "_terminate_child", side_effect=lambda process: process.kill()) as terminate, \
                redirect_stdout(StringIO()):
            signer._sign_one("1234")
        self.assertEqual(launch.call_count, 1)
        terminate.assert_called_once_with(child)
        self.assertEqual(len(notifications), 1)
        self.assertIn("结果未知", notifications[0][0])

    def test_pre_cancelled_session_never_launches_a_child(self):
        stop = threading.Event()
        stop.set()
        signer = AutoSigner(lambda *_: None, stop=stop)
        with patch("echosign.attendance.subprocess.Popen") as launch:
            self.assertFalse(signer.submit("1234"))
            signer._sign_one("1234")
            signer.close()
        launch.assert_not_called()

    def test_real_child_output_and_exit_code_are_preserved(self):
        signer = AutoSigner(lambda *_: None, timeout_s=5)
        result = signer._run_child([
            sys.executable, "-X", "utf8", "-c",
            "import sys; print('课堂测试'); print('sample error', file=sys.stderr); sys.exit(7)",
        ])
        self.assertEqual(result.returncode, 7)
        self.assertEqual(result.stdout.strip(), "课堂测试")
        self.assertEqual(result.stderr.strip(), "sample error")

    @unittest.skipUnless(sys.platform == "win32", "Windows process-tree cleanup")
    def test_cancel_reaps_child_tree_and_preserves_an_unrelated_process(self):
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        kernel.TerminateProcess.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        stop = threading.Event()
        signer = AutoSigner(lambda *_: None, timeout_s=10, stop=stop)
        results, errors = [], []
        descendant_handle = None
        runner = None
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        sleeper = [sys.executable, "-c", "import time; time.sleep(15)"]
        control = subprocess.Popen(sleeper, creationflags=flags,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        with tempfile.TemporaryDirectory() as directory:
            marker = Path(directory) / "descendant.pid"
            script = (
                "import subprocess, sys, time\n"
                "from pathlib import Path\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(15)'], "
                "creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))\n"
                "Path(sys.argv[1]).write_text(str(child.pid))\n"
                "time.sleep(15)\n"
            )

            def run():
                try:
                    results.append(signer._run_child([sys.executable, "-c", script, str(marker)]))
                except Exception as exc:
                    errors.append(exc)

            try:
                runner = threading.Thread(target=run, daemon=True)
                runner.start()
                deadline = time.monotonic() + 5
                while time.monotonic() < deadline:
                    if marker.exists() and marker.read_text().strip():
                        break
                    stop.wait(0.01)
                self.assertTrue(marker.exists(), f"Child did not start: {errors}")
                # Hold the actual child handle, so PID reuse cannot affect cleanup.
                descendant_handle = kernel.OpenProcess(0x00100001, False, int(marker.read_text()))
                self.assertTrue(descendant_handle, ctypes.get_last_error())
                stop.set()
                runner.join(timeout=8)
                self.assertFalse(runner.is_alive())
                self.assertEqual(errors, [])
                self.assertEqual(results, [None])
                self.assertEqual(kernel.WaitForSingleObject(descendant_handle, 2000), 0)
                self.assertIsNone(control.poll())
            finally:
                stop.set()
                if runner is not None:
                    runner.join(timeout=8)
                if descendant_handle:
                    if kernel.WaitForSingleObject(descendant_handle, 0) == 258:
                        kernel.TerminateProcess(descendant_handle, 1)
                    kernel.CloseHandle(descendant_handle)
                control.kill()
                control.wait()


if __name__ == "__main__":
    unittest.main()
