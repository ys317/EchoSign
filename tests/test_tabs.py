"""Settings navigation preserves edits, scrolling, and theme rendering."""
from pathlib import Path
import tempfile
import time
import unittest

from legacy_demo import DemoApp, prepare_demo, ui


class TabTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original_paths = ui.CONFIG, ui.SECRETS
        cls.temp = tempfile.TemporaryDirectory(prefix="tabs-", dir=ui.APP_ROOT / "build")
        prepare_demo(Path(cls.temp.name))
        cls.app = DemoApp()
        cls.app.attributes("-alpha", 0.0)
        cls.app.overrideredirect(True)
        cls.app.geometry("960x600")
        cls.app.update()

    @classmethod
    def tearDownClass(cls):
        for job in cls.app.tk.splitlist(cls.app.tk.call("after", "info")):
            cls.app.tk.call("after", "cancel", job)
        cls.app.destroy()
        ui.ctk.AppearanceModeTracker.update_loop_running = False
        ui.ctk.ScalingTracker.update_loop_running = False
        ui.CONFIG, ui.SECRETS = cls.original_paths
        cls.temp.cleanup()

    def settle(self):
        # CTk briefly hides the Windows root while applying a DPI change.
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.app.update()
            if self.app.winfo_viewable():
                return
            time.sleep(.01)
        self.fail("The window did not become visible after scaling")

    def test_switching_pages_keeps_unsaved_fields_and_scroll_position(self):
        app = self.app
        saved_files = ui.CONFIG.read_bytes(), ui.SECRETS.read_bytes()
        app.v_url.set("https://example.com/unsaved-class")
        app.v_hook.set("https://example.com/unsaved-notification")
        app.txt_rules.insert("end", "\n临时关键词")
        edits = app._field_values()
        app._select_tab("basic")
        self.settle()
        canvas = app._pages["basic"]._parent_canvas
        canvas.yview_moveto(.4)
        app.update_idletasks()
        scroll = canvas.yview()
        for key in ("extras", "basic") * 3:
            app._select_tab(key)
            app.update()
            self.assertTrue(app._pages[key].winfo_viewable())
            self.assertTrue(all(not page.winfo_viewable()
                                for name, page in app._pages.items() if name != key))
            self.assertEqual(app._field_values(), edits)
        app._select_tab("basic")
        self.assertAlmostEqual(canvas.yview()[0], scroll[0], places=5)
        self.assertEqual((ui.CONFIG.read_bytes(), ui.SECRETS.read_bytes()), saved_files)

    def test_selection_keeps_colors_and_fonts_after_theme_and_scale_changes(self):
        app = self.app
        original_theme = app._appearance
        original_scale = ui.ctk.ScalingTracker.widget_scaling
        try:
            for scale in (1.0, 1.2):
                ui.ctk.set_widget_scaling(scale)
                self.settle()
                self.assertEqual([key for key, page in app._pages.items() if page.winfo_viewable()],
                                 [app._active_tab])
                for theme in ("light", "dark"):
                    if app._appearance != theme:
                        app.toggle_theme()
                    for key in ("extras", "basic"):
                        app._select_tab(key)
                        app.update_idletasks()
                        for name, button in app._tabs.items():
                            selected = name == key
                            background = app._theme_color(
                                ui.design.GHOST_HOVER if selected else ui.design.CARD)
                            foreground = app._theme_color(ui.design.TXT if selected else ui.design.TXT2)
                            self.assertEqual(button._text_label.cget("background"), background)
                            self.assertEqual(button._text_label.cget("foreground"), foreground)
                            self.assertEqual(button._canvas.itemcget("inner_parts", "fill"), background)
                            requested_font = app.tk.splitlist(button._text_label.cget("font"))
                            emphasized = ("bold" in requested_font[2:] or
                                          ui.design.FH != ui.design.F and requested_font[0] == ui.design.FH)
                            self.assertEqual(emphasized, selected)
                            button._on_enter()
                            button._on_leave()
                            self.assertEqual(button._text_label.cget("background"), background)
        finally:
            ui.ctk.set_widget_scaling(original_scale)
            if app._appearance != original_theme:
                app.toggle_theme()


if __name__ == "__main__":
    unittest.main()
