"""EchoSign desktop console.

  python echosign_app.py           # 图形界面
  EchoSign.exe --sign 2330         # 打包后自动签到入口（内部使用）
"""
from __future__ import annotations

import copy
import json
import math
import os
import queue
import re
import sys
import threading
import time
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from urllib.parse import urlparse

if getattr(sys, "frozen", False):
    APP_ROOT = Path(sys.executable).parent
else:
    APP_ROOT = Path(__file__).resolve().parent
os.chdir(APP_ROOT)

# AutoSigner 在打包环境中通过同一个 exe 启动浏览器签到。
if len(sys.argv) >= 3 and sys.argv[1] == "--sign":
    sys.argv = ["browser_sign.py", *sys.argv[2:]]
    import browser_sign

    sys.exit(browser_sign.main())

import customtkinter as ctk  # noqa: E402
import yaml  # noqa: E402

CONFIG = APP_ROOT / "config.yaml"
SECRETS = APP_ROOT / "secrets_local.json"
RESOURCE_ROOT = Path(getattr(sys, "_MEIPASS", APP_ROOT))

APP_VERSION = "v1.2"
F = "Microsoft YaHei UI"
FM = "Cascadia Code"

# (浅色, 深色)：沿用 Hermes 软件的中性色层次，蓝色只用于交互强调。
BG = ("#f3f4f6", "#171a1e")
CARD = ("#fcfcfd", "#202429")
SURFACE = ("#eaedf2", "#2a3037")
RAIL = ("#dde2e8", "#343b44")
INPUT_BG = ("#f6f7f9", "#1a1e23")
INPUT_BORDER = ("#cdd4dd", "#414b57")
FOCUS = ("#5279bb", "#7597ce")
TXT = ("#252d39", "#e5e9ef")
TXT2 = ("#5d6978", "#b3bdca")
TXT3 = ("#707c8c", "#8996a7")
GREEN = ("#287254", "#91c6a6")
AMBER = ("#96661f", "#d2b47b")
RED = ("#b44b58", "#db939d")
PRIMARY = ("#426fba", "#456eb8")
PRIMARY_HOVER = ("#355fa6", "#3c61a5")
BUTTON_TEXT = "#ffffff"
GHOST_HOVER = ("#e5eaf1", "#303842")
TAB_SELECTED = ("#e3ebf9", "#2c3c54")
SW_ON = PRIMARY
SW_OFF = ("#bdc7d4", "#4b5868")
KNOB_ON = "#ffffff"
KNOB_OFF = ("#ffffff", "#d9e0e8")
RADIUS = 8

BTN_FONT = (F, 12)
FIELD_FONT = (F, 13)
LABEL_FONT = (F, 12)
MAX_LOG_LINES = 1500


def load_cfg() -> dict:
    path = CONFIG if CONFIG.exists() else RESOURCE_ROOT / "config.example.yaml"
    if not path.exists():
        return {}
    cfg = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(cfg, dict):
        raise ValueError("配置文件内容应为键值配置")
    return cfg


def load_secrets() -> dict:
    if SECRETS.exists():
        return json.loads(SECRETS.read_text(encoding="utf-8"))
    return {"skl_username": "", "skl_password": ""}


class QueueWriter:
    """把后台输出送到主线程，不直接操作 Tk 控件。"""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, s):
        if s and s.strip():
            for line in s.splitlines():
                if line.strip():
                    self.q.put(line.rstrip())
        return len(s)

    def flush(self):
        pass


class Switch(ctk.CTkFrame):
    """可聚焦的胶囊开关；变量变化与快速连点均能保持显示同步。"""

    W, H, KNOB, PAD = 36, 22, 16, 3

    def __init__(self, master, variable: ctk.BooleanVar, **kw):
        super().__init__(
            master, width=self.W, height=self.H, corner_radius=11,
            fg_color=SW_ON if variable.get() else SW_OFF, **kw)
        self.var = variable
        self._anim = 0
        self._jobs = []
        self._position = self._x(variable.get())
        self.knob = ctk.CTkFrame(
            self, width=self.KNOB, height=self.KNOB, corner_radius=8,
            fg_color=KNOB_ON if variable.get() else KNOB_OFF)
        self.knob.place(x=self._position, y=self.PAD)
        self._canvas.configure(takefocus=1)
        self.bind("<FocusIn>", lambda _: self.configure(
            border_width=1, border_color=FOCUS))
        self.bind("<FocusOut>", lambda _: self.configure(border_width=0))
        self.bind("<space>", self.toggle)
        self.bind("<Return>", self.toggle)
        for widget in (self, self.knob):
            widget.configure(cursor="hand2")
            widget.bind("<Button-1>", self.toggle)
        self._trace = self.var.trace_add("write", self._sync)

    def _x(self, on):
        return self.W - self.KNOB - self.PAD if on else self.PAD

    def toggle(self, _=None):
        self._canvas.focus_set()
        self.var.set(not self.var.get())
        return "break"

    def _sync(self, *_):
        self._anim += 1  # 让快速连点留下的旧回调失效。
        for job in self._jobs:
            self.after_cancel(job)
        self._jobs.clear()
        gen = self._anim
        on = self.var.get()
        x0, x1 = self._position, self._x(on)
        self.configure(fg_color=SW_ON if on else SW_OFF)
        self.knob.configure(fg_color=KNOB_ON if on else KNOB_OFF)
        for i in range(1, 5):
            t = 1 - (1 - i / 4) ** 2
            self._jobs.append(self.after(
                i * 20, lambda x=x0 + (x1 - x0) * t: self._paint(x, gen)))

    def _paint(self, x, gen):
        if gen == self._anim:
            self._position = x
            self.knob.place(x=x, y=self.PAD)

    def destroy(self):
        self.var.trace_remove("write", self._trace)
        for job in self._jobs:
            self.after_cancel(job)
        super().destroy()


class Entry(ctk.CTkEntry):
    """统一的输入框，支持聚焦和字段校验反馈。"""

    def __init__(self, master, **kw):
        kw.setdefault("fg_color", INPUT_BG)
        kw.setdefault("border_color", INPUT_BORDER)
        kw.setdefault("border_width", 1)
        kw.setdefault("corner_radius", RADIUS)
        kw.setdefault("text_color", TXT)
        kw.setdefault("height", 40)
        kw.setdefault("font", FIELD_FONT)
        super().__init__(master, **kw)
        self.invalid = False
        self.bind("<FocusIn>", lambda _: self.configure(
            border_color=RED if self.invalid else FOCUS), add="+")
        self.bind("<FocusOut>", lambda _: self.configure(
            border_color=RED if self.invalid else INPUT_BORDER), add="+")
        self.bind("<KeyRelease>", self._editing, add="+")

    def _editing(self, _=None):
        if self.invalid:
            self.invalid = False
            self.configure(border_color=FOCUS)

    def set_error(self):
        self.invalid = True
        self.focus_set()
        self.configure(border_color=RED)


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.cfg = load_cfg()
        self._appearance = (self.cfg.get("ui") or {}).get("appearance", "dark")
        if self._appearance not in ("light", "dark"):
            self._appearance = "dark"
        ctk.set_appearance_mode(self._appearance)
        self.configure(fg_color=BG)
        self.title(f"EchoSign {APP_VERSION}")
        icon = RESOURCE_ROOT / "assets" / "echosign.ico"
        if icon.exists():
            self.iconbitmap(str(icon))
        self.geometry("1100x700")
        self.minsize(940, 560)

        self.secrets = load_secrets()
        self.log_q: queue.Queue = queue.Queue()
        self.task_q: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.stop_event = threading.Event()
        self._task_kind: str | None = None
        self._t0: float | None = None
        self._loading = True
        self._poll_job = None
        self._tick_job = None
        self._pages = {}
        self._tabs = {}
        self._entries = {}
        self._field_actions = {}
        self.v_url = ctk.StringVar()
        self.v_user = ctk.StringVar()
        self.v_pwd = ctk.StringVar()
        self.v_hook = ctk.StringVar()
        self.v_lat = ctk.StringVar()
        self.v_lng = ctk.StringVar()
        self.v_auto = ctk.BooleanVar(value=True)
        self.v_sem = ctk.BooleanVar(value=False)
        self.v_follow = ctk.BooleanVar(value=True)

        self._body()
        self._load_fields()
        self._loading = False
        self._saved_values = self._field_values()
        for var in (self.v_url, self.v_user, self.v_pwd, self.v_hook,
                    self.v_lat, self.v_lng, self.v_auto, self.v_sem):
            var.trace_add("write", self._mark_dirty)
        self.txt_rules.bind("<<Modified>>", self._rules_changed, add="+")
        self.txt_rules.edit_modified(False)
        self.bind("<Control-s>", lambda _: self.save_cfg())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_job = self.after(100, self._poll_log)
        self._tick_job = self.after(1000, self._tick)

    @staticmethod
    def _label(parent, text, size=12, color=TXT2, bold=False, family=F, **kw):
        kw.setdefault("height", 0)
        return ctk.CTkLabel(
            parent, text=text, font=(family, size, "bold") if bold else (family, size),
            text_color=color, anchor="w", **kw)

    @staticmethod
    def _divider(parent, pady=16):
        ctk.CTkFrame(parent, height=1, fg_color=RAIL,
                     corner_radius=0).pack(fill="x", pady=pady)

    @staticmethod
    def _button(parent, text, command, **kw):
        kw.setdefault("height", 34)
        kw.setdefault("corner_radius", RADIUS)
        kw.setdefault("font", BTN_FONT)
        kw.setdefault("fg_color", "transparent")
        kw.setdefault("hover_color", GHOST_HOVER)
        kw.setdefault("text_color", TXT2)
        kw.setdefault("text_color_disabled", TXT3)
        return ctk.CTkButton(parent, text=text, command=command, **kw)


    def _body(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=24, pady=24)
        body.grid_columnconfigure(0, weight=0, minsize=400)
        body.grid_columnconfigure(1, weight=1, minsize=440)
        body.grid_rowconfigure(0, weight=1)
        self._settings(body)
        self._monitor_panel(body)

    def _settings(self, body):
        card = ctk.CTkFrame(body, fg_color=CARD, corner_radius=RADIUS,
                            border_color=RAIL, border_width=1)
        card.grid(row=0, column=0, sticky="nsew", padx=(0, 16))
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 10))
        self._label(header, "设置", 15, TXT, True).pack(side="left")
        self.b_save = self._button(
            header, "保存", self.save_cfg, width=52, height=30)
        self.b_save.pack(side="right")

        tabbar = ctk.CTkFrame(card, fg_color=SURFACE, corner_radius=RADIUS)
        tabbar.pack(fill="x", padx=20, pady=(0, 14))
        tabbar.grid_columnconfigure((0, 1, 2), weight=1, uniform="tabs")
        for i, (key, title) in enumerate((
                ("basic", "直播与账号"), ("rules", "识别设置"),
                ("extras", "通知与定位"))):
            tab = self._button(
                tabbar, title, lambda k=key: self._select_tab(k),
                width=0, height=32, font=(F, 11))
            tab.grid(row=0, column=i, sticky="ew", padx=3, pady=3)
            self._tabs[key] = tab

        # 底部操作独立于滚动内容，小窗口中也始终可见。
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(side="bottom", fill="x", padx=20, pady=(0, 16))
        self._divider(actions, pady=(8, 10))
        self._save_state = self._label(
            actions, "", 11, TXT3, height=18)
        self._save_state.pack(fill="x", pady=(0, 8))
        row = ctk.CTkFrame(actions, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure(0, weight=1)
        self.b_start = self._button(
            row, "启动监控", self.start_monitor, height=42,
            fg_color=PRIMARY, hover_color=PRIMARY_HOVER,
            text_color=BUTTON_TEXT, text_color_disabled="#a5b1c5",
            font=(F, 13, "bold"))
        self.b_start.grid(row=0, column=0, sticky="ew")
        self.b_stop = self._button(
            row, "停止", self.stop_monitor, width=76, height=42,
            border_color=INPUT_BORDER, border_width=1, state="disabled")
        self.b_stop.grid(row=0, column=1, padx=(10, 0))

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=(14, 10))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        for key in self._tabs:
            page = ctk.CTkScrollableFrame(
                content, fg_color=CARD, corner_radius=0,
                scrollbar_button_color=RAIL,
                scrollbar_button_hover_color=INPUT_BORDER)
            page.grid(row=0, column=0, sticky="nsew")
            self._pages[key] = page
        self._basic_page(self._pages["basic"])
        self._rules_page(self._pages["rules"])
        self._extras_page(self._pages["extras"])
        self._select_tab("basic")


    def _field(self, parent, key, title, var, show="", action=None):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(fill="x", pady=(0, 12))
        caption = ctk.CTkFrame(box, fg_color="transparent", height=22)
        caption.pack(fill="x", pady=(0, 5))
        caption.pack_propagate(False)
        self._label(caption, title, 12, TXT2).pack(side="left")
        if action:
            button = self._button(
                caption, action[0], action[1], width=60, height=22,
                font=(F, 11), text_color=TXT2)
            button.pack(side="right")
            self._field_actions[key] = button
        entry = Entry(box, textvariable=var, show=show)
        entry.pack(fill="x")
        self._entries[key] = entry
        return entry

    def _basic_page(self, page):
        self._field(page, "url", "直播网址", self.v_url,
                    action=("打开 ↗", self.open_url))
        self._divider(page, 10)
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure((0, 1), weight=1, uniform="account")
        user = ctk.CTkFrame(row, fg_color="transparent")
        user.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        pwd = ctk.CTkFrame(row, fg_color="transparent")
        pwd.grid(row=0, column=1, sticky="nsew")
        self._field(user, "user", "学号", self.v_user)
        self.e_pwd = self._field(
            pwd, "pwd", "密码", self.v_pwd, show="•",
            action=("显示密码", self._toggle_password))
        self.b_pwd = self._field_actions["pwd"]
        self.b_login = self._button(
            page, "登录 / 刷新", self.do_login, width=116, height=32,
            border_color=INPUT_BORDER, border_width=1)
        self.b_login.pack(anchor="w")
        self._divider(page, 18)
        self._switch_row(
            page, "自动签到", "识别到签到码后自动提交", self.v_auto)

    def _rules_page(self, page):
        self._label(page, "签到关键词", 13, TXT, True).pack(anchor="w")
        self._label(page, "每行一项，支持 re: 正则表达式。", 11, TXT3).pack(
            anchor="w", pady=(2, 10))
        self.txt_rules = ctk.CTkTextbox(
            page, height=185, font=FIELD_FONT, fg_color=INPUT_BG,
            text_color=TXT, border_color=INPUT_BORDER, border_width=1,
            corner_radius=RADIUS, wrap="word", spacing1=3, spacing3=3)
        self.txt_rules.pack(fill="x")
        self.txt_rules.bind("<FocusIn>", lambda _: self.txt_rules.configure(
            border_color=FOCUS), add="+")
        self.txt_rules.bind("<FocusOut>", lambda _: self.txt_rules.configure(
            border_color=INPUT_BORDER), add="+")
        self._divider(page, 16)
        self._switch_row(
            page, "语义辅助识别", "识别相近话术，首次加载较慢",
            self.v_sem)


    def _extras_page(self, page):
        self._field(
            page, "hook", "企业微信 Webhook（可选）", self.v_hook,
            show="•", action=("测试推送", self.test_webhook))
        self.b_test = self._field_actions["hook"]
        self._divider(page, 18)
        self._label(page, "签到位置", 12, TXT2).pack(anchor="w", pady=(0, 8))
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure((0, 1), weight=1, uniform="location")
        for i, (key, title, var) in enumerate((
                ("lat", "纬度", self.v_lat), ("lng", "经度", self.v_lng))):
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.grid(row=0, column=i, sticky="ew", padx=(0, 10) if i == 0 else 0)
            self._field(col, key, title, var)

    def _switch_row(self, parent, title, desc, variable):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        track = Switch(row, variable)
        track.pack(side="right", padx=(14, 2))
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        self._label(text, title, 13, TXT, True).pack(anchor="w")
        description = self._label(text, desc, 11, TXT3, justify="left", wraplength=260)
        description.pack(fill="x", pady=(3, 0))
        text.bind("<Configure>", lambda e: description.configure(
            wraplength=max(120, int(e.width / description._get_widget_scaling()) - 4)), add="+")
        for widget in (row, text, *text.winfo_children()):
            widget.bind("<Button-1>", track.toggle)
        return track

    def _select_tab(self, key):
        self._active_tab = key
        for name, page in self._pages.items():
            if name == key:
                page.grid()
            else:
                page.grid_remove()
            self._tabs[name].configure(
                fg_color=TAB_SELECTED if name == key else "transparent",
                hover_color=TAB_SELECTED if name == key else GHOST_HOVER,
                text_color=PRIMARY if name == key else TXT2)


    def _monitor_panel(self, body):
        panel = ctk.CTkFrame(
            body, fg_color=CARD, corner_radius=RADIUS,
            border_color=RAIL, border_width=1)
        panel.grid(row=0, column=1, sticky="nsew")

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.pack(fill="x", padx=20, pady=(16, 12))
        self._label(header, "实时监控", 15, TXT, True).pack(side="left")
        self._dot = self._label(header, "●", 9, TXT3)
        self._dot.pack(side="left", padx=(14, 5))
        self._status = self._label(header, "就绪", 11, TXT3)
        self._status.pack(side="left")
        self.b_theme = self._button(
            header, "切换浅色" if self._appearance == "dark" else "切换深色",
            self.toggle_theme, width=76, height=30, font=(F, 11))
        self.b_theme.pack(side="right")

        meta = ctk.CTkFrame(panel, fg_color="transparent")
        meta.pack(fill="x", padx=20, pady=(0, 18))
        self._metrics = {}
        for key, title, value, side in (
                ("time", "运行", "00:00:00", "left"),
                ("code", "签到码", "— — — —", "right")):
            cell = ctk.CTkFrame(meta, fg_color="transparent")
            cell.pack(side=side)
            self._label(cell, title, 11, TXT3).pack(side="left", padx=(0, 8))
            number = ctk.CTkLabel(
                cell, text=value, height=22, font=(FM, 14), text_color=TXT2)
            number.pack(side="left")
            self._metrics[key] = number

        # 固定转写区高度，让长句也不会挤占日志和操作区域。
        transcript = ctk.CTkFrame(panel, fg_color="transparent", height=84)
        transcript.pack(fill="x", padx=20)
        transcript.pack_propagate(False)
        self._label(transcript, "实时转写", 11, TXT3).pack(anchor="w", pady=(0, 6))
        self._transcript = self._label(
            transcript, "等待课堂声音…", 13, TXT2,
            wraplength=480, justify="left", height=40)
        self._transcript.pack(fill="both", expand=True)
        transcript.bind("<Configure>", lambda e: self._transcript.configure(
            wraplength=max(200, int(e.width / self._transcript._get_widget_scaling()) - 2)),
            add="+")

        ctk.CTkFrame(panel, height=1, fg_color=RAIL, corner_radius=0).pack(
            fill="x", padx=20, pady=(12, 10))
        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=20, pady=(0, 6))
        self._label(head, "日志", 12, TXT2).pack(side="left")
        self._button(head, "清空", self.clear_log, width=42, height=28,
                     font=(F, 11)).pack(side="right")
        ctk.CTkCheckBox(
            head, text="自动滚动", variable=self.v_follow, width=90, height=22,
            checkbox_width=14, checkbox_height=14, corner_radius=4,
            border_width=1, border_color=TXT3, fg_color=PRIMARY,
            hover_color=PRIMARY_HOVER, checkmark_color=BUTTON_TEXT,
            text_color=TXT3, font=(F, 11)).pack(side="right", padx=(0, 8))
        self.log = ctk.CTkTextbox(
            panel, font=(F, 12), height=100, fg_color=CARD,
            text_color=TXT2, border_width=0, corner_radius=0,
            wrap="word", spacing1=3, spacing3=4,
            scrollbar_button_color=RAIL,
            scrollbar_button_hover_color=INPUT_BORDER)
        self.log.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._apply_log_colors()
        self.log.configure(state="disabled")
        self._empty_log = self._label(self.log, "暂无记录", 12, TXT3)
        self._empty_log.place(relx=0.5, rely=0.5, anchor="center")

    # ---------- 配置与即时反馈 ----------

    def _load_fields(self):
        self.v_url.set(str(self.cfg.get("live_url", "") or ""))
        self.v_user.set(self.secrets.get("skl_username", ""))
        self.v_pwd.set(self.secrets.get("skl_password", ""))
        hook = ((self.cfg.get("alert") or {}).get("webhook") or {}).get("url", "")
        self.v_hook.set(str(hook or ""))
        location = self.cfg.get("location") or {}
        self.v_lat.set(str(location.get("lat", 29.219569)))
        self.v_lng.set(str(location.get("lng", 119.47955)))
        self.v_auto.set(bool((self.cfg.get("auto_sign") or {}).get("enabled", True)))
        rules = self.cfg.get("rules") or {}
        self.v_sem.set(bool((rules.get("semantic") or {}).get("enabled", False)))
        self.txt_rules.insert("1.0", "\n".join(str(r) for r in rules.get("strong", [])))

    def _field_values(self):
        return (
            self.v_url.get(), self.v_user.get(), self.v_pwd.get(),
            self.v_hook.get(), self.v_lat.get(), self.v_lng.get(),
            self.v_auto.get(), self.v_sem.get(),
            self.txt_rules.get("1.0", "end-1c"),
        )

    def _mark_dirty(self, *_):
        if not self._loading:
            dirty = self._field_values() != self._saved_values
            self._save_state.configure(
                text="有未保存的更改" if dirty else "已保存",
                text_color=AMBER if dirty else TXT3)
            self.b_save.configure(text_color=PRIMARY if dirty else TXT2)

    def _rules_changed(self, _=None):
        if self.txt_rules.edit_modified():
            self.txt_rules.edit_modified(False)
            self._mark_dirty()

    def _feedback(self, message, error=False):
        self._save_state.configure(text=message, text_color=RED if error else GREEN)
        self.logline(f"[!] {message}" if error else f"[i] {message}")

    def _field_error(self, key, message):
        self._select_tab("extras" if key in ("lat", "lng", "hook") else "basic")
        self._entries[key].set_error()
        self._feedback(message, error=True)
        return False

    def save_cfg(self) -> bool:
        coords = {}
        for key, var, title, limit in (
                ("lat", self.v_lat, "纬度", 90),
                ("lng", self.v_lng, "经度", 180)):
            try:
                value = float(var.get().strip() or 0)
                if not math.isfinite(value) or not -limit <= value <= limit:
                    raise ValueError
            except ValueError:
                return self._field_error(key, f"{title}须为 {-limit} 到 {limit} 的数字")
            coords[key] = value
            self._entries[key].invalid = False
            self._entries[key].configure(border_color=INPUT_BORDER)

        cfg = copy.deepcopy(self.cfg)
        secrets = copy.deepcopy(self.secrets)
        cfg["ui"] = {**(cfg.get("ui") or {}), "appearance": self._appearance}
        cfg["live_url"] = self.v_url.get().strip()
        cfg.setdefault("alert", {}).setdefault("webhook", {})["url"] = self.v_hook.get().strip()
        cfg["location"] = {**(cfg.get("location") or {}), **coords}
        cfg.setdefault("auto_sign", {})["enabled"] = bool(self.v_auto.get())
        cfg.setdefault("rules", {}).setdefault("semantic", {})["enabled"] = bool(self.v_sem.get())
        cfg["rules"]["strong"] = [
            line.strip() for line in self.txt_rules.get("1.0", "end").splitlines()
            if line.strip()]
        secrets["skl_username"] = self.v_user.get().strip()
        secrets["skl_password"] = self.v_pwd.get()
        try:
            CONFIG.write_text(
                yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
            SECRETS.write_text(
                json.dumps(secrets, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError as exc:
            self._feedback(f"保存失败：{exc.strerror or '无法写入配置文件'}", error=True)
            return False
        self.cfg, self.secrets = cfg, secrets
        self._saved_values = self._field_values()
        self.b_save.configure(text_color=TXT2)
        self._feedback("已保存 · 设置将在下次启动时生效" if self._task_kind else "配置已保存")
        return True

    def _theme_color(self, value):
        if isinstance(value, (tuple, list)):
            return value[0 if self._appearance == "light" else 1]
        return value

    def _apply_log_colors(self):
        # Tk 文本标签不接受 CTk 的双色元组，切换时同步已有日志。
        for tag, color in (("time", TXT3), ("info", TXT2), ("success", GREEN),
                           ("error", RED), ("warn", AMBER), ("asr", TXT)):
            self.log.tag_config(tag, foreground=self._theme_color(color))

    def toggle_theme(self):
        self._appearance = "light" if self._appearance == "dark" else "dark"
        ctk.set_appearance_mode(self._appearance)
        self.b_theme.configure(
            text="切换浅色" if self._appearance == "dark" else "切换深色")
        self._apply_log_colors()
        # 单独记住主题，不提交表单中尚未保存的账号或其他修改。
        cfg = copy.deepcopy(self.cfg)
        cfg["ui"] = {**(cfg.get("ui") or {}), "appearance": self._appearance}
        try:
            CONFIG.write_text(
                yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except OSError:
            self._feedback("主题已切换，但偏好保存失败", error=True)
            return
        self.cfg = cfg

    def _toggle_password(self):
        hidden = bool(self.e_pwd.cget("show"))
        self.e_pwd.configure(show="" if hidden else "•")
        self.b_pwd.configure(text="隐藏密码" if hidden else "显示密码")

    # ---------- 后台动作与主线程状态 ----------
    def _busy(self):
        if self._task_kind is not None:
            self.logline("[!] 已有任务在运行，请等待完成或停止监控。")
            return True
        return False

    def _worker(self, fn, *args, kind="monitor"):
        if self._busy():
            return False
        self._task_kind = kind
        self.b_start.configure(state="disabled")
        self.b_login.configure(state="disabled")
        self.b_test.configure(state="disabled")
        if kind == "monitor":
            self._t0 = time.monotonic()
            self._metrics["time"].configure(text="00:00:00")
            self._metrics["code"].configure(text="— — — —", text_color=TXT)
            self._transcript.configure(text="正在等待课堂声音…", text_color=TXT3)
            self.b_start.configure(text="正在监控")
            self.b_stop.configure(state="normal", text="停止", text_color=RED)
            self._set_status(AMBER, "正在启动")
        elif kind == "login":
            self.b_login.configure(text="登录中…")
            self._set_status(AMBER, "登录中")
        else:
            self.b_test.configure(text="发送中…")
            self._set_status(AMBER, "测试通知")

        def run():
            failed = False
            writer = QueueWriter(self.log_q)
            with redirect_stdout(writer), redirect_stderr(writer):
                try:
                    result = fn(*args)
                    failed = type(result) is int and result != 0
                except SystemExit as exc:
                    failed = exc.code not in (None, 0)
                    if failed:
                        print(f"[错误] 任务退出：{exc.code}")
                except Exception as exc:  # noqa: BLE001
                    import traceback

                    failed = True
                    print(f"[错误] {exc}")
                    traceback.print_exc()
            self.task_q.put((kind, failed))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        return True

    def _set_status(self, color, status):
        self._dot.configure(text_color=color)
        self._status.configure(text=status, text_color=color)

    def _finish_task(self, kind, failed):
        if kind == "monitor":
            self._update_timer()
        self._task_kind = None
        self._t0 = None
        self.worker = None
        self.b_start.configure(state="normal", text="启动监控")
        self.b_stop.configure(state="disabled", text="停止", text_color=TXT3)
        self.b_login.configure(state="normal", text="登录 / 刷新")
        self.b_test.configure(state="normal", text="测试推送")
        if failed:
            self._set_status(RED, "任务异常")
        elif kind == "monitor":
            self._set_status(TXT3, "已停止")
            self.logline("[i] 监控已停止。")
        else:
            self._set_status(TXT3, "就绪")

    def start_monitor(self):
        if self._busy() or not self.save_cfg():
            return
        self.stop_event.clear()

        def run(cfg):
            import main as monitor

            if not self.stop_event.is_set():
                monitor.cmd_run(cfg, self.stop_event)

        self._worker(run, copy.deepcopy(self.cfg), kind="monitor")

    def stop_monitor(self):
        if self._task_kind != "monitor" or self.stop_event.is_set():
            return
        self.stop_event.set()
        self.b_stop.configure(state="disabled", text="停止中")
        self._set_status(AMBER, "正在停止")
        self.logline("[i] 正在停止监控…")

    def do_login(self):
        if self._busy() or not self.save_cfg():
            return

        def run():
            import browser_login

            return browser_login.main()

        self._worker(run, kind="login")

    def test_webhook(self):
        if self._busy():
            return
        if not self._valid_url(self.v_hook.get().strip()):
            self._field_error("hook", "请填写有效的企业微信 Webhook 地址")
            return
        if not self.save_cfg():
            return

        def run(cfg):
            import main as monitor

            monitor.cmd_webhook_test(cfg)

        self._worker(run, copy.deepcopy(self.cfg), kind="webhook")

    @staticmethod
    def _valid_url(value):
        try:
            parsed = urlparse(value)
            return parsed.scheme in ("http", "https") and bool(parsed.hostname)
        except ValueError:
            return False

    def open_url(self):
        url = self.v_url.get().strip()
        if not self._valid_url(url):
            self._field_error("url", "请填写以 http:// 或 https:// 开头的直播网址")
            return
        webbrowser.open(url)

    def _update_timer(self):
        if self._t0 is not None:
            elapsed = int(time.monotonic() - self._t0)
            self._metrics["time"].configure(
                text=f"{elapsed // 3600:02d}:{elapsed // 60 % 60:02d}:{elapsed % 60:02d}")

    def _tick(self):
        self._update_timer()
        self._tick_job = self.after(1000, self._tick)

    # ---------- 日志和实时转写 ----------
    def logline(self, s: str):
        self.log_q.put(s)

    def _append_log(self, line):
        line = line.strip()
        if not line:
            return
        if line.startswith("…识别中:"):
            self._transcript.configure(text=line.partition(":")[2].strip(), text_color=TXT2)
            return  # 中间识别结果只更新预览，不淹没最终日志。
        if line.startswith("[ASR "):
            self._transcript.configure(text=line.partition("]")[2].strip(), text_color=TXT)
        if (code := re.search(r"签到码[:：]\s*(\d{4})(?!\d)", line)):
            self._metrics["code"].configure(text=code.group(1), text_color=GREEN)
        if "ASR 就绪" in line and self._task_kind == "monitor" and not self.stop_event.is_set():
            self._set_status(GREEN, "监控中")
        if line.startswith("[错误]") or "Traceback" in line:
            tag = "error"
        elif line.startswith(("[!]", "[warn]")):
            tag = "warn"
        elif line.startswith("[OK]") or "签到提醒" in line:
            tag = "success"
        elif line.startswith("[ASR "):
            tag = "asr"
        else:
            tag = "info"
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S") + "  ", ("time",))
        self.log.insert("end", line + "\n", (tag,))
        excess = int(self.log.index("end-1c").split(".")[0]) - 1 - MAX_LOG_LINES
        if excess > 0:
            self.log.delete("1.0", f"{excess + 1}.0")
        if self.v_follow.get():
            self.log.see("end")
        self.log.configure(state="disabled")
        self._empty_log.place_forget()

    def clear_log(self):
        # 清空日志视图，保留本次运行时间、签到码和磁盘记录。
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._empty_log.place(relx=0.5, rely=0.5, anchor="center")

    def _poll_log(self):
        for _ in range(160):  # 批量处理有上限，避免大量输出阻塞按钮和窗口。
            try:
                self._append_log(self.log_q.get_nowait())
            except queue.Empty:
                break
        # 先处理完这一任务的输出，再切回空闲状态。
        if self.log_q.empty():
            try:
                self._finish_task(*self.task_q.get_nowait())
            except queue.Empty:
                pass
        self._poll_job = self.after(100, self._poll_log)

    def _on_close(self):
        self.stop_event.set()
        self.destroy()

    def destroy(self):
        for job in (self._poll_job, self._tick_job):
            if job:
                self.after_cancel(job)
        super().destroy()


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
