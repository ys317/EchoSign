"""Shared desktop palette, typography, icons, and input controls."""
from __future__ import annotations

import math
from tkinter import font as tkfont

import customtkinter as ctk
from PIL import Image, ImageDraw

F = "Microsoft YaHei UI"
FL = "Segoe UI Semibold"
FM = "Cascadia Mono"

# (浅色, 深色)：中性侧栏、低对比边界与清晰的主操作。
# 明确选择中文无衬线字体，避免 Segoe UI 的中文回退变成细宋体。
BG = ("#f7f7f5", "#202020")
CARD = ("#eeeeeb", "#181818")
SURFACE = ("#fcfcfa", "#252525")
RAIL = ("#deded9", "#333333")
INPUT_BG = ("#f8f8f6", "#222222")
INPUT_BORDER = ("#d9d9d3", "#363636")
FOCUS = ("#858580", "#8d8d89")
TXT = ("#252523", "#efefed")
TXT2 = ("#51514d", "#c7c7c2")
TXT3 = ("#74746e", "#999994")
GREEN = ("#317450", "#97c4a4")
AMBER = ("#956824", "#d2b47b")
RED = ("#ae4650", "#dc959c")
PRIMARY = ("#252523", "#e8e8e4")
PRIMARY_HOVER = ("#41413c", "#ffffff")
BUTTON_TEXT = ("#fafaf9", "#252523")
BUTTON_DISABLED = ("#b6b6b1", "#777772")
GHOST_HOVER = ("#e5e5e1", "#30302e")
TAB_BG = ("#e3e3df", "#222222")
TAB_SELECTED = ("#fafaf8", "#353535")
SW_ON = PRIMARY
SW_OFF = ("#c7c7c2", "#484844")
KNOB_ON = BUTTON_TEXT
KNOB_OFF = ("#ffffff", "#d5d5cf")
RADIUS = 10

BTN_FONT = (F, 13, "bold")
FIELD_FONT = (FL, 14)


def configure_ui_fonts(root) -> None:
    """Prefer installed medium-weight CJK faces with explicit Windows fallbacks."""
    global F, FL, FM, BTN_FONT, FIELD_FONT
    families = set(tkfont.families(root))
    F = next((name for name in ("Noto Sans SC Medium", "Microsoft YaHei UI",
                               "Microsoft JhengHei UI") if name in families),
             "Microsoft YaHei UI")
    FL = next((name for name in ("Segoe UI Variable Text Semibold", "Segoe UI Semibold",
                                "Segoe UI") if name in families), "Segoe UI")
    FM = "Cascadia Mono" if "Cascadia Mono" in families else "Consolas"
    BTN_FONT = (F, 13, "bold")
    FIELD_FONT = (FL, 14)


def ui_icon(name, size=16, color=TXT2):
    """Draw small, theme-aware line icons at native high-DPI resolution."""
    def draw_icon(ink):
        image = Image.new("RGBA", (96, 96))
        draw = ImageDraw.Draw(image)
        if name == "sun":
            draw.ellipse((33, 33, 63, 63), outline=ink, width=7)
            for angle in range(0, 360, 45):
                a = math.radians(angle)
                draw.line([(48 + math.cos(a) * r, 48 + math.sin(a) * r)
                           for r in (32, 41)], fill=ink, width=6)
        elif name == "moon":
            draw.arc((17, 17, 79, 79), 25, 285, fill=ink, width=7)
            draw.arc((40, 1, 95, 59), 88, 188, fill=ink, width=7)
        elif name == "play":
            draw.polygon(((32, 22), (74, 48), (32, 74)), fill=ink)
        elif name == "stop":
            draw.rounded_rectangle((27, 27, 69, 69), radius=8, fill=ink)
        elif name == "copy":
            draw.rounded_rectangle((34, 33, 77, 80), radius=8, outline=ink, width=6)
            draw.line(((22, 61), (18, 61), (18, 17), (60, 17), (60, 22)),
                      fill=ink, width=6, joint="curve")
        elif name == "check":
            draw.line(((21, 49), (39, 68), (76, 29)), fill=ink, width=8, joint="curve")
        return image

    colors = color if isinstance(color, (tuple, list)) else (color, color)
    return ctk.CTkImage(light_image=draw_icon(colors[0]),
                        dark_image=draw_icon(colors[1]), size=(size, size))


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
        kw.setdefault("height", 38)
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
