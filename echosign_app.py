"""EchoSign GUI: Vercel/Hermes 风格极简界面.

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
F = "Microsoft YaHei UI"       # 中文主体
FL = "Segoe UI Variable Text"  # 英文/品牌
FM = "Cascadia Code"           # 等宽

# ---------- 中性色 (Vercel/Hermes 风) ----------
BG = "#000000"            # 纯黑底
CARD = "#0a0a0a"          # 卡片
RAIL = "#1f1f23"          # 发丝线
INPUT_BG = "#0a0a0a"
INPUT_BORDER = "#29292e"
FOCUS = "#fafafa"         # 聚焦白描边
TXT = "#f7f7f8"
TXT2 = "#a1a1aa"
TXT3 = "#5b5b63"
GREEN = "#34d399"
RED = "#f87171"
PRIMARY = "#f7f7f8"       # 主按钮(近白)
PRIMARY_HOVER = "#ffffff"
GHOST_HOVER = "#191919"
SW_ON = "#f7f7f8"         # 开关开: 白底黑钮
SW_OFF = "#2e2e33"        # 开关关: 深灰底浅钮
KNOB_ON = "#000000"
KNOB_OFF = "#8a8a93"

BTN_FONT = (F, 12)
FIELD_FONT = (F, 12.5)
LABEL_FONT = (F, 11)


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


class Switch(ctk.CTkFrame):
    """自绘胶囊开关: 关=深灰底浅钮, 开=白底黑钮, 带滑动动画."""

    W, H, KNOB, PAD = 34, 20, 15, 2.5

    def __init__(self, master, variable: ctk.BooleanVar, **kw):
        super().__init__(master, width=self.W, height=self.H,
                         corner_radius=self.H // 2,
                         fg_color=self._track(variable.get()), **kw)
        self.var = variable
        self.knob = ctk.CTkFrame(self, width=self.KNOB, height=self.KNOB,
                                 corner_radius=self.KNOB // 2,
                                 fg_color=self._knob(variable.get()))
        self.knob.place(x=self._x(variable.get()), y=self.PAD)
        for w in (self, self.knob):
            w.bind("<Button-1>", self.toggle)

    def _track(self, on): return SW_ON if on else SW_OFF
    def _knob(self, on): return KNOB_ON if on else KNOB_OFF
    def _x(self, on): return self.W - self.KNOB - self.PAD if on else self.PAD

    def toggle(self, _=None):
        on = not self.var.get()
        self.var.set(on)
        for i in range(4):
            t = i / 3.0
            x0, x1 = self._x(not on), self._x(on)
            self.after(i * 25, lambda v=x0 + (x1 - x0) * t, final=(i == 3):
                       self._paint(v, on if final else not on))

    def _paint(self, x, on):
        self.knob.place(x=x, y=self.PAD)
        self.configure(fg_color=self._track(on))
        self.knob.configure(fg_color=self._knob(on))


class Entry(ctk.CTkEntry):
    """带白色聚焦环的输入框."""

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", INPUT_BG)
        kw.setdefault("border_color", INPUT_BORDER)
        kw.setdefault("border_width", 1)
        kw.setdefault("corner_radius", 8)
        kw.setdefault("text_color", TXT)
        super().__init__(master, **kw)
        self.bind("<FocusIn>", lambda _: self.configure(border_color=FOCUS),
                  add="+")
        self.bind("<FocusOut>",
                  lambda _: self.configure(border_color=INPUT_BORDER),
                  add="+")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=BG)
        self.title(f"EchoSign {APP_VERSION}")
        self.geometry("1060x660")
        self.minsize(980, 560)

        self.cfg = load_cfg()
        self.secrets = load_secrets()
        self.log_q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self._t0: float | None = None

        self._navbar()
        self._divider(self)
        self._body()
        self._load_fields()
        self.after(200, self._poll_log)

    @staticmethod
    def _divider(parent, horizontal=True):
        if horizontal:
            ctk.CTkFrame(parent, height=1, fg_color=RAIL,
                         corner_radius=0).pack(fill="x")
        else:
            ctk.CTkFrame(parent, width=1, fg_color=RAIL,
                         corner_radius=0).pack(side="left", fill="y")

    # ---------------- 顶栏 ----------------
    def _navbar(self):
        bar = ctk.CTkFrame(self, fg_color=BG, height=54, corner_radius=0)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        inner = ctk.CTkFrame(bar, fg_color=BG)
        inner.pack(fill="both", expand=True, padx=24)

        logo = ctk.CTkFrame(inner, width=26, height=26, corner_radius=7,
                            fg_color=PRIMARY)
        logo.pack(side="left", pady=14)
        logo.pack_propagate(False)
        ctk.CTkLabel(logo, text="E", font=(FL, 13, "bold"),
                     text_color=BG).place(relx=0.5, rely=0.5, anchor="center")
        ctk.CTkLabel(inner, text="EchoSign", font=(FL, 14.5, "bold"),
                     text_color=TXT).pack(side="left", padx=(10, 0))
        ctk.CTkLabel(inner, text=f"  {APP_VERSION} · 直播自动签到",
                     font=(F, 11), text_color=TXT3).pack(side="left",
                                                         pady=(4, 0))

        chip = ctk.CTkFrame(inner, fg_color=CARD, corner_radius=14,
                            border_color=RAIL, border_width=1)
        chip.pack(side="right", pady=13)
        self._dot = ctk.CTkLabel(chip, text="●", font=(F, 11),
                                 text_color=TXT3)
        self._dot.pack(side="left", padx=(10, 4), pady=4)
        self._status = ctk.CTkLabel(chip, text="就绪", font=(F, 11.5),
                                    text_color=TXT2)
        self._status.pack(side="left", padx=(0, 10))

    # ---------------- 主体 ----------------
    def _body(self):
        body = ctk.CTkFrame(self, fg_color=BG)
        body.pack(fill="both", expand=True)

        # ---- 左列: 配置(可滚动) + 底部固定操作区 ----
        left = ctk.CTkFrame(body, fg_color=BG, width=560, corner_radius=0)
        left.pack(side="left", fill="both")
        left.pack_propagate(False)

        actions = ctk.CTkFrame(left, fg_color=BG)
        actions.pack(side="bottom", fill="x", padx=28, pady=(0, 12))
        scroll = ctk.CTkScrollableFrame(
            left, fg_color=BG, corner_radius=0,
            scrollbar_button_color="#1c1c1f",
            scrollbar_button_hover_color="#2e2e33")
        scroll.pack(fill="both", expand=True)
        pad = ctk.CTkFrame(scroll, fg_color=BG)
        pad.pack(fill="both", expand=True, padx=(28, 14), pady=(14, 10))
        pad.grid_columnconfigure((0, 1), weight=1, uniform="c")
        self._left_need = 0

        hdr = ctk.CTkFrame(pad, fg_color=BG)
        hdr.grid(row=0, column=0, columnspan=2, sticky="ew")
        ctk.CTkLabel(hdr, text="配置", font=(F, 15, "bold"),
                     text_color=TXT).pack(side="left")
        ctk.CTkLabel(hdr, text="每一项都会写入本地 config.yaml",
                     font=(F, 11), text_color=TXT3).pack(side="right",
                                                         pady=(4, 0))

        self.v_url = ctk.StringVar()
        self.v_user = ctk.StringVar()
        self.v_pwd = ctk.StringVar()
        self.v_hook = ctk.StringVar()
        self.v_lat = ctk.StringVar()
        self.v_lng = ctk.StringVar()
        self.v_auto = ctk.BooleanVar(value=True)
        self.v_sem = ctk.BooleanVar(value=False)

        def field(r, c, label, var, show="", span=1, ph=""):
            ctk.CTkLabel(pad, text=label, font=LABEL_FONT, text_color=TXT2,
                         anchor="w").grid(row=r, column=c, columnspan=span,
                                          sticky="ew", padx=(0, 12),
                                          pady=(8, 4))
            e = Entry(pad, textvariable=var, show=show, height=31,
                      font=(F, 12),
                      placeholder_text=ph, placeholder_text_color=TXT3)
            e.grid(row=r + 1, column=c, columnspan=span, sticky="ew",
                   padx=(0, 12))
            return e

        field(1, 0, "直播页网址", self.v_url, span=2,
              ph="https://…")
        field(3, 0, "学号", self.v_user)
        field(3, 1, "密码", self.v_pwd, show="•")
        field(5, 0, "企微 Webhook", self.v_hook, span=2,
              ph="可选 · 用于推送签到结果")
        field(7, 0, "纬度", self.v_lat)
        field(7, 1, "经度", self.v_lng)

        ctk.CTkLabel(pad, text="签到关键词", font=LABEL_FONT,
                     text_color=TXT2, anchor="w"
                     ).grid(row=9, column=0, columnspan=2, sticky="ew",
                            pady=(8, 5))
        self.txt_rules = ctk.CTkTextbox(pad, height=46, font=FIELD_FONT,
                                        fg_color=INPUT_BG, text_color=TXT,
                                        border_color=INPUT_BORDER,
                                        border_width=1, corner_radius=8)
        self.txt_rules.grid(row=10, column=0, columnspan=2, sticky="ew",
                            padx=(0, 12))
        ctk.CTkLabel(pad, text="每行一个，听到任一关键词即触发签到",
                     font=(F, 11), text_color=TXT3, anchor="w"
                     ).grid(row=11, column=0, columnspan=2, sticky="w",
                            pady=(4, 0))

        def switch_row(r, text, desc, var):
            row = ctk.CTkFrame(pad, fg_color=BG)
            row.grid(row=r, column=0, columnspan=2, sticky="ew",
                     pady=(8, 0), padx=(0, 12))
            track = Switch(row, var)
            track.pack(side="left", pady=2)
            tb = ctk.CTkFrame(row, fg_color=BG)
            tb.pack(side="left", padx=(12, 0))
            ctk.CTkLabel(tb, text=text, font=(F, 12.5, "bold"),
                         text_color=TXT, anchor="w").pack(side="left")
            ctk.CTkLabel(tb, text="   " + desc, font=(F, 11),
                         text_color=TXT3).pack(side="left")
            tb.bind("<Button-1>", lambda _=None, s=track: s.toggle())

        switch_row(12, "自动签到", "识别到签到码后自动打开浏览器完成签到", self.v_auto)
        switch_row(13, "语义匹配", "用语义模型兜底识别非常规口令(启动稍慢)", self.v_sem)

        # 操作 (固定在左列底部, 永远可见)
        act = ctk.CTkFrame(actions, fg_color=BG)
        act.pack(fill="x")
        act.grid_columnconfigure(0, weight=1)
        self.b_start = ctk.CTkButton(
            act, text="启动监控", command=self.start_monitor,
            fg_color=PRIMARY, hover_color=PRIMARY_HOVER, text_color=BG,
            font=(F, 12.5, "bold"), height=34, corner_radius=8)
        self.b_start.grid(row=0, column=0, sticky="ew")
        self.b_stop = ctk.CTkButton(
            act, text="停止", command=self.stop_monitor,
            fg_color="transparent", hover_color="#2a1518",
            text_color=TXT2, border_color="#2e2e33", border_width=1,
            font=BTN_FONT, height=34, width=84, corner_radius=8,
            state="disabled")
        self.b_stop.grid(row=0, column=1, padx=(10, 0))

        tools = ctk.CTkFrame(actions, fg_color=BG)
        tools.pack(fill="x", pady=(6, 0))
        tools.grid_columnconfigure((0, 1, 2, 3), weight=1, uniform="t")
        for i, (text, cmd) in enumerate((
                ("保存配置", self.save_cfg),
                ("登录态", self.do_login),
                ("测试推送", self.test_webhook),
                ("打开直播页", self.open_url))):
            ctk.CTkButton(tools, text=text, command=cmd,
                          fg_color="transparent", hover_color=GHOST_HOVER,
                          text_color=TXT2, font=(F, 11), height=26,
                          corner_radius=6).grid(row=0, column=i,
                                                padx=(0, 4), sticky="ew")

        # ---- 右列: 日志 ----
        self._divider(body, horizontal=False)
        right = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        right.pack(side="left", fill="both", expand=True)
        rpad = ctk.CTkFrame(right, fg_color=BG)
        rpad.pack(fill="both", expand=True, padx=24, pady=(14, 10))

        rh = ctk.CTkFrame(rpad, fg_color=BG)
        rh.pack(fill="x")
        ctk.CTkLabel(rh, text="日志", font=(F, 15, "bold"),
                     text_color=TXT).pack(side="left")
        ctk.CTkButton(rh, text="清空", width=52, height=24,
                      fg_color="transparent", hover_color=GHOST_HOVER,
                      text_color=TXT3, font=(F, 11), corner_radius=6,
                      command=self.clear_log).pack(side="right")

        term = ctk.CTkFrame(rpad, fg_color=CARD, corner_radius=10,
                            border_color=RAIL, border_width=1)
        term.pack(fill="both", expand=True, pady=(14, 0))
        self.log = ctk.CTkTextbox(term, font=(FM, 11), height=140,
                                  fg_color=CARD, text_color="#c4c4cc",
                                  border_width=0, corner_radius=10)
        self.log.pack(fill="both", expand=True, padx=10, pady=10)
        self.log.insert("end", "$ echosign 就绪\n"
                               "$ 流程: 保存配置 → 登录态 → 启动监控\n")
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

    def _set_status(self, dot: str, text: str):
        self._dot.configure(text_color=dot)
        self._status.configure(text=text)

    def start_monitor(self):
        self.save_cfg()
        self.stop_event.clear()
        self.b_start.configure(state="disabled")
        self.b_stop.configure(state="normal", text_color=RED,
                              border_color="#5b1f23")
        self._set_status(GREEN, "监控中")
        self._t0 = time.time()

        def done_watch():
            while self.worker and self.worker.is_alive():
                time.sleep(0.3)
            self.after(0, lambda: (self.b_start.configure(state="normal"),
                                   self.b_stop.configure(state="disabled",
                                                         text_color=TXT2,
                                                         border_color="#2e2e33"),
                                   self._set_status(TXT3, "就绪")))

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
