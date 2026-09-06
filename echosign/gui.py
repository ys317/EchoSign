"""EchoSign desktop console.

  python -m echosign               # 图形界面
  EchoSign.exe --sign 2330         # 打包后自动签到入口（内部使用）
"""
from __future__ import annotations

import copy
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
from echosign.ui import Entry, Switch
from echosign.runtime import application_root, resource_root

APP_ROOT = application_root()

CONFIG = APP_ROOT / "config.yaml"
SECRETS = APP_ROOT / "secrets_local.json"
RESOURCE_ROOT = resource_root()

APP_VERSION = f"v{__version__}"
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
        self._code: str | None = None
        self._has_transcript = False
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
                ("basic", "课堂"), ("rules", "识别"), ("extras", "通知"))):
            tab = self._button(
                tabbar, title, lambda k=key: self._select_tab(k),
                width=0, height=32, font=(design.F, 12), corner_radius=8)
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
            page.grid(row=0, column=0, sticky="nsew")
            self._pages[key] = page
        self._basic_page(self._pages["basic"])
        self._rules_page(self._pages["rules"])
        self._extras_page(self._pages["extras"])
        self._select_tab("basic")


    def _field(self, parent, key, title, var, show="", action=None):
        box = ctk.CTkFrame(parent, fg_color="transparent")
        box.pack(fill="x", pady=(0, 16))
        caption = ctk.CTkFrame(box, fg_color="transparent", height=22)
        caption.pack(fill="x", pady=(0, 6))
        caption.pack_propagate(False)
        self._label(caption, title, 12, design.TXT2).pack(side="left")
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
        self._field(page, "url", "直播网址", self.v_url,
                    action=("打开 ↗", self.open_url))
        self._divider(page, (2, 12))
        self._field(page, "user", "学号", self.v_user)
        self.e_pwd = self._field(
            page, "pwd", "密码", self.v_pwd, show="•",
            action=("显示密码", self._toggle_password))
        self.b_pwd = self._field_actions["pwd"]
        self.b_login = self._button(
            page, "登录 / 刷新", self.do_login, height=36,
            border_color=design.INPUT_BORDER, border_width=1)
        self.b_login.pack(fill="x")
        self._divider(page, (18, 12))
        self._switch_row(
            page, "自动签到", "识别到签到码后自动提交", self.v_auto)

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
        self._divider(page, 18)
        self._label(page, "签到位置", 13, design.TXT2).pack(anchor="w", pady=(0, 8))
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
        self._label(text, title, 13, design.TXT, True).pack(anchor="w")
        description = self._label(text, desc, 11, design.TXT3, justify="left", wraplength=260)
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
                fg_color=design.TAB_SELECTED if name == key else "transparent",
                hover_color=design.TAB_SELECTED if name == key else design.GHOST_HOVER,
                text_color=design.TXT if name == key else design.TXT2,
                font=(design.F, 12, "bold") if name == key else (design.F, 12))


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
            transcript, "播放课程声音后，点击左侧「启动监控」。", 12, design.TXT3)
        self._transcript_hint.pack(side="bottom", fill="x", padx=24, pady=(0, 16))
        self._transcript = self._label(
            transcript, "准备开始课堂监控", 22, design.TXT,
            wraplength=520, justify="left", height=60, anchor="nw")
        self._transcript.pack(fill="both", expand=True, padx=24, pady=(0, 8))
        transcript.bind("<Configure>", lambda e: self._transcript.configure(
            wraplength=max(200, int(e.width / self._transcript._get_widget_scaling()) - 52)),
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
            self._entries[key].configure(border_color=design.INPUT_BORDER)

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
        if kind == "monitor":
            self._t0 = time.monotonic()
            self._metrics["time"].configure(text="00:00:00")
            self._set_code(None)
            self._has_transcript = False
            self._transcript.configure(text="正在准备语音识别…", text_color=design.TXT2)
            self._transcript_hint.configure(text="初始化本地模型，请稍候。")
            self.b_monitor.configure(
                state="normal", text="停止监控",
                image=design.ui_icon("stop", 15, design.BUTTON_TEXT))
            self._set_status(design.AMBER, "正在启动")
        elif kind == "login":
            self.b_login.configure(text="登录中…")
            self._set_status(design.AMBER, "登录中")
        else:
            self.b_test.configure(text="发送中…")
            self._set_status(design.AMBER, "测试通知")

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
            if not self._has_transcript:
                self._transcript.configure(text="监控未能启动" if failed else "监控已结束")
            self._transcript_hint.configure(
                text="请查看下方活动记录，调整后重试。" if failed else "点击「启动监控」开始下一次课堂。")
        self._task_kind = None
        self._t0 = None
        self.worker = None
        self.b_monitor.configure(
            state="normal", text="启动监控",
            image=design.ui_icon("play", 15, design.BUTTON_TEXT))
        self.b_login.configure(state="normal", text="登录 / 刷新")
        self.b_test.configure(state="normal", text="测试推送")
        if failed:
            self._set_status(design.RED, "任务异常")
        elif kind == "monitor":
            self._set_status(design.TXT3, "已停止")
            self.logline("[i] 监控已停止。")
        else:
            self._set_status(design.TXT3, "就绪")

    def toggle_monitor(self):
        if self._task_kind == "monitor":
            self.stop_monitor()
        else:
            self.start_monitor()

    def start_monitor(self):
        if self._busy() or not self.save_cfg():
            return
        self.stop_event.clear()

        def run(cfg):
            from echosign import monitor

            if not self.stop_event.is_set():
                monitor.cmd_run(cfg, self.stop_event)

        self._worker(run, copy.deepcopy(self.cfg), kind="monitor")

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
        line = line.strip()
        if not line:
            return
        if line.startswith("…识别中:"):
            self._has_transcript = True
            self._transcript_hint.configure(text="")
            self._transcript.configure(text=line.partition(":")[2].strip(), text_color=design.TXT2)
            return  # 中间识别结果只更新预览，不淹没最终日志。
        if line.startswith("[ASR "):
            self._has_transcript = True
            self._transcript_hint.configure(text="")
            self._transcript.configure(text=line.partition("]")[2].strip(), text_color=design.TXT)
        if (code := re.search(r"签到码[:：]\s*([0-9]{4})(?!\d)", line)):
            self._set_code(code.group(1))
        if "ASR 就绪" in line and self._task_kind == "monitor" and not self.stop_event.is_set():
            self._set_status(design.GREEN, "监控中")
            if not self._has_transcript:
                self._transcript.configure(text="等待课堂声音…", text_color=design.TXT2)
                self._transcript_hint.configure(text="正在接收电脑播放的声音。")
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
        self.log.configure(state="normal")
        self.log.insert("end", time.strftime("%H:%M:%S") + "  ", ("time",))
        self.log.insert("end", display_line + "\n", (tag,))
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
        for job in (self._poll_job, self._tick_job, self._copy_job):
            if job:
                self.after_cancel(job)
        super().destroy()


def main() -> int:
    App().mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
