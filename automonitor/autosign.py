"""Auto sign-in dispatcher: run browser_sign.py in a subprocess when a code is heard."""
from __future__ import annotations

import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"


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
        try:
            proc = subprocess.run(
                [str(PY), "-X", "utf8", str(ROOT / "browser_sign.py"), code],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=self.timeout_s, cwd=str(ROOT))
            out = (proc.stdout or "") + (proc.stderr or "")
        except Exception as e:  # noqa: BLE001
            out = f"启动失败: {e}"

        tail = "\n".join([ln for ln in out.splitlines() if ln.strip()][-6:])
        print(tail)

        if "成功" in out or '"code":200' in out:
            self.notify(f"自动签到成功, 码 {code}", f"✅ 已自动完成签到 (码 {code})")
        elif "不存在" in out or "过期" in out or "错误" in out:
            self.notify(f"自动签到失败, 码 {code}", f"❌ 码无效/过期: {code}\n{tail[-200:]}")
        else:
            self.notify(f"自动签到结果未知, 码 {code}", f"⚠️ 请人工确认: {tail[-300:]}")


def make_auto_signer(cfg: dict, alerter):
    if not (cfg.get("auto_sign") or {}).get("enabled"):
        return None

    def notify(reason: str, text: str):
        print(f"!!!! {reason} !!!!")
        alerter.notify(text, "code", reason)

    return AutoSigner(notify, int((cfg.get("auto_sign") or {}).get("timeout_seconds", 180)))
