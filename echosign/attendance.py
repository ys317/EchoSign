"""Structured attendance results and isolated browser-task dispatch."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from contextlib import ExitStack
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

from echosign.processes import hidden_subprocess_options
from echosign.runtime import application_root

ROOT = application_root()


def write_json(path: Path, data: dict) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)


def browser_command(*args: str) -> list[str]:
    prefix = [sys.executable] if getattr(sys, "frozen", False) else [
        sys.executable, "-X", "utf8", "-m", "echosign"]
    return [*prefix, *args]


@dataclass(frozen=True)
class SignResult:
    status: str
    sign_code: str
    message: str

    @property
    def exit_code(self) -> int:
        return {"success": 0, "failure": 1, "unknown": 2}[self.status]

    def write(self, path: Path) -> None:
        write_json(path, asdict(self))

    @classmethod
    def read(cls, path: Path, sign_code: str) -> SignResult:
        data = json.loads(path.read_text(encoding="utf-8"))
        if (not isinstance(data, dict)
                or data.get("status") not in ("success", "failure", "unknown")
                or data.get("sign_code") != sign_code
                or not isinstance(data.get("message"), str)):
            raise ValueError("签到结果格式无效或签到码不匹配")
        return cls(data["status"], sign_code, data["message"][:240])


def classify_response(sign_code: str, http_status: int, payload: object) -> SignResult:
    """Interpret the business code from the matched HDU sign-in endpoint only.

    HTTP 200, captcha/login responses and arbitrary log text do not prove a sign-in.
    Missing or unrecognized response schemas remain unknown.
    """
    if not 200 <= http_status < 300:
        return SignResult("failure", sign_code, f"签到接口返回 HTTP {http_status}")
    if not isinstance(payload, dict):
        return SignResult("unknown", sign_code, "签到接口未返回可识别的 JSON 结果")
    message = payload.get("msg") or payload.get("message")
    message = " ".join(message.split())[:240] if isinstance(message, str) else ""
    business_code = payload.get("code")
    if type(business_code) not in (int, str):
        return SignResult("unknown", sign_code, "签到响应缺少有效的业务状态码")
    if business_code in (200, "200") and payload.get("success") is not False:
        return SignResult("success", sign_code, message or "签到接口已确认成功")
    return SignResult("failure", sign_code, message or f"签到接口返回业务状态 {business_code}")


class AutoSigner:
    """One worker per monitoring session; only the latest waiting code is kept."""

    def __init__(self, notify, timeout_s: int = 180, stop: threading.Event | None = None,
                 *, prewarm_browser: bool = False):
        self.notify = notify          # callable(reason, text) -> WeChat/console push
        self.timeout_s = timeout_s
        self._condition = threading.Condition()
        self._stop = stop if stop is not None else threading.Event()
        self._pending: tuple[str, float] | None = None
        self._closing = False
        self._worker: threading.Thread | None = None
        self._prewarm_browser = prewarm_browser
        self._prepare_requested = False
        self._prepare_failed = False
        self._session: _BrowserSession | None = None
        self._detected_at: float | None = None

    def _start_worker(self) -> None:
        if self._worker is None:
            self._worker = threading.Thread(target=self._run, name="EchoSign attendance", daemon=False)
            try:
                self._worker.start()
            except Exception:
                self._worker = None
                self._pending = None
                self._prepare_requested = False
                raise

    def prepare(self) -> bool:
        """Warm the sign-in page without providing or submitting any code."""
        with self._condition:
            if (not self._prewarm_browser or self._closing or self._stop.is_set()
                    or self._prepare_failed):
                return False
            if self._session is None:
                self._prepare_requested = True
                self._start_worker()
                self._condition.notify_all()
        return True

    def submit(self, code: str) -> bool:
        with self._condition:
            if self._closing or self._stop.is_set():
                return False
            self._pending = (code, time.time())
            self._start_worker()
            self._condition.notify_all()
        return True

    def close(self, *, cancel: bool = True) -> None:
        """Reject further work and join the worker; cancellation discards the queue.

        Finite WAV replay may drain normally with cancel=False. A shared stop
        signal or Ctrl+C still cancels the running child during that wait.
        """
        with self._condition:
            self._closing = True
            if cancel:
                self._stop.set()
                self._pending = None
            self._condition.notify_all()
            worker = self._worker
        if worker is not None and worker is not threading.current_thread():
            try:
                worker.join()
            except BaseException:
                self._stop.set()
                with self._condition:
                    self._pending = None
                    self._condition.notify_all()
                worker.join()
                raise

    def _run(self) -> None:
        try:
            while True:
                with self._condition:
                    while (self._pending is None and not self._prepare_requested
                           and not self._closing and not self._stop.is_set()):
                        self._condition.wait(timeout=0.1)
                    if self._stop.is_set() or (self._closing and self._pending is None):
                        return
                    pending, self._pending = self._pending, None
                    self._prepare_requested = False
                if self._prewarm_browser and self._session is None and not self._prepare_failed:
                    self._prepare_browser()
                if pending is None:
                    continue
                code, self._detected_at = pending
                try:
                    self._sign_one(code)
                except Exception as exc:
                    print(f"[warn] 签到任务异常：{exc}")
        finally:
            try:
                if self._session is not None:
                    self._session.close()
            finally:
                self._session = None
                with self._condition:
                    self._pending = None
                    self._closing = True

    def _prepare_browser(self) -> None:
        session = _BrowserSession(self._stop, self.timeout_s)
        self._session = session
        try:
            session.open()
            print("[autosign] 签到页已准备好，等待确认签到码")
        except Exception as exc:
            session.close()
            self._session = None
            self._prepare_failed = True
            if not self._stop.is_set():
                print(f"[autosign] 页面预备未完成，确认码后再打开：{exc}")

    @staticmethod
    def _terminate_child(proc) -> None:
        """Stop this child's process tree, including its Playwright browser."""
        if proc.poll() is not None:
            return
        if sys.platform == "win32":
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=5,
                    **hidden_subprocess_options())
            except (OSError, subprocess.TimeoutExpired) as exc:
                print(f"[warn] 浏览器子进程清理失败：{exc}")
        if proc.poll() is None:
            proc.kill()
        proc.wait()

    def _run_child(self, command: list[str]):
        if self._stop.is_set():
            return None
        # Files avoid pipe-reader threads blocking shutdown if a browser inherits
        # a child's stdout/stderr. Result interpretation still uses result.json.
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            with subprocess.Popen(
                    command, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, cwd=str(ROOT),
                    **hidden_subprocess_options()) as proc:
                deadline = time.monotonic() + self.timeout_s
                try:
                    while proc.poll() is None:
                        if self._stop.is_set():
                            return None
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(command, self.timeout_s)
                        self._stop.wait(min(0.1, remaining))
                finally:
                    self._terminate_child(proc)
                stdout.seek(0)
                stderr.seek(0)
                return subprocess.CompletedProcess(
                    command, proc.returncode,
                    stdout.read().decode("utf-8", errors="replace"),
                    stderr.read().decode("utf-8", errors="replace"))

    def _sign_one(self, code: str) -> None:
        if self._stop.is_set():
            return
        print(f"[autosign] 听到签到码 {code}, 启动自动签到...")
        if self._session is not None and not self._session.is_alive():
            self._session.close()
            self._session = None
        if self._session is not None:
            try:
                result = self._session.submit(code, self._detected_at or time.time())
            except Exception as exc:
                # A request may already have reached the server. Never retry it
                # in a new browser just because the worker/result disappeared.
                result = SignResult("unknown", code, f"无法确认签到结果：{exc}")
                self._session.close()
                self._session = None
                self._prepare_failed = True
            self._notify_result(result)
            return
        cmd = browser_command("--sign", code)
        result = SignResult("unknown", code, "浏览器未返回明确的签到结果，请到平台核对")
        try:
            # Windowed executables may not expose stdout. Use a private result file
            # for both frozen and source runs; logs never determine success.
            with tempfile.TemporaryDirectory(prefix="echosign-result-") as temporary:
                result_path = Path(temporary) / "result.json"
                proc = self._run_child([*cmd, "--result-file", str(result_path)])
                if proc is None:
                    print("[autosign] 浏览器任务已停止；已提交的签到请到平台核对")
                    return
                out = (proc.stdout or "") + (proc.stderr or "")
                print("\n".join(line for line in out.splitlines() if line.strip())[-1200:])
                if result_path.exists():
                    result = SignResult.read(result_path, code)
                if result.status == "success" and proc.returncode != 0:
                    result = SignResult("unknown", code, "浏览器异常退出，签到结果需到平台核对")
        except subprocess.TimeoutExpired:
            result = SignResult("unknown", code, "浏览器处理超时，签到结果需到平台核对")
        except (OSError, ValueError) as exc:
            result = SignResult("unknown", code, f"无法确认签到结果：{exc}")

        self._notify_result(result)

    def _notify_result(self, result: SignResult) -> None:
        if self._stop.is_set():
            return
        code = result.sign_code
        if result.status == "success":
            self.notify(f"自动签到成功, 码 {code}", f"✅ 已自动完成签到 (码 {code})")
        elif result.status == "failure":
            self.notify(f"自动签到失败, 码 {code}", f"❌ 签到失败 (码 {code})\n{result.message}")
        else:
            self.notify(f"自动签到结果未知, 码 {code}", f"⚠️ 请人工确认: {result.message}")


class _BrowserSession:
    """One isolated browser per monitor, with atomic request/result files.

    File exchange also works with windowed frozen executables, which may not
    have stdin/stdout. The parent remains able to stop the entire child tree.
    """

    def __init__(self, stop: threading.Event, timeout_s: float):
        self.stop = stop
        self.timeout_s = timeout_s
        self.resources = ExitStack()
        self.directory: Path | None = None
        self.proc = None
        self.sequence = 0
        self.in_request = False

    def is_alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def _wait(self, path: Path) -> None:
        deadline = time.monotonic() + self.timeout_s
        while not path.exists():
            if self.stop.is_set():
                raise InterruptedError("监控已停止")
            if self.proc.poll() is not None:
                raise RuntimeError("浏览器进程已退出")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired("prepared browser", self.timeout_s)
            self.stop.wait(min(0.05, remaining))
        if self.stop.is_set():
            raise InterruptedError("监控已停止")

    def open(self) -> None:
        if self.stop.is_set():
            raise InterruptedError("监控已停止")
        self.directory = Path(self.resources.enter_context(
            tempfile.TemporaryDirectory(prefix="echosign-browser-")))
        log = self.resources.enter_context(tempfile.TemporaryFile())
        command = browser_command("--sign-worker", "--exchange-dir", str(self.directory))
        self.proc = self.resources.enter_context(subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, cwd=str(ROOT),
            **hidden_subprocess_options()))
        ready = self.directory / "ready.json"
        self._wait(ready)
        result = json.loads(ready.read_text(encoding="utf-8"))
        if result.get("status") != "ready":
            raise RuntimeError(result.get("message", "签到页未就绪"))

    def submit(self, code: str, detected_at: float) -> SignResult:
        if self.stop.is_set():
            raise InterruptedError("监控已停止")
        self.sequence += 1
        request = self.sequence
        self.in_request = True
        # Never replace a file the Windows child may still have open for reading.
        # Immutable request names also prevent reprocessing an earlier code.
        write_json(self.directory / f"request-{request}.json", {
            "id": request, "code": code, "detected_at": detected_at})
        result_path = self.directory / f"result-{request}.json"
        self._wait(result_path)
        result = SignResult.read(result_path, code)
        self.in_request = False
        if result.status == "success" and self.proc.poll() not in (None, 0):
            return SignResult("unknown", code, "浏览器异常退出，签到结果需到平台核对")
        timing = self.directory / f"timing-{request}.json"
        try:
            if timing.exists():
                values = json.loads(timing.read_text(encoding="utf-8"))
                if "page_ready" in values and "submit" in values:
                    ready_s = max(0.0, values["page_ready"] - detected_at)
                    submit_s = max(0.0, values["submit"] - detected_at)
                    print(f"[autosign] 确认码→页面就绪 {ready_s:.2f}s，确认码→点击签到 {submit_s:.2f}s")
        except (OSError, ValueError, TypeError):
            print("[warn] 无法读取操作耗时；签到结果已单独确认")
        return result

    def close(self) -> None:
        try:
            if self.proc is not None and self.proc.poll() is None:
                if self.in_request:
                    AutoSigner._terminate_child(self.proc)
                else:
                    try:
                        if self.directory is not None:
                            write_json(self.directory / "stop.json", {})
                        self.proc.wait(timeout=1.5)
                    except (OSError, subprocess.TimeoutExpired):
                        AutoSigner._terminate_child(self.proc)
        finally:
            self.resources.close()
            self.proc = None


def make_auto_signer(cfg: dict, alerter, stop: threading.Event | None = None):
    if not (cfg.get("auto_sign") or {}).get("enabled"):
        return None

    def notify(reason: str, text: str):
        print(f"!!!! {reason} !!!!")
        alerter.notify(text, "code", reason)

    options = cfg.get("auto_sign") or {}
    return AutoSigner(notify, int(options.get("timeout_seconds", 180)), stop,
                      prewarm_browser=bool(options.get("prewarm_browser", True)))
