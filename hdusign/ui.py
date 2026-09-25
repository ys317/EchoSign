"""Shared desktop palette, typography, icons, and input controls."""
from __future__ import annotations

import math
from tkinter import Canvas, font as tkfont

import customtkinter as ctk
from PIL import Image, ImageDraw

F = "Microsoft YaHei UI"
FH = F
FL = "Segoe UI Semibold"
FM = "Cascadia Mono"

# (浅色, 深色)：Notion tokens。Tk 不支持 alpha 颜色；muted、border 和
# hover 分别使用 #37352F 以 65%、9%、6% 不透明度合成到白底后的颜色。
BG = ("#ffffff", "#191919")
CARD = ("#f7f6f5", "#202020")
SURFACE = ("#ffffff", "#252525")
INSET = ("#f1f1ef", "#252525")
RAIL = ("#ededec", "#2f2f2f")
INPUT_BG = ("#ffffff", "#252525")
INPUT_BORDER = ("#e0e0de", "#3a3a3a")
FOCUS = ("#7a93ad", "#8ba3bd")
TXT = ("#37352f", "#e6e6e5")
TXT2 = ("#7d7c78", "#9b9b98")
TXT3 = ("#9b9a97", "#6f6f6c")
ACCENT = ("#7a93ad", "#8ba3bd")
ACCENT_HOVER = ("#6a839d", "#9bb3cd")
ACCENT_SOFT = ("#eef2f5", "#2e3a46")
ACCENT_TEXT = ("#6a839d", "#9bb3cd")
AMBER = ("#a1740f", "#d9ad4f")
RED = ("#eb5757", "#f26d6d")
RED_HOVER = ("#d64545", "#ff8585")
RED_SOFT = ("#ffeceb", "#352727")
# Tk 不支持半透明边框；浅色值为 20% #EB5757 叠加在侧栏上的结果。
RED_BORDER = ("#f5d6d5", "#493030")
GREEN = ("#1c3829", "#a9c8b4")
GREEN_SOFT = ("#dbeddb", "#253329")
AMBER_SOFT = ("#fbf3db", "#3a2f14")
CALLOUT = ("#fbf3db", "#232323")
CALLOUT_TEXT = ("#8f6b00", "#b3b1a9")
PRIMARY = ("#37352f", "#e6e6e4")
PRIMARY_HOVER = ("#55534c", "#ffffff")
BUTTON_TEXT = ("#ffffff", "#191919")
BUTTON_DISABLED = ("#b9b7b2", "#555550")
GHOST_HOVER = ("#f3f3f3", "#2f2f2f")
SELECTION = ("#eae9e7", "#2f2f2f")
SW_ON = PRIMARY
SW_OFF = ("#e0e0de", "#3a3a3a")
KNOB_ON = ("#ffffff", "#191919")
KNOB_OFF = ("#ffffff", "#d4d4d2")
RADIUS = 4

# 监控中状态点的呼吸暗色。
PULSE_ACCENT = ("#a8b8c8", "#6b7f94")

BTN_FONT = (F, 13, "bold")
FIELD_FONT = (FL, 14)


def configure_ui_fonts(root) -> None:
    """Keep native Segoe UI for Latin text and an explicit sans-serif CJK face.

    Tk's Segoe UI fallback can resolve Chinese glyphs to serif SimSun, so choose
    Microsoft YaHei UI explicitly for mixed Chinese labels.
    """
    global F, FH, FL, FM, BTN_FONT, FIELD_FONT
    families = set(tkfont.families(root))
    F = next((name for name in ("Microsoft YaHei UI", "Noto Sans SC",
                               "Microsoft JhengHei UI") if name in families),
             "Microsoft YaHei UI")
    FH = "Noto Sans SC Medium" if "Noto Sans SC Medium" in families else F
    FL = next((name for name in ("Segoe UI Variable Text", "Segoe UI",
                                "Segoe UI") if name in families), "Segoe UI")
    FM = "Cascadia Mono" if "Cascadia Mono" in families else "Consolas"
    BTN_FONT = (F, 13)
    FIELD_FONT = (FL, 14)
    # 小圆角使用轻量路径绘制，避免每个圆角由多个字体图元拼接。
    ctk.DrawEngine.preferred_drawing_method = "polygon_shapes"


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
        elif name == "clock":
            draw.ellipse((18, 18, 78, 78), outline=ink, width=7)
            draw.line(((48, 29), (48, 52)), fill=ink, width=7)
            draw.line(((48, 52), (67, 63)), fill=ink, width=7)
        elif name == "status":
            draw.ellipse((18, 18, 78, 78), outline=ink, width=6)
            draw.ellipse((37, 37, 59, 59), fill=ink)
        elif name == "copy":
            draw.rounded_rectangle((34, 33, 77, 80), radius=8, outline=ink, width=6)
            draw.line(((22, 61), (18, 61), (18, 17), (60, 17), (60, 22)),
                      fill=ink, width=6, joint="curve")
        elif name == "check":
            draw.line(((21, 49), (39, 68), (76, 29)), fill=ink, width=8, joint="curve")
        elif name == "chevron":
            draw.line(((28, 39), (48, 59), (68, 39)), fill=ink, width=8, joint="curve")
        elif name == "camera":
            draw.rounded_rectangle((14, 30, 66, 74), radius=10, outline=ink, width=6)
            draw.polygon(((66, 44), (86, 32), (86, 72), (66, 60)), outline=ink, width=6)
            draw.ellipse((31, 45, 49, 63), outline=ink, width=5)
        elif name == "sliders":
            for y, x in ((28, 58), (48, 38), (68, 62)):
                draw.line(((18, y), (78, y)), fill=ink, width=6)
                draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=ink)
        elif name == "collapse":
            draw.line(((58, 20), (30, 48), (58, 76)), fill=ink, width=7, joint="curve")
        elif name == "expand":
            draw.line(((38, 20), (66, 48), (38, 76)), fill=ink, width=7, joint="curve")
        elif name == "triangle-right":
            draw.polygon(((35, 23), (69, 48), (35, 73)), fill=ink)
        elif name == "triangle-down":
            draw.polygon(((23, 35), (73, 35), (48, 69)), fill=ink)
        elif name == "focus":
            for points in (((34, 18), (18, 18), (18, 34)),
                           ((62, 18), (78, 18), (78, 34)),
                           ((18, 62), (18, 78), (34, 78)),
                           ((78, 62), (78, 78), (62, 78))):
                draw.line(points, fill=ink, width=6, joint="curve")
        elif name == "history":
            draw.arc((22, 18, 80, 78), 215, 525, fill=ink, width=6)
            draw.line(((16, 19), (16, 39), (36, 39)), fill=ink, width=6)
            draw.line(((50, 32), (50, 50), (63, 57)), fill=ink, width=6)
        elif name == "more":
            for x in (24, 48, 72):
                draw.ellipse((x - 5, 43, x + 5, 53), fill=ink)
        elif name == "radar":
            draw.ellipse((16, 16, 80, 80), outline=ink, width=4)
            draw.arc((29, 29, 67, 67), 5, 295, fill=ink, width=4)
            draw.line(((48, 48), (72, 22)), fill=ink, width=5)
            draw.ellipse((43, 43, 53, 53), fill=ink)
            draw.ellipse((24, 54, 33, 63), fill=ink)
        elif name == "key":
            draw.ellipse((16, 15, 53, 52), outline=ink, width=5)
            draw.line(((47, 47), (78, 78), (84, 72)), fill=ink, width=5, joint="curve")
            draw.line(((65, 65), (72, 58)), fill=ink, width=5)
        return image

    colors = color if isinstance(color, (tuple, list)) else (color, color)
    return ctk.CTkImage(light_image=draw_icon(colors[0]),
                        dark_image=draw_icon(colors[1]), size=(size, size))


class Scrollbar(ctk.CTkScrollbar):
    """CTk 6 滚动条外观；绘制留给事件循环，不在绘制中再次强制布局。"""

    def _draw(self, no_color_updates=False):
        start, end = self._get_scrollbar_values_for_minimum_pixel_size()
        recolor = self._draw_engine.draw_rounded_scrollbar(
            self._apply_widget_scaling(self._current_width),
            self._apply_widget_scaling(self._current_height),
            self._apply_widget_scaling(self._corner_radius),
            self._apply_widget_scaling(self._border_spacing), start, end, self._orientation)
        if not no_color_updates or recolor:
            ink = self._apply_appearance_mode(
                self._button_hover_color if self._hover_state else self._button_color)
            background = self._apply_appearance_mode(
                self._bg_color if self._fg_color == "transparent" else self._fg_color)
            self._canvas.itemconfig("scrollbar_parts", fill=ink, outline=ink)
            self._canvas.configure(bg=background)
            self._canvas.itemconfig("border_parts", fill=background, outline=background)

    def set(self, start, end):
        if (float(start), float(end)) != (self._start_value, self._end_value):
            super().set(start, end)


def _replace_scrollbar(old, command):
    bar = Scrollbar(old.master, command=command,
                    orientation=old.cget("orientation"),
                    fg_color=old.cget("fg_color"),
                    button_color=old.cget("button_color"),
                    button_hover_color=old.cget("button_hover_color"),
                    corner_radius=4)
    old.destroy()
    return bar


class ScrollableFrame(ctk.CTkScrollableFrame):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        vertical = self._orientation == "vertical"
        self._scrollbar = _replace_scrollbar(self._scrollbar,
            self._parent_canvas.yview if vertical else self._parent_canvas.xview)
        self._parent_canvas.configure(**{
            "yscrollcommand" if vertical else "xscrollcommand": self._scrollbar.set})
        self._create_grid()


class Textbox(ctk.CTkTextbox):
    def __init__(self, *args, **kw):
        super().__init__(*args, **kw)
        self._x_scrollbar = _replace_scrollbar(self._x_scrollbar, self._textbox.xview)
        self._y_scrollbar = _replace_scrollbar(self._y_scrollbar, self._textbox.yview)
        self._textbox.configure(xscrollcommand=self._x_scrollbar.set,
                                yscrollcommand=self._y_scrollbar.set)
        self._create_grid_for_text_and_scrollbars(re_grid_x_scrollbar=True, re_grid_y_scrollbar=True)


class QuoteText(Textbox):
    """可选择复制的只读引用文本，按实际换行自适应高度与 1.6 行高。"""

    def __init__(self, master, text, **kw):
        self._quote_text = text
        self._wraplength = 520
        self._resize_job = None
        self._fit_key = None
        self._metrics_key = None
        super().__init__(master, font=(F, 17), height=28, fg_color=BG,
                         border_width=0, border_spacing=0, corner_radius=0,
                         wrap="word", activate_scrollbars=False, **kw)
        # 自动高度引用没有内部滚动条。解除隐藏滚动条回调，避免它们在
        # 每次插入/缩放时重绘并递归调用 update_idletasks。
        self._textbox.configure(padx=0, pady=0, xscrollcommand="", yscrollcommand="")
        self.insert("1.0", text)
        super().configure(state="disabled")
        self.bind("<Configure>", self._schedule_fit, add="+")

    def configure(self, require_redraw=False, **kw):
        resized = "font" in kw
        if "text" in kw:
            text = kw.pop("text")
            if text != self._quote_text:
                self._quote_text = text
                super().configure(state="normal")
                self._textbox.delete("1.0", "end")
                self._textbox.insert("1.0", text)
                super().configure(state="disabled")
                resized = True
        if "wraplength" in kw:
            self._wraplength = kw.pop("wraplength")
        super().configure(require_redraw=require_redraw, **kw)
        if resized:
            self._schedule_fit()

    def _check_if_scrollbars_needed(self, event=None, continue_loop=False):
        # 整个页面负责滚动，不启动 CTkTextbox 的滚动条轮询。
        return

    def cget(self, attribute):
        if attribute == "text":
            return self._quote_text
        if attribute == "wraplength":
            return self._wraplength
        return super().cget(attribute)

    def _schedule_fit(self, _=None):
        if self._resize_job is None:
            self._resize_job = self.after_idle(self._fit_height)

    def _fit_height(self):
        self._resize_job = None
        scale = self._get_widget_scaling()
        font_key = (str(self._textbox.cget("font")), scale)
        key = (self._textbox.winfo_width(), font_key, self._quote_text)
        if key == self._fit_key:
            return
        self._fit_key = key
        if font_key != self._metrics_key:
            self._metrics_key = font_key
            font = tkfont.Font(font=font_key[0])
            self._line_height = max(font.metrics("linespace"), round(17 * 1.6 * scale))
            extra = self._line_height - font.metrics("linespace")
            self._textbox.configure(spacing1=extra // 2, spacing2=extra,
                                    spacing3=extra - extra // 2)
        count = self._textbox.count("1.0", "end", "displaylines")
        height = max(1, count[0] if count else 1) * self._line_height / scale
        if abs(self.cget("height") - height) > 0.5:
            super().configure(height=height)

    def destroy(self):
        if self._resize_job is not None:
            self.after_cancel(self._resize_job)
        super().destroy()


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


class NotionMenu(ctk.CTkToplevel):
    """轻量 Notion 式弹出菜单：小圆角卡片，细边框，行悬停换底色。"""

    def __init__(self, master, items, width=200):
        super().__init__(master)
        self.withdraw()
        self.overrideredirect(True)
        self.configure(fg_color="transparent")
        self._items = list(items)
        card = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=5,
                            border_color=RAIL, border_width=1)
        card.pack(fill="both", expand=True)
        self._buttons = []
        for item in self._items:
            if item == "-":
                ctk.CTkFrame(card, height=1, fg_color=RAIL,
                             corner_radius=0).pack(fill="x", padx=8, pady=4)
                continue
            label, command = item
            button = ctk.CTkButton(
                card, text=label, command=lambda c=command: self._pick(c),
                height=30, anchor="w", corner_radius=5, font=(F, 12),
                fg_color="transparent", hover_color=GHOST_HOVER, text_color=TXT)
            button.pack(fill="x", padx=4, pady=(4, 0))
            self._buttons.append(button)
        if self._buttons:
            self._buttons[-1].pack_configure(pady=(4, 4))
        self.bind("<FocusOut>", lambda _: self._close())
        self.bind("<Escape>", lambda _: self._close())

    def _pick(self, command):
        self._close()
        if command:
            command()

    def _close(self):
        if self.winfo_exists():
            self.destroy()

    def open_for(self, anchor):
        self.update_idletasks()
        x = anchor.winfo_rootx()
        y = anchor.winfo_rooty() + anchor.winfo_height() + 4
        x = max(0, min(x, self.winfo_screenwidth() - self.winfo_reqwidth() - 12))
        self.geometry(f"+{x}+{y}")
        self.deiconify()
        self.lift()
        self.focus_force()

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
