"""EchoSign desktop console.

  python -m echosign               # 图形界面
  EchoSign.exe --sign 2330         # 打包后自动签到入口（内部使用）
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import math
import queue
import re
import sys
import threading
import time
import webbrowser
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from tkinter import TclError
from urllib.parse import urlparse

import customtkinter as ctk
import yaml

from echosign import __version__, ui as design
from echosign.location import DEFAULT_LAT, DEFAULT_LNG, Location, LocationError, get_current_location
from echosign.live import LiveCourse
from echosign.ui import Entry, Switch, TabButton
from echosign.runtime import application_root, resource_root

APP_ROOT = application_root()

CONFIG = APP_ROOT / "config.yaml"
SECRETS = APP_ROOT / "secrets_local.json"
RESOURCE_ROOT = resource_root()

APP_VERSION = f"v{__version__}"
MAX_LOG_LINES = 1500
SCHEDULE_START_DELAY = 2.0


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


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        design.configure_ui_fonts(self)
        self.cfg = load_cfg()
        self._appearance = (self.cfg.get("ui") or {}).get("appearance", "dark")
        if self._appearance not in ("light", "dark"):
            self._appearance = "dark"
        ctk.set_appearance_mode(self._appearance)
        self.configure(fg_color=design.BG)
        self.title(f"EchoSign {APP_VERSION}")
        icon = RESOURCE_ROOT / "assets" / "echosign.ico"
        if icon.exists():
            self.iconbitmap(str(icon))
        self.geometry("1180x760")
        self.minsize(960, 600)

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
        self._copy_job = None
        self._close_job = None
        self._closing = False
        self._code: str | None = None
        self._has_transcript = False
        self._pages = {}
        self._tabs = {}
        self._active_tab = None
        self._entries = {}
        self._field_actions = {}
        self._field_labels = {}
        self._active_audio_source = "system"
        self._monitor_ready = False
        self._live_courses = []
        self._live_course_lookup = {}
        self._scheduled_course: LiveCourse | None = None
        self.v_url = ctk.StringVar()
        self.v_user = ctk.StringVar()
        self.v_pwd = ctk.StringVar()
        self.v_hook = ctk.StringVar()
        self.v_lat = ctk.StringVar()
        self.v_lng = ctk.StringVar()
        self.v_auto = ctk.BooleanVar(value=True)
        self.v_sem = ctk.BooleanVar(value=False)
        self.v_live = ctk.BooleanVar(value=False)
        self.v_follow = ctk.BooleanVar(value=True)
        self.v_live_course = ctk.StringVar(value="登录后读取当前直播课")

        self._body()
        self._load_fields()
        self._loading = False
        self._saved_values = self._field_values()
        for var in (self.v_url, self.v_user, self.v_pwd, self.v_hook,
                    self.v_lat, self.v_lng, self.v_auto, self.v_sem, self.v_live):
            var.trace_add("write", self._mark_dirty)
        self.v_live.trace_add("write", self._update_audio_mode)
        self.v_url.trace_add("write", self._url_edited)
        self.txt_rules.bind("<<Modified>>", self._rules_changed, add="+")
        self.txt_rules.edit_modified(False)
        self.bind("<Control-s>", lambda _: self.save_cfg())
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self._poll_job = self.after(100, self._poll_log)
        self._tick_job = self.after(1000, self._tick)
        self._courses_job = self.after(350, self._load_saved_live_courses)

    @staticmethod
    def _label(parent, text, size=12, color=design.TXT2, bold=False, family=None, **kw):
        kw.setdefault("height", 0)
        kw.setdefault("anchor", "w")
        family = family or design.F
        return ctk.CTkLabel(
            parent, text=text, font=(family, size, "bold") if bold else (family, size),
            text_color=color, **kw)

    @staticmethod
    def _divider(parent, pady=16):
        ctk.CTkFrame(parent, height=1, fg_color=design.RAIL,
                     corner_radius=0).pack(fill="x", pady=pady)

    @staticmethod
    def _fit_wrap(label, pixels, minimum, padding):
        width = max(minimum, int(pixels / label._get_widget_scaling()) - padding)
        if label.cget("wraplength") != width:
            label.configure(wraplength=width)

    @staticmethod
    def _button(parent, text, command, **kw):
        kw.setdefault("height", 34)
        kw.setdefault("corner_radius", design.RADIUS)
        kw.setdefault("font", design.BTN_FONT)
        kw.setdefault("fg_color", "transparent")
        kw.setdefault("hover_color", design.GHOST_HOVER)
        kw.setdefault("text_color", design.TXT2)
        kw.setdefault("text_color_disabled", design.TXT3)
        return ctk.CTkButton(parent, text=text, command=command, **kw)


    def _body(self):
        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=0)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self._settings(body)
        self._monitor_panel(body)

    def _settings(self, body):
        card = ctk.CTkFrame(body, width=312, fg_color=design.CARD, corner_radius=0)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_propagate(False)
        card.pack_propagate(False)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=22, pady=(20, 18))
        self._label(header, "课堂设置", 14, design.TXT, True).pack(side="left")
        self.b_save = self._button(
            header, "保存", self.save_cfg, width=52, height=30)
        self.b_save.pack(side="right")

        tabbar = ctk.CTkFrame(card, fg_color=design.TAB_BG, corner_radius=11)
        tabbar.pack(fill="x", padx=22, pady=(0, 22))
        tabbar.grid_columnconfigure((0, 1, 2), weight=1, uniform="tabs")
        for i, (key, title) in enumerate((
                ("basic", "课堂"), ("signin", "签到"), ("extras", "更多"))):
            tab = TabButton(tabbar, text=title, command=lambda k=key: self._select_tab(k))
            tab.grid(row=0, column=i, sticky="ew", padx=(3, 0) if i < 2 else 3, pady=3)
            self._tabs[key] = tab

        # 底部操作独立于滚动内容，小窗口中也始终可见。
        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(side="bottom", fill="x", padx=22, pady=(8, 22))
        self._save_state = self._label(
            actions, "", 11, design.TXT3, height=18)
        self._save_state.pack(fill="x", pady=(0, 8))
        self.b_monitor = self._button(
            actions, "启动监控", self.toggle_monitor, height=44, corner_radius=14,
            fg_color=design.PRIMARY, hover_color=design.PRIMARY_HOVER,
            text_color=design.BUTTON_TEXT, text_color_disabled=design.BUTTON_DISABLED,
            image=design.ui_icon("play", 15, design.BUTTON_TEXT), compound="left",
            font=(design.F, 14, "bold"))
        self.b_monitor.pack(fill="x")

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=(22, 4))
        content.grid_rowconfigure(0, weight=1)
        content.grid_columnconfigure(0, weight=1)
        for key in self._tabs:
            page = ctk.CTkScrollableFrame(
                content, fg_color=design.CARD, corner_radius=0,
                scrollbar_fg_color=design.CARD, scrollbar_button_color=design.CARD,
                scrollbar_button_hover_color=design.INPUT_BORDER)
            self._pages[key] = page
        self._basic_page(self._pages["basic"])
        self._signin_page(self._pages["signin"])
        self._rules_page(self._pages["extras"])
        self._divider(self._pages["extras"], 16)
        self._extras_page(self._pages["extras"])
        self._select_tab("basic")


    def _field(self, parent, key, title, var, show="", action=None, bottom=16):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(fill="x", pady=(0, bottom))
        caption = ctk.CTkFrame(box, fg_color="transparent", height=22)
        caption.pack(fill="x", pady=(0, 6))
        caption.pack_propagate(False)
        label = self._label(caption, title, 12, design.TXT2)
        label.pack(side="left")
        self._field_labels[key] = label
        if action:
            button = self._button(
                caption, action[0], action[1], width=60, height=22,
                font=(design.F, 12), text_color=design.TXT2)
            button.pack(side="right")
            self._field_actions[key] = button
        entry = Entry(box, textvariable=var, show=show)
        entry.pack(fill="x")
        self._entries[key] = entry
        return entry

    def _basic_page(self, page):
        self._label(page, "当前直播", 13, design.TXT, True).pack(anchor="w", pady=(0, 8))
        course_row = ctk.CTkFrame(page, fg_color="transparent")
        course_row.pack(fill="x", pady=(0, 3))
        self.live_course_picker = ctk.CTkComboBox(
            course_row, width=244, height=36, state="disabled",
            values=[self.v_live_course.get()], variable=self.v_live_course,
            fg_color=design.INPUT_BG, border_color=design.INPUT_BORDER,
            button_color=design.RAIL, button_hover_color=design.FOCUS,
            dropdown_fg_color=design.SURFACE, dropdown_hover_color=design.GHOST_HOVER,
            dropdown_text_color=design.TXT, text_color=design.TXT2,
            font=(design.F, 12), dropdown_font=(design.F, 12),
            command=self._select_live_course)
        self.live_course_picker.pack(fill="x")
        course_actions = ctk.CTkFrame(page, fg_color="transparent")
        course_actions.pack(fill="x", pady=(6, 8))
        self.b_live_login = self._button(
            course_actions, "登录直播", self.do_live_login, width=88, height=30,
            border_color=design.INPUT_BORDER, border_width=1)
        self.b_live_login.pack(side="left")
        self.b_course_refresh = self._button(
            course_actions, "刷新课程", self.refresh_live_courses, width=76, height=30,
            font=(design.F, 12))
        self.b_course_refresh.pack(side="right", padx=(8, 0))
        self._live_course_hint = self._label(
            page, "先登录直播，再选择课程。无需复制每节课的网址。",
            11, design.TXT3, wraplength=244, justify="left")
        self._live_course_hint.pack(fill="x", pady=(0, 10))

        self.b_manual_url = self._button(
            page, "手动填写网址 ›", self._toggle_manual_url, height=26,
            anchor="w", font=(design.F, 11))
        self.b_manual_url.pack(fill="x", pady=(0, 6))
        self._manual_url = ctk.CTkFrame(page, fg_color="transparent")
        self._field(self._manual_url, "url", "课程网址（选填）", self.v_url,
                    action=("打开 ↗", self.open_url), bottom=6)
        self.b_url = self._field_actions["url"]

        mode = self._audio_mode_row = ctk.CTkFrame(page, fg_color="transparent")
        mode.pack(fill="x", pady=(6, 5))
        switch = Switch(mode, self.v_live)
        switch.pack(side="right")
        self.b_live_account = self._button(
            mode, "换账号", lambda: self.do_live_login(switch_account=True),
            width=56, height=22, font=(design.F, 11), text_color=design.TXT2)
        label = self._label(mode, "后台音频", 12, design.TXT2)
        label.pack(side="left")
        label.bind("<Button-1>", switch.toggle)
        self._url_hint = self._label(
            page, "已在浏览器播放课程时可留空。",
            11, design.TXT3, wraplength=244, justify="left")
        self._url_hint.pack(fill="x", pady=(0, 4))
        self._divider(page, (12, 12))
        self._switch_row(
            page, "自动签到", "启动监控时准备签到页，确认码后提交", self.v_auto)
        self._button(page, "账号与签到设置 →", lambda: self._select_tab("signin"),
                     height=28, anchor="w", font=(design.F, 11)).pack(fill="x")

    def _signin_page(self, page):
        self._label(page, "签到账号", 13, design.TXT, True).pack(anchor="w", pady=(0, 10))
        self._field(page, "user", "学号", self.v_user, bottom=12)
        self.e_pwd = self._field(
            page, "pwd", "密码", self.v_pwd, show="•",
            action=("显示密码", self._toggle_password), bottom=12)
        self.b_pwd = self._field_actions["pwd"]
        self.b_login = self._button(
            page, "登录 / 刷新", self.do_login, height=36,
            border_color=design.INPUT_BORDER, border_width=1)
        self.b_login.pack(fill="x")
        self._divider(page, (12, 8))
        self._location_fields(page)

    def _toggle_manual_url(self):
        self._show_manual_url(not bool(self._manual_url.winfo_manager()))

    def _show_manual_url(self, visible=True):
        if visible:
            self._manual_url.pack(fill="x", before=self._audio_mode_row)
        else:
            self._manual_url.pack_forget()
        self.b_manual_url.configure(text="收起手动网址 ‹" if visible else "手动填写网址 ›")

    def _rules_page(self, page):
        self._label(page, "签到关键词", 13, design.TXT, True).pack(anchor="w")
        self._label(page, "每行一项，支持 re: 正则表达式", 11, design.TXT3).pack(
            anchor="w", pady=(4, 12))
        self.txt_rules = ctk.CTkTextbox(
            page, height=224, font=(design.F, 13), fg_color=design.INPUT_BG,
            text_color=design.TXT, border_color=design.INPUT_BORDER, border_width=1,
            corner_radius=design.RADIUS, wrap="word", spacing1=4, spacing3=4)
        self.txt_rules.pack(fill="x")
        self.txt_rules.bind("<FocusIn>", lambda _: self.txt_rules.configure(
            border_color=design.FOCUS), add="+")
        self.txt_rules.bind("<FocusOut>", lambda _: self.txt_rules.configure(
            border_color=design.INPUT_BORDER), add="+")
        self._divider(page, 16)
        self._switch_row(
            page, "语义辅助识别", "识别相近话术，在本机运行",
            self.v_sem)


    def _extras_page(self, page):
        self._field(
            page, "hook", "企业微信 Webhook", self.v_hook,
            show="•", action=("测试推送", self.test_webhook))
        self.b_test = self._field_actions["hook"]
        self._label(page, "选填，留空时仅在本机提醒", 11, design.TXT3).pack(anchor="w")

    def _location_fields(self, page):
        caption = ctk.CTkFrame(page, fg_color="transparent")
        caption.pack(fill="x", pady=(0, 8))
        self._label(caption, "签到位置", 13, design.TXT2).pack(side="left")
        self.b_locate = self._button(
            caption, "获取当前位置", self.locate, width=96, height=26,
            font=(design.F, 11))
        self.b_locate.pack(side="right")
        row = ctk.CTkFrame(page, fg_color="transparent")
        row.pack(fill="x")
        row.grid_columnconfigure((0, 1), weight=1, uniform="location")
        for i, (key, title, var) in enumerate((
                ("lat", "纬度", self.v_lat), ("lng", "经度", self.v_lng))):
            col = ctk.CTkFrame(row, fg_color="transparent")
            col.grid(row=0, column=i, sticky="ew", padx=(0, 10) if i == 0 else 0)
            self._field(col, key, title, var, bottom=8)
        self._location_hint = self._label(
            page, "可通过 Windows 定位填入，请核对后保存。",
            11, design.TXT3, wraplength=244, justify="left")
        self._location_hint.pack(fill="x")

    def _switch_row(self, parent, title, desc, variable):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=(0, 8))
        track = Switch(row, variable)
        track.pack(side="right", padx=(14, 2))
        text = ctk.CTkFrame(row, fg_color="transparent")
        text.pack(side="left", fill="x", expand=True)
        self._label(text, title, 13, design.TXT, True).pack(anchor="w")
        description = self._label(text, desc, 11, design.TXT3, justify="left", wraplength=260)
        description.pack(fill="x", pady=(3, 0))
        text.bind("<Configure>", lambda e: self._fit_wrap(description, e.width, 120, 4), add="+")
        for widget in (row, text, *text.winfo_children()):
            widget.bind("<Button-1>", track.toggle)
        return track

    def _select_tab(self, key):
        if self._active_tab == key:
            return
        if self._active_tab is not None:
            # CTk replays cached grid calls on DPI changes. Forget the hidden
            # page's placement so scaling cannot make it reappear on top.
            self._pages[self._active_tab].grid_forget()
            self._tabs[self._active_tab].set_selected(False)
        self._pages[key].grid(row=0, column=0, sticky="nsew")
        self._tabs[key].set_selected(True)
        self._active_tab = key


    def _monitor_panel(self, body):
        panel = ctk.CTkFrame(body, fg_color=design.BG, corner_radius=0)
        panel.grid(row=0, column=1, sticky="nsew")

        header = ctk.CTkFrame(panel, fg_color="transparent")
        header.pack(fill="x", padx=32, pady=(20, 26))
        self._label(header, "课堂监控", 17, design.TXT, True).pack(side="left")
        status = ctk.CTkFrame(header, fg_color="transparent")
        status.pack(side="left", padx=(10, 0))
        self._dot = self._label(status, "●", 8, design.TXT3)
        self._dot.pack(side="left", padx=(10, 5), pady=6)
        self._status = self._label(status, "未开始", 11, design.TXT3)
        self._status.pack(side="left", padx=(0, 10), pady=6)
        self.b_theme = self._button(
            header, "浅色" if self._appearance == "dark" else "深色",
            self.toggle_theme, width=72, height=30, font=(design.F, 12),
            image=design.ui_icon("sun" if self._appearance == "dark" else "moon", 16),
            compound="left", corner_radius=8)
        self.b_theme.pack(side="right")

        # 将转写和运行信息收进同一个轻量区域，保持活动记录的阅读空间。
        transcript = ctk.CTkFrame(
            panel, fg_color=design.SURFACE, height=216, corner_radius=16,
            border_width=1, border_color=design.RAIL)
        transcript.pack(fill="x", padx=32)
        transcript.pack_propagate(False)
        caption = ctk.CTkFrame(transcript, fg_color="transparent")
        caption.pack(fill="x", padx=24, pady=(18, 14))
        self._label(caption, "实时转写", 12, design.TXT2).pack(side="left")
        self._metrics = {}
        timer = self._label(caption, "00:00:00", 12, design.TXT3, family=design.FM)
        timer.pack(side="right")
        self._metrics["time"] = timer

        footer = ctk.CTkFrame(transcript, fg_color="transparent")
        footer.pack(side="bottom", fill="x", padx=24, pady=(0, 16))
        ctk.CTkFrame(footer, height=1, fg_color=design.RAIL, corner_radius=0).pack(
            fill="x", pady=(0, 12))
        code_row = ctk.CTkFrame(footer, fg_color="transparent")
        code_row.pack(fill="x")
        self._label(code_row, "签到码", 12, design.TXT3).pack(side="left", padx=(0, 14))
        code = self._label(code_row, "— — — —", 22, design.TXT3, family=design.FM, bold=True)
        code.pack(side="left")
        self._metrics["code"] = code
        self.b_copy = self._button(
            code_row, "复制", self.copy_code, width=74, height=30, font=(design.F, 11),
            image=design.ui_icon("copy", 14, design.TXT3), compound="left", state="disabled")
        self.b_copy.pack(side="right")
        self._transcript_hint = self._label(
            transcript, "选择直播课程或播放网页声音，再点击「启动监控」。", 12, design.TXT3)
        self._transcript_hint.pack(side="bottom", fill="x", padx=24, pady=(0, 16))
        self._transcript = self._label(
            transcript, "准备开始课堂监控", 22, design.TXT,
            wraplength=520, justify="left", height=60, anchor="nw")
        self._transcript.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        transcript.bind("<Configure>", lambda e: self._fit_wrap(self._transcript, e.width, 200, 52),
                        add="+")

        head = ctk.CTkFrame(panel, fg_color="transparent")
        head.pack(fill="x", padx=34, pady=(24, 10))
        self._label(head, "活动记录", 13, design.TXT2, True).pack(side="left")
        self._button(head, "清空", self.clear_log, width=42, height=28,
                     font=(design.F, 12)).pack(side="right")
        ctk.CTkCheckBox(
            head, text="自动滚动", variable=self.v_follow, width=90, height=22,
            checkbox_width=14, checkbox_height=14, corner_radius=4,
            border_width=1, border_color=design.TXT3, fg_color=design.PRIMARY,
            hover_color=design.PRIMARY_HOVER, checkmark_color=design.BUTTON_TEXT,
            text_color=design.TXT3, font=(design.F, 12)).pack(side="right", padx=(0, 8))
        self.log = ctk.CTkTextbox(
            panel, font=(design.F, 13), height=100, fg_color=design.BG,
            text_color=design.TXT2, border_width=0, corner_radius=0,
            wrap="word", spacing1=6, spacing3=6,
            scrollbar_button_color=design.BG,
            scrollbar_button_hover_color=design.INPUT_BORDER)
        self.log.pack(fill="both", expand=True, padx=28, pady=(0, 24))
        self._apply_log_colors()
        self.log.configure(state="disabled")
        self._empty_log = self._label(self.log, "监控开始后，活动记录会显示在这里", 12, design.TXT3)
        self._empty_log.place(relx=0.5, rely=0.5, anchor="center")

    # ---------- 配置与即时反馈 ----------

    def _load_fields(self):
        self.v_url.set(str(self.cfg.get("live_url", "") or ""))
        self.v_live.set(bool((self.cfg.get("live_audio") or {}).get("enabled", False)))
        self.v_user.set(self.secrets.get("skl_username", ""))
        self.v_pwd.set(self.secrets.get("skl_password", ""))
        hook = ((self.cfg.get("alert") or {}).get("webhook") or {}).get("url", "")
        self.v_hook.set(str(hook or ""))
        location = self.cfg.get("location") or {}
        self.v_lat.set(str(location.get("lat", DEFAULT_LAT)))
        self.v_lng.set(str(location.get("lng", DEFAULT_LNG)))
        self.v_auto.set(bool((self.cfg.get("auto_sign") or {}).get("enabled", True)))
        rules = self.cfg.get("rules") or {}
        self.v_sem.set(bool((rules.get("semantic") or {}).get("enabled", False)))
        self.txt_rules.insert("1.0", "\n".join(str(r) for r in rules.get("strong", [])))
        self._update_audio_mode()
        self._restore_scheduled_course()

    def _field_values(self):
        return (
            self.v_url.get(), self.v_user.get(), self.v_pwd.get(),
            self.v_hook.get(), self.v_lat.get(), self.v_lng.get(),
            self.v_auto.get(), self.v_sem.get(),
            self.txt_rules.get("1.0", "end-1c"),
            self.v_live.get(),
        )

    @staticmethod
    def _course_label(course, *, now=None):
        title = course.title
        title = title if len(title) <= 12 else title[:11] + "…"
        zone = dt.timezone(dt.timedelta(hours=8))
        course_when = dt.datetime.fromtimestamp(course.start, zone)
        current = (dt.datetime.fromtimestamp(now, zone) if now is not None
                   else dt.datetime.now(zone))
        tomorrow = current.date() + dt.timedelta(days=1)
        if course_when.date() == tomorrow:
            when = "明日 " + course_when.strftime("%H:%M")
        elif course_when.date() > tomorrow:
            when = course_when.strftime("%m-%d %H:%M")
        else:
            when = course_when.strftime("%H:%M")
        detail = course.teacher or course.classroom
        detail = detail if len(detail) <= 8 else detail[:7] + "…"
        if course_when.date() > current.date():
            return " · ".join(part for part in (when, title, detail) if part)
        suffix = " · ".join(part for part in (when, detail) if part)
        return f"{title} · {suffix}" if suffix else title

    @staticmethod
    def _scheduled_course_data(course: LiveCourse) -> dict:
        return {
            "course_id": course.course_id,
            "title": course.title,
            "start": course.start,
            "end": course.end,
            "teacher": course.teacher,
            "classroom": course.classroom,
            "section": course.section,
            "tecl_id": course.tecl_id,
            "origin": course.origin,
        }

    @staticmethod
    def _scheduled_course_from_data(value: object) -> LiveCourse | None:
        if not isinstance(value, dict):
            return None
        try:
            course = LiveCourse(
                str(value["course_id"]), str(value["title"]),
                float(value["start"]), float(value["end"]),
                str(value.get("teacher", "")), str(value.get("classroom", "")),
                str(value.get("section", "")), str(value.get("tecl_id", "")),
                str(value.get("origin", "https://course.hdu.edu.cn")),
            )
        except (KeyError, TypeError, ValueError):
            return None
        if not (math.isfinite(course.start) and math.isfinite(course.end)
                and course.end > course.start):
            return None
        return course

    def _restore_scheduled_course(self):
        stored = self.cfg.get("scheduled_course")
        course = self._scheduled_course_from_data(stored)
        now = time.time()
        if course is None or course.end <= now:
            if stored is not None:
                self.cfg.pop("scheduled_course", None)
                self._write_scheduled_course(None)
            if stored is not None:
                self._live_course_hint.configure(
                    text="已忽略无效或已结束的预约。", text_color=design.AMBER)
            return
        self._scheduled_course = course
        from echosign.live import live_course_url

        try:
            self.v_url.set(live_course_url(course))
            self.v_live.set(True)
            self._update_audio_mode()
        except Exception:
            self._scheduled_course = None
            self.cfg.pop("scheduled_course", None)
            self._write_scheduled_course(None)
            return
        self._show_scheduled_state(restored=True)

    def _set_live_course_choices(self, courses):
        self._live_courses = list(courses or [])
        self._live_course_lookup = {}
        labels = []
        for index, course in enumerate(self._live_courses):
            base = self._course_label(course)
            label = base if base not in self._live_course_lookup else f"{base} ({index + 1})"
            self._live_course_lookup[label] = course
            labels.append(label)
        if labels:
            self.live_course_picker.configure(values=labels, state="readonly")
            from echosign.live import live_course_url

            current = "请选择直播课程"
            for label, course in self._live_course_lookup.items():
                try:
                    if live_course_url(course) == self.v_url.get().strip():
                        current = label
                        break
                except Exception:
                    continue
            self.v_live_course.set(current)
            self._live_course_hint.configure(
                text=f"找到 {len(labels)} 节今明直播课，选择后启用后台音频。",
                text_color=design.TXT3)
            if self._scheduled_course is not None:
                self._show_scheduled_state(restored=True)
        else:
            text = "当前没有可选择的直播课"
            self.live_course_picker.configure(values=[text], state="disabled")
            self.v_live_course.set(text)
            self._live_course_hint.configure(
                text="今明两天没有可选择的直播课，仍可手动粘贴链接。",
                text_color=design.AMBER)
            if self._scheduled_course is not None:
                self._show_scheduled_state(restored=True)

    def _select_live_course(self, label):
        if self._task_kind or self._closing:
            return
        course = self._live_course_lookup.get(label)
        if course is None:
            return
        from echosign.live import live_course_url

        if self._scheduled_course is not None:
            self._cancel_scheduled_course(notify=False)

        self.v_live_course.set(label)
        self.v_url.set(live_course_url(course))
        self.v_live.set(True)
        self._entries["url"].invalid = False
        self._entries["url"].configure(border_color=design.INPUT_BORDER)
        zone = dt.timezone(dt.timedelta(hours=8))
        when = dt.datetime.fromtimestamp(course.start, zone).strftime("%m-%d %H:%M")
        end = dt.datetime.fromtimestamp(course.end, zone).strftime("%H:%M")
        details = " · ".join(part for part in (course.teacher, course.classroom, course.section) if part)
        action = "点击「预约监控」。" if course.start > time.time() else "点击启动监控。"
        self._live_course_hint.configure(
            text=f"{course.title}\n{when}–{end}  {details}\n已选好，{action}",
            text_color=design.GREEN)
        self._update_monitor_button()

    def _load_saved_live_courses(self):
        self._courses_job = None
        if not self._closing and self._task_kind is None and (CONFIG.parent / "live_session.json").is_file():
            self.refresh_live_courses()

    def _url_edited(self, *_):
        from echosign.live import live_course_url
        if self._scheduled_course is not None:
            try:
                scheduled_url = live_course_url(self._scheduled_course)
            except Exception:
                scheduled_url = ""
            if self.v_url.get().strip() != scheduled_url:
                self._cancel_scheduled_course(notify=True)
        selected = self._live_course_lookup.get(self.v_live_course.get())
        if selected is not None and live_course_url(selected) != self.v_url.get().strip():
            self.v_live_course.set("请选择直播课程")
            self._live_course_hint.configure(text="已改为手动地址，或重新选择列表中的课程。",
                                             text_color=design.TXT3)

    def refresh_live_courses(self):
        if self._busy():
            return
        self._live_course_hint.configure(text="正在读取直播课程…", text_color=design.TXT3)
        self._live_course_lookup = {}
        self.v_live_course.set("正在读取直播课程…")
        self.live_course_picker.configure(state="disabled")
        self.stop_event.clear()

        def run(cfg):
            from echosign.live import list_live_courses

            return list_live_courses(cfg, stop=self.stop_event)

        cfg = copy.deepcopy(self.cfg)
        cfg["live_url"] = self.v_url.get().strip()
        self._worker(run, cfg, kind="live_courses")

    @staticmethod
    def _course_time_text(course: LiveCourse, *, now=None) -> str:
        zone = dt.timezone(dt.timedelta(hours=8))
        course_when = dt.datetime.fromtimestamp(course.start, zone)
        current = (dt.datetime.fromtimestamp(now, zone) if now is not None
                   else dt.datetime.now(zone))
        if course_when.date() == current.date():
            prefix = "今天"
        elif course_when.date() == current.date() + dt.timedelta(days=1):
            prefix = "明日"
        else:
            prefix = course_when.strftime("%m-%d")
        return f"{prefix} {course_when.strftime('%H:%M')}"

    def _update_monitor_button(self):
        if not self._closing:
            self.b_monitor.configure(state="normal")
        if self._task_kind == "monitor":
            self.b_monitor.configure(
                text="停止监控", image=design.ui_icon("stop", 15, design.BUTTON_TEXT))
            return
        if self._scheduled_course is not None:
            self.b_monitor.configure(
                text="取消预约", image=design.ui_icon("clock", 15, design.BUTTON_TEXT))
            return
        selected = self._live_course_lookup.get(self.v_live_course.get())
        if selected is not None and selected.start > time.time():
            self.b_monitor.configure(
                text="预约监控", image=design.ui_icon("clock", 15, design.BUTTON_TEXT))
        else:
            self.b_monitor.configure(
                text="启动监控", image=design.ui_icon("play", 15, design.BUTTON_TEXT))

    def _write_scheduled_course(self, course: LiveCourse | None) -> bool:
        cfg = load_cfg()
        if course is None:
            cfg.pop("scheduled_course", None)
        else:
            cfg["scheduled_course"] = self._scheduled_course_data(course)
        try:
            CONFIG.write_text(
                yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8")
        except OSError as exc:
            self._feedback(f"预约保存失败：{exc.strerror or '无法写入配置文件'}", error=True)
            return False
        self.cfg = cfg
        return True

    def _show_scheduled_state(self, restored=False):
        course = self._scheduled_course
        if course is None:
            return

        when = self._course_time_text(course)
        zone = dt.timezone(dt.timedelta(hours=8))
        end = dt.datetime.fromtimestamp(course.end, zone).strftime("%H:%M")
        details = " · ".join(part for part in (course.teacher, course.classroom, course.section) if part)
        self._update_monitor_button()
        self._set_status(design.AMBER, "已预约")
        self._live_course_hint.configure(
            text=(f"{course.title}\n{when}–{end}  {details}\n"
                  "到点会自动启动监控。"),
            text_color=design.GREEN)
        self._transcript.configure(text=f"等待{when}的课程开始", text_color=design.TXT2)
        self._transcript_hint.configure(
            text=("已恢复预约，到点自动启动监控。" if restored else
                  "预约已保存；到点自动启动，点击主按钮可取消。"))
        label = next((label for label, candidate in self._live_course_lookup.items()
                      if self._urls_equal(candidate, course)), None)
        self.v_live_course.set(label or f"已预约 · {when}")
        self._update_scheduled_countdown()

    @staticmethod
    def _urls_equal(left: LiveCourse, right: LiveCourse) -> bool:
        from echosign.live import live_course_url

        try:
            return live_course_url(left) == live_course_url(right)
        except Exception:
            return False

    def _update_scheduled_countdown(self):
        if self._scheduled_course is None:
            return
        remaining = max(0, int(self._scheduled_course.start + SCHEDULE_START_DELAY - time.time()))
        days, seconds = divmod(remaining, 86400)
        clock = f"{seconds // 3600:02}:{seconds // 60 % 60:02}:{seconds % 60:02}"
        text = f"{days}天 {clock}" if days else clock
        self._metrics["time"].configure(text=text)

    def _schedule_monitor(self, course: LiveCourse) -> bool:
        if self._busy() or self._closing:
            return False
        now = time.time()
        if course.end <= now:
            self._live_course_hint.configure(
                text="这节课已经结束，无法预约。", text_color=design.AMBER)
            return False
        if course.start <= now:
            return self.start_monitor()
        self._scheduled_course = course
        if not self.save_cfg():
            self._scheduled_course = None
            self._update_monitor_button()
            return False
        self._show_scheduled_state()
        self.logline(f"[i] 已预约监控：{course.title} · {self._course_time_text(course)}")
        return True

    def _cancel_scheduled_course(self, notify=True) -> bool:
        course = self._scheduled_course
        if course is None:
            return False
        self._scheduled_course = None
        persisted = self._write_scheduled_course(None)
        self._update_monitor_button()
        if self._task_kind is None:
            self._set_status(design.TXT3, "就绪")
        if notify:
            when = self._course_time_text(course)
            self._live_course_hint.configure(
                text=f"已取消 {when} 的课程预约。", text_color=design.TXT3)
            self.logline(f"[i] 已取消监控预约：{course.title} · {when}")
        return persisted

    def _discard_scheduled_course(self, reason: str):
        course = self._scheduled_course
        if course is None:
            return
        self._scheduled_course = None
        self._write_scheduled_course(None)
        self._update_monitor_button()
        if self._task_kind is None:
            self._set_status(design.TXT3, "就绪")
        self._live_course_hint.configure(text=reason, text_color=design.AMBER)
        self.logline(f"[!] {reason}")

    def _check_scheduled_monitor(self):
        course = self._scheduled_course
        if course is None or self._closing:
            return
        now = time.time()
        if now < course.start + SCHEDULE_START_DELAY:
            self._update_scheduled_countdown()
            return
        if now >= course.end:
            self._discard_scheduled_course("预约课程已结束，未启动监控。")
            return
        if self._task_kind is not None:
            return
        self._start_scheduled_monitor()

    def _start_scheduled_monitor(self):
        course = self._scheduled_course
        if course is None:
            return False
        self._scheduled_course = None
        self._update_monitor_button()
        self.logline(
            f"[i] 预约课程到点，正在启动监控：{course.title} · {self._course_time_text(course)}")
        started = self.start_monitor()
        if not started:
            self._scheduled_course = course
            self._show_scheduled_state()
        return started

    def _update_audio_mode(self, *_):
        direct = self.v_live.get()
        if (self._scheduled_course is not None and not direct and not self._loading):
            self._cancel_scheduled_course(notify=True)
        self._field_labels["url"].configure(
            text="手动直播网址" if direct else "课程网址（选填）")
        self.b_live_login.configure(
            text="登录中…" if self._task_kind == "live_login" else "登录直播",
            state="disabled" if self._closing or self._task_kind else "normal")
        self.b_live_account.configure(
            state="disabled" if self._closing or self._task_kind else "normal")
        self.b_live_account.pack(side="right", padx=(0, 8))
        self._url_hint.configure(text=(
            "登录直播后，启动监控即可直接读取声音。" if direct
            else "已在浏览器播放课程时可留空。"))

    def _mark_dirty(self, *_):
        if not self._loading:
            dirty = self._field_values() != self._saved_values
            self._save_state.configure(
                text="有未保存的更改" if dirty else "已保存",
                text_color=design.AMBER if dirty else design.TXT3)
            self.b_save.configure(text_color=design.PRIMARY if dirty else design.TXT2)

    def _rules_changed(self, _=None):
        if self.txt_rules.edit_modified():
            self.txt_rules.edit_modified(False)
            self._mark_dirty()

    def _feedback(self, message, error=False):
        self._save_state.configure(text=message, text_color=design.RED if error else design.TXT3)
        if error:
            self.logline(f"[!] {message}")

    def _field_error(self, key, message):
        self._select_tab("extras" if key == "hook" else "basic" if key == "url" else "signin")
        if key == "url":
            self._show_manual_url()
        self._entries[key].set_error()
        self._feedback(message, error=True)
        return False

    def save_cfg(self) -> bool:
        coords = {}
        for key, var, title, limit in (
                ("lat", self.v_lat, "纬度", 90),
                ("lng", self.v_lng, "经度", 180)):
            try:
                value = float(var.get().strip())
                if not math.isfinite(value) or not -limit <= value <= limit:
                    raise ValueError
            except ValueError:
                return self._field_error(key, f"{title}须为 {-limit} 到 {limit} 的数字")
            coords[key] = value
            self._entries[key].invalid = False
            self._entries[key].configure(border_color=design.INPUT_BORDER)

        cfg = copy.deepcopy(self.cfg)
        secrets = copy.deepcopy(self.secrets)
        cfg["ui"] = {**(cfg.get("ui") or {}), "appearance": self._appearance}
        cfg["live_url"] = self.v_url.get().strip()
        cfg.setdefault("live_audio", {})["enabled"] = bool(self.v_live.get())
        if self._scheduled_course is None:
            cfg.pop("scheduled_course", None)
        else:
            cfg["scheduled_course"] = self._scheduled_course_data(self._scheduled_course)
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
        self.b_save.configure(text_color=design.TXT2)
        self._feedback("已保存 · 下次启动时生效" if self._task_kind else "设置已保存")
        return True

    def _theme_color(self, value):
        if isinstance(value, (tuple, list)):
            return value[0 if self._appearance == "light" else 1]
        return value

    def _apply_log_colors(self):
        # Tk 文本标签不接受 CTk 的双色元组，切换时同步已有日志。
        for tag, color in (("time", design.TXT3), ("info", design.TXT2), ("success", design.GREEN),
                           ("error", design.RED), ("warn", design.AMBER), ("asr", design.TXT)):
            self.log.tag_config(tag, foreground=self._theme_color(color))

    def toggle_theme(self):
        self._appearance = "light" if self._appearance == "dark" else "dark"
        ctk.set_appearance_mode(self._appearance)
        self.b_theme.configure(
            text="浅色" if self._appearance == "dark" else "深色",
            image=design.ui_icon("sun" if self._appearance == "dark" else "moon", 16))
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
        if self._closing:
            return True
        if self._task_kind is not None:
            self.logline("[!] 已有任务在运行，请等待完成或停止监控。")
            return True
        return False

    def _worker(self, fn, *args, kind="monitor"):
        if self._busy():
            return False
        self._task_kind = kind
        self.b_monitor.configure(state="disabled")
        self.b_login.configure(state="disabled")
        self.b_test.configure(state="disabled")
        self.b_locate.configure(state="disabled")
        self.b_course_refresh.configure(state="disabled")
        self.live_course_picker.configure(state="disabled")
        self._update_audio_mode()
        if kind == "monitor":
            self._t0 = time.monotonic()
            self._metrics["time"].configure(text="00:00:00")
            self._set_code(None)
            self._has_transcript = False
            self._monitor_ready = False
            self._transcript.configure(text="正在准备语音识别…", text_color=design.TXT2)
            self._transcript_hint.configure(text="初始化本地模型，请稍候。")
            self.b_monitor.configure(
                state="normal", text="停止监控",
                image=design.ui_icon("stop", 15, design.BUTTON_TEXT))
            self._set_status(design.AMBER, "正在启动")
        elif kind == "login":
            self.b_login.configure(text="登录中…")
            self._set_status(design.AMBER, "登录中")
        elif kind == "live_login":
            self._set_status(design.AMBER, "登录直播")
        elif kind == "location":
            self.b_locate.configure(text="获取中…")
            self._location_hint.configure(text="正在获取 Windows 位置…", text_color=design.TXT3)
            self._set_status(design.AMBER, "正在定位")
        elif kind == "live_courses":
            self.b_course_refresh.configure(text="读取中…")
            self._set_status(design.AMBER, "读取直播课")
        else:
            self.b_test.configure(text="发送中…")
            self._set_status(design.AMBER, "测试通知")

        def run():
            from echosign.live import LiveError
            failed = False
            result = None
            writer = QueueWriter(self.log_q)
            with redirect_stdout(writer), redirect_stderr(writer):
                try:
                    result = fn(*args)
                    failed = type(result) is int and result != 0
                except (LocationError, LiveError) as exc:
                    failed = True
                    result = exc
                    print(f"[!] {exc}")
                except SystemExit as exc:
                    failed = exc.code not in (None, 0)
                    if failed:
                        print(f"[错误] 任务退出：{exc.code}")
                except Exception as exc:  # noqa: BLE001
                    import traceback

                    failed = True
                    print(f"[错误] {exc}")
                    traceback.print_exc()
            self.task_q.put((kind, failed, result))

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        return True

    def _set_status(self, color, status):
        self._dot.configure(text_color=color)
        self._status.configure(text=status, text_color=color)

    def _finish_task(self, kind, failed, result=None):
        if self._closing:
            self._task_kind = None
            self.worker = None
            return
        if kind == "monitor":
            self._update_timer()
            if not self._has_transcript:
                self._transcript.configure(text=(
                    "监控已中断" if self._monitor_ready else "监控未能启动") if failed else "监控已结束")
            self._transcript_hint.configure(
                text="请查看下方活动记录，调整后重试。" if failed else "点击「启动监控」开始下一次课堂。")
        elif kind == "location":
            if failed:
                message = str(result) if isinstance(result, LocationError) else "获取失败，请查看活动记录或手动填写。"
                self._location_hint.configure(text=message, text_color=design.AMBER)
            elif isinstance(result, Location):
                if (self.v_lat.get(), self.v_lng.get()) != self._location_request_values:
                    self._location_hint.configure(
                        text="坐标已手动修改，已保留当前填写。", text_color=design.TXT3)
                else:
                    self.v_lat.set(f"{result.lat:.6f}")
                    self.v_lng.set(f"{result.lng:.6f}")
                    for key in ("lat", "lng"):
                        self._entries[key].invalid = False
                        self._entries[key].configure(border_color=design.INPUT_BORDER)
                    accuracy = f"，误差约 {result.accuracy_m:.0f} 米" if result.accuracy_m is not None else ""
                    self._location_hint.configure(
                        text=f"已获取{accuracy}。请核对后保存。",
                        text_color=design.AMBER if result.accuracy_m is not None and result.accuracy_m > 1000 else design.TXT3)
                    self.logline(f"[OK] 已获取 Windows 当前位置{accuracy}，请核对后保存。")
        elif kind == "live_courses":
            if failed:
                from echosign.live import LiveError
                message = str(result) if isinstance(result, LiveError) else "读取直播课程失败，请稍后重试。"
                self.v_live_course.set("未读取到课程，请登录或刷新")
                self._live_course_hint.configure(text=message, text_color=design.AMBER)
            else:
                self._set_live_course_choices(result)
        self._task_kind = None
        self._t0 = None
        self.worker = None
        self._update_monitor_button()
        self.b_login.configure(state="normal", text="登录 / 刷新")
        self.b_test.configure(state="normal", text="测试推送")
        self.b_locate.configure(state="normal", text="获取当前位置")
        self.b_course_refresh.configure(state="normal", text="刷新课程")
        self.live_course_picker.configure(state="readonly" if self._live_course_lookup else "disabled")
        self._update_audio_mode()
        if failed:
            self._set_status(design.RED, "任务异常")
        elif kind == "monitor":
            self._set_status(design.TXT3, "已停止")
            self.logline("[i] 监控已停止。")
        else:
            self._set_status(design.TXT3, "就绪")
        if self._scheduled_course is not None:
            self._set_status(design.AMBER, "已预约")
        if kind == "live_login" and not failed and result == 0:
            self.refresh_live_courses()

    def toggle_monitor(self):
        if self._task_kind == "monitor":
            self.stop_monitor()
            return
        if self._scheduled_course is not None:
            self._cancel_scheduled_course(notify=True)
            return
        selected = self._live_course_lookup.get(self.v_live_course.get())
        if selected is not None and selected.start > time.time():
            self._schedule_monitor(selected)
        else:
            self.start_monitor()

    def start_monitor(self):
        if self._busy():
            return False
        if self.v_live.get() and not self._valid_url(self.v_url.get().strip()):
            self._field_error("url", "请选择直播课程，或手动填写直播网址")
            return False
        if self.v_live.get():
            from echosign.live import LiveError, parse_live_page
            try:
                parse_live_page(self.v_url.get().strip())
            except LiveError as exc:
                self._field_error("url", str(exc))
                return False
        if self._scheduled_course is not None:
            self._cancel_scheduled_course(notify=False)
        if not self.save_cfg():
            return False
        self.stop_event.clear()
        self._active_audio_source = "live" if self.v_live.get() else "system"

        def run(cfg):
            from echosign import monitor

            if not self.stop_event.is_set():
                monitor.cmd_run(cfg, self.stop_event)

        return self._worker(run, copy.deepcopy(self.cfg), kind="monitor")

    def stop_monitor(self):
        if self._task_kind != "monitor" or self.stop_event.is_set():
            return
        self.stop_event.set()
        self.b_monitor.configure(state="disabled", text="正在停止…")
        self._set_status(design.AMBER, "正在停止")
        self.logline("[i] 正在停止监控…")

    def do_login(self):
        if self._busy() or not self.save_cfg():
            return

        def run():
            from echosign import browser

            return browser.login()

        self._worker(run, kind="login")

    def do_live_login(self, switch_account=False):
        if self._busy():
            return
        if not self.save_cfg():
            return
        self.stop_event.clear()
        from echosign.live import LiveError, parse_live_origin
        url = self.v_url.get().strip()
        try:
            parse_live_origin(url)
        except LiveError:
            url = "https://course.hdu.edu.cn/#/home"

        def run(url):
            from echosign.live import login_live

            return login_live(url, self.stop_event, switch_account=switch_account)

        self._worker(run, url, kind="live_login")

    def test_webhook(self):
        if self._busy():
            return
        if not self._valid_url(self.v_hook.get().strip()):
            self._field_error("hook", "请填写有效的企业微信 Webhook 地址")
            return
        if not self.save_cfg():
            return

        def run(cfg):
            from echosign import monitor

            monitor.cmd_webhook_test(cfg)

        self._worker(run, copy.deepcopy(self.cfg), kind="webhook")

    def locate(self):
        if self._busy():
            return
        self._location_request_values = (self.v_lat.get(), self.v_lng.get())
        self._worker(get_current_location, kind="location")

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
        self._check_scheduled_monitor()
        self._tick_job = self.after(1000, self._tick)

    # ---------- 日志和实时转写 ----------
    def _set_code(self, code):
        if self._copy_job:
            self.after_cancel(self._copy_job)
            self._copy_job = None
        self._code = code
        self._metrics["code"].configure(
            text=code or "— — — —", text_color=design.GREEN if code else design.TXT3)
        self.b_copy.configure(
            text="复制", state="normal" if code else "disabled",
            image=design.ui_icon("copy", 14, design.TXT2 if code else design.TXT3))

    def copy_code(self):
        if not self._code:
            return False
        try:
            self.clipboard_clear()
            self.clipboard_append(self._code)
        except TclError:
            self._feedback("复制失败，请重试", error=True)
            return False
        if self._copy_job:
            self.after_cancel(self._copy_job)
        self.b_copy.configure(text="已复制", image=design.ui_icon("check", 14))

        def reset_feedback():
            self._copy_job = None
            self._set_code(self._code)

        self._copy_job = self.after(1800, reset_feedback)
        return True

    def logline(self, s: str):
        self.log_q.put(s)

    def _append_log(self, line):
        self._append_logs((line,))

    def _show_log_transcript(self, text, color, hint):
        # 读取控件的当前值，启动、停止或重连后的状态也能正确覆盖。
        changes = {}
        if self._transcript.cget("text") != text:
            changes["text"] = text
        if self._transcript.cget("text_color") != color:
            changes["text_color"] = color
        if changes:
            self._transcript.configure(**changes)
        if self._transcript_hint.cget("text") != hint:
            self._transcript_hint.configure(text=hint)

    def _append_logs(self, lines):
        segments = []
        preview = None
        for line in lines:
            line = line.strip()
            if not line:
                continue
            if line.startswith("…识别中:"):
                self._has_transcript = True
                preview = (line.partition(":")[2].strip(), design.TXT2, "")
                continue  # 同一批中间结果只显示最新内容，不写入最终日志。
            if line.startswith("[ASR "):
                self._has_transcript = True
                preview = (line.partition("]")[2].strip(), design.TXT, "")
            if (code := re.search(r"签到码[:：]\s*([0-9]{4})(?!\d)", line)):
                self._set_code(code.group(1))
            if "ASR 就绪" in line and self._task_kind == "monitor" and not self.stop_event.is_set():
                self._monitor_ready = True
                self._set_status(design.GREEN, "监控中")
                if not self._has_transcript:
                    preview = ("等待课堂声音…", design.TXT2,
                               "正在接收直播音频，无需网页播放。" if self._active_audio_source == "live"
                               else "正在接收电脑播放的声音。")
            if (line.startswith("[i] 直播状态:") and self._task_kind == "monitor"
                    and not self.stop_event.is_set()):
                reconnecting = "正在重连" in line
                self._set_status(design.AMBER, "正在重连" if reconnecting else "正在连接")
                self._has_transcript = False
                preview = ("直播暂时中断，正在重新连接…" if reconnecting else "正在连接直播…",
                           design.TXT2,
                           "恢复收到声音后会继续识别。" if reconnecting else "收到直播声音后开始识别。")
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
            display_line = re.sub(r"^\[(?:ASR [^\]]+|i|OK)\]\s*", "", line)
            segments.extend((time.strftime("%H:%M:%S") + "  ", ("time",), display_line + "\n", (tag,)))
        if segments:
            self._write_log_batch(segments)
        if preview is not None:
            self._show_log_transcript(*preview)

    def _write_log_batch(self, segments):
        self.log.configure(state="normal")
        try:
            # CTk 的包装方法只接收一段文本；Tk Text 支持一次插入多段及各自标签。
            self.log._textbox.insert("end", *segments)
            excess = int(self.log.index("end-1c").split(".")[0]) - 1 - MAX_LOG_LINES
            if excess > 0:
                self.log.delete("1.0", f"{excess + 1}.0")
            if self.v_follow.get():
                self.log.yview_moveto(1.0)
        finally:
            self.log.configure(state="disabled")
        self._empty_log.place_forget()

    def clear_log(self):
        # 清空日志视图，保留本次运行时间、签到码和磁盘记录。
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")
        self._empty_log.place(relx=0.5, rely=0.5, anchor="center")

    def _poll_log(self):
        # 留出约 2 ms 一次提交文本和预览，避免逐条 Tk 重绘占满事件循环。
        deadline = time.perf_counter() + 0.008

        def pending_lines():
            for count in range(160):
                if count and time.perf_counter() >= deadline:
                    break
                try:
                    yield self.log_q.get_nowait()
                except queue.Empty:
                    break

        self._append_logs(pending_lines())
        # 完成通知入队后再检查一次日志，覆盖工作线程恰好写入最后一条的竞态。
        if self.log_q.empty():
            completion = getattr(self, "_log_completion", None)
            if completion is None:
                try:
                    completion = self.task_q.get_nowait()
                except queue.Empty:
                    pass
            self._log_completion = completion
            if completion is not None and self.log_q.empty():
                self._log_completion = None
                self._finish_task(*completion)
        # 有积压时先让出事件循环，随后尽快继续；空闲时维持低频轮询。
        self._poll_job = self.after(10 if not self.log_q.empty() else 100, self._poll_log)

    def _on_close(self):
        if self._closing:
            return
        self._closing = True
        self.stop_event.set()
        self.b_monitor.configure(state="disabled", text="正在关闭…")
        self.b_login.configure(state="disabled")
        self.b_test.configure(state="disabled")
        self.b_locate.configure(state="disabled")
        self.b_url.configure(state="disabled")
        self.b_live_account.configure(state="disabled")
        self.b_live_login.configure(state="disabled")
        self.b_course_refresh.configure(state="disabled")
        self._set_status(design.AMBER, "正在关闭")
        self._wait_for_monitor_close()

    def _wait_for_monitor_close(self):
        # Wait for attendance cleanup or the bounded system-location helper.
        # Keep Tk responsive rather than abandoning a child process on exit.
        self._close_job = None
        if self._task_kind in ("monitor", "location", "live_login", "live_courses") and self.worker and self.worker.is_alive():
            self._close_job = self.after(100, self._wait_for_monitor_close)
        else:
            self.destroy()

    def destroy(self):
        self.stop_event.set()
        for job in (self._poll_job, self._tick_job, self._copy_job, self._close_job,
                    getattr(self, "_courses_job", None)):
            if job:
                self.after_cancel(job)
        super().destroy()


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
