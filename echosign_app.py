"""EchoSign GUI (CustomTkinter): 图形化配置 + 启停监控 + 日志窗.

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

import customtkinter as ctk  # noqa: E402
import yaml  # noqa: E402

CONFIG = APP_ROOT / "config.yaml"
SECRETS = APP_ROOT / "secrets_local.json"

ACCENT = "#3b82f6"
GREEN = "#22c55e"
RED = "#ef4444"
CARD = "#1e1e2e"


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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.title("EchoSign")
        self.geometry("820x700")
        self.minsize(760, 620)

        self.cfg = load_cfg()
        self.secrets = load_secrets()
        self.log_q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()

        self._build_header()
        self._build_form()
        self._build_buttons()
        self._build_log()
        self._load_fields()
        self.after(200, self._poll_log)

    # ---------- UI ----------
    def _build_header(self):
        h = ctk.CTkFrame(self, fg_color="transparent")
        h.pack(fill="x", padx=16, pady=(12, 4))
        ctk.CTkLabel(h, text="EchoSign", font=("微软雅黑", 24, "bold")).pack(side="left")
        ctk.CTkLabel(h, text="直播课堂自动签到", font=("微软雅黑", 13),
                     text_color="#9ca3af").pack(side="left", padx=(10, 0), pady=(6, 0))
        self.status_dot = ctk.CTkLabel(h, text="● 未运行", font=("微软雅黑", 13),
                                       text_color="#6b7280")
        self.status_dot.pack(side="right", padx=6)

    def _card(self, title: str) -> ctk.CTkFrame:
        ctk.CTkLabel(self, text=title, font=("微软雅黑", 13, "bold"),
                     text_color="#9ca3af").pack(anchor="w", padx=20, pady=(10, 2))
        card = ctk.CTkFrame(self, fg_color=CARD, corner_radius=12)
        card.pack(fill="x", padx=16)
        return card

    def _build_form(self):
        f = self._card("配置")
        f.grid_columnconfigure(1, weight=1)
        self.v_url = ctk.StringVar()
        self.v_user = ctk.StringVar()
        self.v_pwd = ctk.StringVar()
        self.v_hook = ctk.StringVar()
        self.v_lat = ctk.StringVar()
        self.v_lng = ctk.StringVar()
        self.v_auto = ctk.BooleanVar(value=True)
        self.v_sem = ctk.BooleanVar(value=False)

        def row(i, label, var, show="", wide=True):
            ctk.CTkLabel(f, text=label, font=("微软雅黑", 12), text_color="#c7c7d1",
                         width=90, anchor="e").grid(row=i, column=0, padx=(12, 6), pady=5)
            e = ctk.CTkEntry(f, textvariable=var, show=show, height=32,
                             font=("微软雅黑", 12), fg_color="#16161f",
                             border_color="#33334a")
            e.grid(row=i, column=1, sticky="ew" if wide else "w",
                   padx=(0, 12) if wide else (0, 0), pady=5)

        row(0, "直播页网址", self.v_url)
        row(1, "学号", self.v_user, wide=False)
        row(2, "密码", self.v_pwd, show="•", wide=False)
        row(3, "企微Webhook", self.v_hook)
        row(4, "纬度 / 经度", None)
        e_lat = ctk.CTkEntry(f, textvariable=self.v_lat, width=120, height=32,
                             fg_color="#16161f", border_color="#33334a")
        e_lat.grid(row=4, column=1, sticky="w", padx=(0, 6), pady=5)
        e_lng = ctk.CTkEntry(f, textvariable=self.v_lng, width=120, height=32,
                             fg_color="#16161f", border_color="#33334a")
        e_lng.grid(row=4, column=1, sticky="w", padx=(140, 0), pady=5)

        ctk.CTkLabel(f, text="签到关键词", font=("微软雅黑", 12), text_color="#c7c7d1",
                     width=90, anchor="e").grid(row=5, column=0, padx=(12, 6), pady=5)
        self.txt_rules = ctk.CTkTextbox(f, height=76, font=("微软雅黑", 12),
                                        fg_color="#16161f", border_color="#33334a",
                                        border_width=1)
        self.txt_rules.grid(row=5, column=1, sticky="ew", padx=(0, 12), pady=5)
        ctk.CTkLabel(f, text="每行一个", font=("微软雅黑", 11),
                     text_color="#6b7280").grid(row=5, column=2, padx=(4, 12))

        sw = ctk.CTkFrame(f, fg_color="transparent")
        sw.grid(row=6, column=0, columnspan=3, sticky="w", padx=12, pady=(2, 10))
        ctk.CTkSwitch(sw, text="听到签到码后自动签到", variable=self.v_auto,
                      progress_color=ACCENT, font=("微软雅黑", 12)).pack(side="left", padx=(0, 24))
        ctk.CTkSwitch(sw, text="语义匹配(启动稍慢)", variable=self.v_sem,
                      progress_color=ACCENT, font=("微软雅黑", 12)).pack(side="left")

    def _build_buttons(self):
        b = ctk.CTkFrame(self, fg_color="transparent")
        b.pack(fill="x", padx=20, pady=8)
        self.b_start = ctk.CTkButton(b, text="▶  启动监控", command=self.start_monitor,
                                     fg_color=GREEN, hover_color="#16a34a",
                                     font=("微软雅黑", 13, "bold"), height=36, width=130,
                                     corner_radius=8)
        self.b_start.pack(side="left", padx=(0, 8))
        self.b_stop = ctk.CTkButton(b, text="■  停止", command=self.stop_monitor,
                                    fg_color=RED, hover_color="#dc2626",
                                    font=("微软雅黑", 13, "bold"), height=36, width=96,
                                    corner_radius=8, state="disabled")
        self.b_stop.pack(side="left", padx=(0, 8))
        ctk.CTkButton(b, text="保存配置", command=self.save_cfg, height=36,
                      fg_color="#374151", hover_color="#4b5563",
                      font=("微软雅黑", 12), corner_radius=8).pack(side="left", padx=4)
        ctk.CTkButton(b, text="登录/刷新登录态", command=self.do_login, height=36,
                      fg_color="#374151", hover_color="#4b5563",
                      font=("微软雅黑", 12), corner_radius=8).pack(side="left", padx=4)
        ctk.CTkButton(b, text="测试企微推送", command=self.test_webhook, height=36,
                      fg_color="#374151", hover_color="#4b5563",
                      font=("微软雅黑", 12), corner_radius=8).pack(side="left", padx=4)
        ctk.CTkButton(b, text="打开直播页", command=self.open_url, height=36,
                      fg_color="#374151", hover_color="#4b5563",
                      font=("微软雅黑", 12), corner_radius=8).pack(side="left", padx=4)

    def _build_log(self):
        self.log = ctk.CTkTextbox(self, font=("Consolas", 11), fg_color="#12121a",
                                  corner_radius=12, border_color="#33334a", border_width=1)
        self.log.pack(fill="both", expand=True, padx=16, pady=(0, 14))
        self.log.insert("end", "EchoSign 就绪。填好配置 → 保存 → 登录登录态 → 启动监控。\n")
        self.log.configure(state="disabled")

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

    def _set_status(self, text: str, color: str):
        self.status_dot.configure(text=f"● {text}", text_color=color)

    def start_monitor(self):
        self.save_cfg()
        self.stop_event.clear()
        self.b_start.configure(state="disabled")
        self.b_stop.configure(state="normal")
        self._set_status("监控中", GREEN)

        def done_watch():
            while self.worker and self.worker.is_alive():
                time.sleep(0.3)
            self.after(0, lambda: (self.b_start.configure(state="normal"),
                                   self.b_stop.configure(state="disabled"),
                                   self._set_status("未运行", "#6b7280")))

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
                self.log.configure(state="normal")
                self.log.insert("end", line + "\n")
                self.log.see("end")
                self.log.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(200, self._poll_log)


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
