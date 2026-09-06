"""Maintain the application icon and lossless desktop screenshots.

The screenshots command uses isolated demo data, without login, audio or webhooks.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageGrab

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echosign import gui as ui  # noqa: E402


class DemoApp(ui.App):
    def start_monitor(self):
        if self._busy() or not self.save_cfg():
            return
        self.stop_event.clear()
        self._worker(lambda: self.stop_event.wait(), kind="monitor")
        for line in (
            "[i] ASR 就绪 · 等待课堂声音",
            "[ASR 10:00:01] 同学们，今天继续学习上一节的内容。",
            "[ASR 10:00:04] 现在开始签到，签到码是二三三零。",
            "[i] 签到提醒：检测到签到码: 2330",
        ):
            self.logline(line)
        self.logline("[i] 自动签到已关闭，请在课堂页面自行确认。")

    def do_login(self):
        self.logline("[i] 演示模式：未连接登录服务。")

    def test_webhook(self):
        self.logline("[i] 演示模式：未发送通知。")

    def open_url(self):
        self.logline("[i] 演示模式：未打开外部页面。")


def prepare_demo(directory):
    ui.CONFIG = directory / "config.yaml"
    ui.SECRETS = directory / "secrets_local.json"
    cfg = ui.yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    cfg["live_url"] = "https://live.example.com/classroom"
    cfg["alert"]["webhook"]["url"] = ""
    cfg["rules"]["semantic"]["enabled"] = False
    cfg["auto_sign"]["enabled"] = False
    cfg["location"] = {"lat": 30.0, "lng": 120.0}
    cfg["ui"] = {"appearance": "dark"}
    ui.CONFIG.write_text(ui.yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    ui.SECRETS.write_text(json.dumps({
        "skl_username": "2026001001", "skl_password": "demo-password",
    }), encoding="utf-8")


def render(app, output, scale, page):
    # Match the requested number of physical pixels, independent of Windows DPI.
    dpi = app._get_window_scaling()
    ui.ctk.set_widget_scaling(scale / dpi)
    ui.ctk.set_window_scaling(scale / dpi)
    app.maxsize(4000, 3000)
    app.geometry("1180x760+0+0")
    app.update()
    app._apply_log_colors()
    app.start_monitor()
    app.after_cancel(app._tick_job)
    app._tick_job = None
    app._select_tab(page)
    # Let Tk finish layout and the normal log queue deliver the demo events.
    deadline = time.monotonic() + 0.4
    while time.monotonic() < deadline:
        app.update()
        time.sleep(0.02)
    app._metrics["time"].configure(text="00:02:18")
    output.mkdir(parents=True, exist_ok=True)
    paths = []
    for theme in ("dark", "light"):
        if app._appearance != theme:
            app.toggle_theme()
        app.update()
        # Capture only this process's Tk client window. PrintWindow excludes the
        # desktop, title bar, pointer and automation overlays, even when occluded.
        image = ImageGrab.grab(window=app.winfo_id())
        expected = (round(1180 * scale), round(760 * scale))
        if image.size != expected:
            raise RuntimeError(f"Expected native render {expected}, received {image.size}")
        for x, color in ((0, ui.design.CARD), (image.width - 1, ui.design.BG)):
            expected_color = tuple(bytes.fromhex(app._theme_color(color).lstrip("#")))
            if image.getpixel((x, image.height - 1)) != expected_color:
                raise RuntimeError("Window is clipped by the display; retry with a smaller --scale.")
        path = output / f"{theme}.png"
        image.save(path, format="PNG", optimize=True)
        paths.append({"file": str(path), "pixels": image.size, "format": "PNG"})
    return paths


def screenshots(args):
    (ROOT / "build").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ui-demo-", dir=ROOT / "build") as temp:
        prepare_demo(Path(temp))
        app = DemoApp()
        if args.preview:
            app._select_tab(args.page)
            app.mainloop()
            if app.worker:
                app.worker.join(timeout=2)
            return
        try:
            result = render(app, args.output.resolve(), args.scale, args.page)
        finally:
            app.stop_event.set()
            if app.worker:
                app.worker.join(timeout=2)
            app.destroy()
        print(json.dumps(result, ensure_ascii=False, indent=2))



def generate_icon():
    image = Image.new("RGBA", (256, 256))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((12, 12, 244, 244), radius=56, fill="#252525")
    for index, height in enumerate((64, 128, 94, 150)):
        x = 63 + 35 * index
        draw.rounded_rectangle(
            (x, 128 - height / 2, x + 20, 128 + height / 2),
            radius=8, fill="#ffffff")
    image.save(Path(__file__).resolve().parents[1] / "assets" / "echosign.ico",
               sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("icon", help="Generate the app's waveform icon")
    shots = commands.add_parser("screenshots", help="Render the real UI with demo data")
    shots.add_argument("--preview", action="store_true")
    shots.add_argument("--output", type=Path, default=ROOT / "assets/screenshots")
    shots.add_argument("--scale", type=float, default=1.5)
    shots.add_argument("--page", choices=("basic", "rules", "extras"), default="basic")
    args = parser.parse_args()
    if args.command == "icon":
        generate_icon()
        return
    if sys.platform != "win32":
        parser.error("The screenshot exporter requires Windows.")
    if not 1 <= args.scale <= 3:
        parser.error("--scale must be between 1 and 3.")
    screenshots(args)


if __name__ == "__main__":
    main()
