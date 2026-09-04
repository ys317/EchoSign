"""EchoSign GUI: 图形化配置 + 启停监控 + 日志窗.

  python echosign_app.py            # 图形界面
  EchoSign.exe --sign 2330          # 打包后自动签到入口(内部使用)
"""
from __future__ import annotations

import json
import os
import queue
import sys
import threading
import time
import webbrowser
from contextlib import redirect_stdout
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_ROOT = Path(sys.executable).parent
else:
    APP_ROOT = Path(__file__).resolve().parent
os.chdir(APP_ROOT)

# --sign 模式: 打包后 AutoSigner 自调用, 直接跑浏览器签到
if len(sys.argv) >= 3 and sys.argv[1] == "--sign":
    sys.argv = ["browser_sign.py", sys.argv[2]]
    import browser_sign

    sys.exit(browser_sign.main())

import tkinter as tk  # noqa: E402
from tkinter import scrolledtext, ttk  # noqa: E402

import yaml  # noqa: E402

CONFIG = APP_ROOT / "config.yaml"
SECRETS = APP_ROOT / "secrets_local.json"


def load_cfg() -> dict:
    if CONFIG.exists():
        return yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}
    return yaml.safe_load((APP_ROOT / "config.example.yaml").read_text(encoding="utf-8"))


def load_secrets() -> dict:
    if SECRETS.exists():
        return json.loads(SECRETS.read_text(encoding="utf-8"))
    return {"skl_username": "", "skl_password": ""}


class QueueWriter:
    """print() 重定向到 GUI 日志窗."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s):
        if s and s.strip():
            for line in s.rstrip("\n").splitlines():
                self.q.put(line)

    def flush(self):
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("EchoSign 回声签 - 直播课堂自动签到")
        root.geometry("760x640")

        self.cfg = load_cfg()
        self.secrets = load_secrets()
        self.log_q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()

        self._build_form()
        self._build_buttons()
        self._build_log()
        self._load_fields()
        root.after(200, self._poll_log)

    # ---------- UI ----------
    def _build_form(self):
        f = ttk.Frame(self.root, padding=8)
        f.pack(fill="x")
        self.v_url = tk.StringVar()
        self.v_user = tk.StringVar()
        self.v_pwd = tk.StringVar()
        self.v_hook = tk.StringVar()
        self.v_lat = tk.StringVar()
        self.v_lng = tk.StringVar()
        self.v_auto = tk.BooleanVar(value=True)
        self.v_sem = tk.BooleanVar(value=False)

        def row(i, label, var, width=58, show=""):
            ttk.Label(f, text=label).grid(row=i, column=0, sticky="e", padx=4, pady=3)
            e = ttk.Entry(f, textvariable=var, width=width, show=show)
            e.grid(row=i, column=1, sticky="w", padx=4)
            return e

        row(0, "直播页网址", self.v_url)
        row(1, "学号", self.v_user)
        row(2, "密码", self.v_pwd, show="*")
        row(3, "企微Webhook", self.v_hook)
        row(4, "纬度", self.v_lat, width=20)
        row(5, "经度", self.v_lng, width=20)

        ttk.Label(f, text="签到关键词").grid(row=6, column=0, sticky="ne", padx=4, pady=3)
        self.txt_rules = tk.Text(f, height=4, width=60)
        self.txt_rules.grid(row=6, column=1, sticky="w", padx=4)
        ttk.Label(f, text="(每行一个)").grid(row=6, column=2, sticky="w")

        ttk.Checkbutton(f, text="听到签到码后自动签到", variable=self.v_auto).grid(
            row=7, column=1, sticky="w", pady=2)
        ttk.Checkbutton(f, text="启用语义匹配(启动稍慢)", variable=self.v_sem).grid(
            row=8, column=1, sticky="w")

        for c in (1, 2):
            f.columnconfigure(c, weight=1)

    def _build_buttons(self):
        b = ttk.Frame(self.root, padding=(8, 0))
        b.pack(fill="x")
        self.b_start = ttk.Button(b, text="▶ 启动监控", command=self.start_monitor)
        self.b_stop = ttk.Button(b, text="■ 停止", command=self.stop_monitor, state="disabled")
        ttk.Button(b, text="保存配置", command=self.save_cfg).pack(side="left", padx=3)
        self.b_start.pack(side="left", padx=3)
        self.b_stop.pack(side="left", padx=3)
        ttk.Button(b, text="登录/刷新登录态", command=self.do_login).pack(side="left", padx=3)
        ttk.Button(b, text="测试企微推送", command=self.test_webhook).pack(side="left", padx=3)
        ttk.Button(b, text="打开直播页", command=self.open_url).pack(side="left", padx=3)

    def _build_log(self):
        ttk.Label(self.root, text="运行日志", padding=(8, 4)).pack(anchor="w")
        self.log = scrolledtext.ScrolledText(self.root, height=18, state="disabled",
                                             font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=(0, 8))

    # ---------- 字段 <-> 配置 ----------
    def _load_fields(self):
        self.v_url.set(str(self.cfg.get("live_url", "")))
        self.v_user.set(self.secrets.get("skl_username", ""))
        self.v_pwd.set(self.secrets.get("skl_password", ""))
        self.v_hook.set(str(((self.cfg.get("alert") or {}).get("webhook") or {}).get("url", "")))
        self.v_lat.set(str(self.cfg.get("location", {}).get("lat", 29.219569)))
        self.v_lng.set(str(self.cfg.get("location", {}).get("lng", 119.47955)))
        self.v_auto.set(bool((self.cfg.get("auto_sign") or {}).get("enabled", True)))
        self.v_sem.set(bool(((self.cfg.get("rules") or {}).get("semantic") or {}).get("enabled", False)))
        rules = (self.cfg.get("rules") or {}).get("strong", [])
        self.txt_rules.delete("1.0", "end")
        self.txt_rules.insert("1.0", "\n".join(str(r) for r in rules))

    def save_cfg(self):
        self.cfg["live_url"] = self.v_url.get().strip()
        self.cfg.setdefault("alert", {})["webhook"] = {
            **((self.cfg.get("alert") or {}).get("webhook") or {}),
            "url": self.v_hook.get().strip(),
        }
        self.cfg["location"] = {"lat": float(self.v_lat.get() or 0), "lng": float(self.v_lng.get() or 0)}
        self.cfg.setdefault("auto_sign", {})["enabled"] = bool(self.v_auto.get())
        self.cfg.setdefault("rules", {}).setdefault("semantic", {})["enabled"] = bool(self.v_sem.get())
        strong = [ln.strip() for ln in self.txt_rules.get("1.0", "end").splitlines() if ln.strip()]
        self.cfg["rules"]["strong"] = strong
        CONFIG.write_text(yaml.safe_dump(self.cfg, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")
        self.secrets["skl_username"] = self.v_user.get().strip()
        self.secrets["skl_password"] = self.v_pwd.get()
        SECRETS.write_text(json.dumps(self.secrets, ensure_ascii=False, indent=2),
                           encoding="utf-8")
        self.logline("[i] 配置已保存")

    # ---------- 动作 ----------
    def _worker(self, fn, *a):
        if self.worker and self.worker.is_alive():
            self.logline("[!] 已有任务在运行, 请先停止")
            return

        def run():
            with redirect_stdout(QueueWriter(self.log_q)):
                try:
                    fn(*a)
                except Exception as e:  # noqa: BLE001
                    import traceback

                    print(f"[错误] {e}")
                    traceback.print_exc()

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()

    def start_monitor(self):
        self.save_cfg()
        self.stop_event.clear()
        self.b_start.config(state="disabled")
        self.b_stop.config(state="normal")

        def done_watch():
            while self.worker and self.worker.is_alive():
                time.sleep(0.3)
            self.root.after(0, lambda: (self.b_start.config(state="normal"),
                                        self.b_stop.config(state="disabled")))

        import main as m

        cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
        self._worker(m.cmd_run, cfg, self.stop_event)
        threading.Thread(target=done_watch, daemon=True).start()

    def stop_monitor(self):
        self.stop_event.set()
        self.logline("[i] 正在停止...")

    def do_login(self):
        self.save_cfg()
        import browser_login as bl

        self._worker(bl.main)

    def test_webhook(self):
        self.save_cfg()
        import main as m

        self._worker(m.cmd_webhook_test, m.load_config(str(CONFIG)))

    def open_url(self):
        url = self.v_url.get().strip()
        if url:
            webbrowser.open(url)

    # ---------- 日志 ----------
    def logline(self, s: str):
        self.log_q.put(s)

    def _poll_log(self):
        try:
            while True:
                line = self.log_q.get_nowait()
                self.log.config(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.config(state="disabled")
        except queue.Empty:
            pass
        self.root.after(200, self._poll_log)


def main() -> int:
    root = tk.Tk()
    try:
        from tkinter import font  # noqa: F401
    except Exception:  # noqa: BLE001
        pass
    App(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
