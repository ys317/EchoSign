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

APP_VERSION = "v1.1"

# ---------- 主题配色 ----------
BG = "#0d1117"
CARD = "#161b27"
CARD_BORDER = "#252e42"
FIELD = "#0f141f"
FIELD_BORDER = "#2b3550"
ACCENT = "#4f8cff"
ACCENT_HOVER = "#3b74e6"
GREEN = "#22c55e"
GREEN_HOVER = "#16a34a"
RED = "#ef4444"
RED_HOVER = "#dc2626"
TOOLBAR_BTN = "#212a3d"
TOOLBAR_HOVER = "#2c3850"
TXT = "#e6eaf2"
TXT_MUTED = "#8b94ad"
TXT_DIM = "#5b6478"


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
        self.configure(fg_color=BG)
        self.title(f"EchoSign {APP_VERSION}")
        self.geometry("880x760")
        self.minsize(800, 680)

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
        head = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_color=CARD_BORDER, border_width=1)
        head.pack(fill="x", padx=16, pady=(14, 6))

        # 左侧图标色块
        badge = ctk.CTkFrame(head, width=52, height=52, corner_radius=14, fg_color=ACCENT)
        badge.pack(side="left", padx=(14, 12), pady=14)
        badge.pack_propagate(False)
        ctk.CTkLabel(badge, text="ES", font=("微软雅黑", 18, "bold"),
                     text_color="#ffffff").place(relx=0.5, rely=0.5, anchor="center")

        col = ctk.CTkFrame(head, fg_color="transparent")
        col.pack(side="left", pady=14)
        trow = ctk.CTkFrame(col, fg_color="transparent")
        trow.pack(anchor="w")
        ctk.CTkLabel(trow, text="EchoSign", font=("微软雅黑", 22, "bold"),
                     text_color=TXT).pack(side="left")
        pill = ctk.CTkFrame(trow, fg_color="#1c2740", corner_radius=9)
        pill.pack(side="left", padx=(8, 0), pady=(6, 0))
        ctk.CTkLabel(pill, text=f" {APP_VERSION} ", font=("微软雅黑", 10, "bold"),
                     text_color=ACCENT).pack(padx=2, pady=1)
        ctk.CTkLabel(col, text="直播课堂 · 听音频识别签到码 · 自动浏览器签到",
                     font=("微软雅黑", 11), text_color=TXT_MUTED).pack(anchor="w", pady=(2, 0))

        # 右侧状态胶囊
        pill_bg = ctk.CTkFrame(head, fg_color="#121826", corner_radius=16,
                               border_color=CARD_BORDER, border_width=1)
        pill_bg.pack(side="right", padx=16, pady=14)
        self.status_dot = ctk.CTkLabel(pill_bg, text="●  未运行",
                                       font=("微软雅黑", 12, "bold"),
                                       text_color=TXT_DIM)
        self.status_dot.pack(padx=14, pady=6)

    def _section(self, title: str) -> ctk.CTkFrame:
        wrap = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_color=CARD_BORDER, border_width=1)
        wrap.pack(fill="x", padx=16, pady=(8, 0))
        ctk.CTkFrame(wrap, width=4, height=16, fg_color=ACCENT,
                     corner_radius=2).pack(side="left", padx=(14, 8), pady=(12, 0))
        ctk.CTkLabel(wrap, text=title, font=("微软雅黑", 12, "bold"),
                     text_color=TXT_MUTED).pack(side="left", anchor="n", pady=(10, 0))
        card = ctk.CTkFrame(wrap, fg_color="transparent")
        card.pack(fill="x", padx=6, pady=(4, 10))
        return card

    def _build_form(self):
        f = self._section("配置")
        f.grid_columnconfigure(1, weight=1)
        self.v_url = ctk.StringVar()
        self.v_user = ctk.StringVar()
        self.v_pwd = ctk.StringVar()
        self.v_hook = ctk.StringVar()
        self.v_lat = ctk.StringVar()
        self.v_lng = ctk.StringVar()
        self.v_auto = ctk.BooleanVar(value=True)
        self.v_sem = ctk.BooleanVar(value=False)

        def row(i, label, var, show="", wide=True, width=None):
            ctk.CTkLabel(f, text=label, font=("微软雅黑", 12), text_color=TXT_MUTED,
                         width=92, anchor="e").grid(row=i, column=0,
                                                    padx=(12, 8), pady=5, sticky="e")
            kw = {"width": width} if width else {}
            e = ctk.CTkEntry(f, textvariable=var, show=show, height=34,
                             font=("微软雅黑", 12), fg_color=FIELD,
                             border_color=FIELD_BORDER, border_width=1,
                             text_color=TXT, **kw)
            e.grid(row=i, column=1, sticky="ew" if wide else "w",
                   padx=(0, 14) if wide else (0, 0), pady=5)
            return e

        row(0, "直播页网址", self.v_url)
        row(1, "学号", self.v_user, wide=False, width=200)
        row(2, "密码", self.v_pwd, show="•", wide=False, width=200)
        row(3, "企微Webhook", self.v_hook)
        ctk.CTkLabel(f, text="纬度 / 经度", font=("微软雅黑", 12),
                     text_color=TXT_MUTED, width=92,
                     anchor="e").grid(row=4, column=0, padx=(12, 8), pady=5, sticky="e")
        geo = ctk.CTkFrame(f, fg_color="transparent")
        geo.grid(row=4, column=1, sticky="w", pady=5)
        ctk.CTkEntry(geo, textvariable=self.v_lat, width=130, height=34,
                     fg_color=FIELD, border_color=FIELD_BORDER, border_width=1,
                     text_color=TXT, placeholder_text="纬度").pack(side="left", padx=(0, 8))
        ctk.CTkEntry(geo, textvariable=self.v_lng, width=130, height=34,
                     fg_color=FIELD, border_color=FIELD_BORDER, border_width=1,
                     text_color=TXT, placeholder_text="经度").pack(side="left")

        ctk.CTkLabel(f, text="签到关键词", font=("微软雅黑", 12), text_color=TXT_MUTED,
                     width=92, anchor="e").grid(row=5, column=0, padx=(12, 8),
                                                pady=5, sticky="ne")
        self.txt_rules = ctk.CTkTextbox(f, height=72, font=("微软雅黑", 12),
                                        fg_color=FIELD, border_color=FIELD_BORDER,
                                        border_width=1, text_color=TXT,
                                        corner_radius=8)
        self.txt_rules.grid(row=5, column=1, sticky="ew", padx=(0, 14), pady=5)
        ctk.CTkLabel(f, text="每行一个", font=("微软雅黑", 10),
                     text_color=TXT_DIM).grid(row=5, column=2, padx=(4, 12), sticky="n")

        sw = ctk.CTkFrame(f, fg_color="transparent")
        sw.grid(row=6, column=0, columnspan=3, sticky="w", padx=12, pady=(4, 6))
        ctk.CTkSwitch(sw, text="听到签到码后自动签到", variable=self.v_auto,
                      progress_color=ACCENT, button_color=ACCENT,
                      font=("微软雅黑", 12), text_color=TXT
                      ).pack(side="left", padx=(0, 32))
        ctk.CTkSwitch(sw, text="语义匹配(启动稍慢)", variable=self.v_sem,
                      progress_color=ACCENT, button_color=ACCENT,
                      font=("微软雅黑", 12), text_color=TXT).pack(side="left")

    def _tool(self, parent, text, cmd):
        return ctk.CTkButton(parent, text=text, command=cmd, height=36,
                             fg_color=TOOLBAR_BTN, hover_color=TOOLBAR_HOVER,
                             border_color=CARD_BORDER, border_width=1,
                             font=("微软雅黑", 12), text_color=TXT,
                             corner_radius=9)

    def _build_buttons(self):
        bar = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                           border_color=CARD_BORDER, border_width=1)
        bar.pack(fill="x", padx=16, pady=8)
        inner = ctk.CTkFrame(bar, fg_color="transparent")
        inner.pack(fill="x", padx=12, pady=10)

        self.b_start = ctk.CTkButton(inner, text="▶  启动监控",
                                     command=self.start_monitor,
                                     fg_color=GREEN, hover_color=GREEN_HOVER,
                                     font=("微软雅黑", 13, "bold"), height=40,
                                     width=148, corner_radius=10)
        self.b_start.pack(side="left", padx=(0, 8))
        self.b_stop = ctk.CTkButton(inner, text="■  停止", command=self.stop_monitor,
                                    fg_color=RED, hover_color=RED_HOVER,
                                    font=("微软雅黑", 13, "bold"), height=40,
                                    width=104, corner_radius=10, state="disabled")
        self.b_stop.pack(side="left", padx=(0, 14))

        sep = ctk.CTkFrame(inner, width=1, height=28, fg_color=CARD_BORDER)
        sep.pack(side="left", padx=(0, 14))

        for text, cmd in (("保存配置", self.save_cfg),
                          ("登录/刷新登录态", self.do_login),
                          ("测试企微推送", self.test_webhook),
                          ("打开直播页", self.open_url)):
            self._tool(inner, text, cmd).pack(side="left", padx=(0, 8))

    def _build_log(self):
        wrap = ctk.CTkFrame(self, fg_color=CARD, corner_radius=14,
                            border_color=CARD_BORDER, border_width=1)
        wrap.pack(fill="both", expand=True, padx=16, pady=(4, 14))
        head = ctk.CTkFrame(wrap, fg_color="transparent")
        head.pack(fill="x", padx=12, pady=(8, 0))
        ctk.CTkFrame(head, width=4, height=16, fg_color=GREEN,
                     corner_radius=2).pack(side="left", padx=(0, 8))
        ctk.CTkLabel(head, text="运行日志", font=("微软雅黑", 12, "bold"),
                     text_color=TXT_MUTED).pack(side="left")
        ctk.CTkButton(head, text="清空", width=54, height=24,
                      fg_color="transparent", hover_color=CARD_BORDER,
                      text_color=TXT_DIM, font=("微软雅黑", 10),
                      corner_radius=6, command=self.clear_log).pack(side="right")

        self.log = ctk.CTkTextbox(wrap, font=("Consolas", 11), fg_color="#0a0e16",
                                  corner_radius=10, border_color=CARD_BORDER,
                                  border_width=1, text_color="#c9d3e6")
        self.log.pack(fill="both", expand=True, padx=10, pady=(6, 10))
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
        self.status_dot.configure(text=f"●  {text}", text_color=color)

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
                                   self._set_status("未运行", TXT_DIM)))

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

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

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
