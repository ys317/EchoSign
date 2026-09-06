"""Structured attendance results and isolated browser-task dispatch."""
from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading

from echosign.runtime import application_root

ROOT = application_root()


@dataclass(frozen=True)
class SignResult:
    status: str
    sign_code: str
    message: str

    @property
    def exit_code(self) -> int:
        return {"success": 0, "failure": 1, "unknown": 2}[self.status]

    def write(self, path: Path) -> None:
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_text(json.dumps(asdict(self), ensure_ascii=False), encoding="utf-8")
        temporary.replace(path)

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
    """Single-flight: only one browser sign-in at a time; the latest code wins."""

    def __init__(self, notify, timeout_s: int = 180):
        self.notify = notify          # callable(reason, text) -> WeChat/console push
        self.timeout_s = timeout_s
        self._lock = threading.Lock()
        self._pending: list[str] = []
        self._busy = False

    def submit(self, code: str) -> None:
        self._pending.append(code)
        if self._busy:
            print(f"[autosign] 忙碌中, {code} 已排队")
            return
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self) -> None:
        self._busy = True
        try:
            while self._pending:
                code = self._pending.pop(-1)  # latest wins
                self._pending.clear()
                self._sign_one(code)
        finally:
            self._busy = False

    def _sign_one(self, code: str) -> None:
        print(f"[autosign] 听到签到码 {code}, 启动自动签到...")
        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--sign", code]  # 打包后自调用
        else:
            cmd = [sys.executable, "-X", "utf8", "-m", "echosign", "--sign", code]
        result = SignResult("unknown", code, "浏览器未返回明确的签到结果，请到平台核对")
        try:
            # Windowed executables may not expose stdout. Use a private result file
            # for both frozen and source runs; logs never determine success.
            with tempfile.TemporaryDirectory(prefix="echosign-result-") as temporary:
                result_path = Path(temporary) / "result.json"
                proc = subprocess.run(
                    [*cmd, "--result-file", str(result_path)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace",
                    timeout=self.timeout_s, cwd=str(ROOT),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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

        if result.status == "success":
            self.notify(f"自动签到成功, 码 {code}", f"✅ 已自动完成签到 (码 {code})")
        elif result.status == "failure":
            self.notify(f"自动签到失败, 码 {code}", f"❌ 签到失败 (码 {code})\n{result.message}")
        else:
            self.notify(f"自动签到结果未知, 码 {code}", f"⚠️ 请人工确认: {result.message}")


def make_auto_signer(cfg: dict, alerter):
    if not (cfg.get("auto_sign") or {}).get("enabled"):
        return None

    def notify(reason: str, text: str):
        print(f"!!!! {reason} !!!!")
        alerter.notify(text, "code", reason)

    return AutoSigner(notify, int((cfg.get("auto_sign") or {}).get("timeout_seconds", 180)))
