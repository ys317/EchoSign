"""Dump sign page localStorage keys related to location."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

import browser_sign as bs  # noqa: E402
from browser_login import _cleanup_stale_profile, load_secrets  # noqa: E402

_cleanup_stale_profile()
from playwright.sync_api import sync_playwright  # noqa: E402

secrets = load_secrets()
with sync_playwright() as pw:
    ctx = pw.chromium.launch_persistent_context(str(bs.ROOT / "browser_profile"), headless=False)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    bs.ensure_logged_in(page, secrets)
    click_visible = bs.click_visible
    click_visible(page, "span, button", "课堂签到", timeout_ms=15000)
    page.wait_for_url("**/sign/in**", timeout=15000)
    page.wait_for_timeout(1500)
    data = page.evaluate("() => Object.fromEntries(Object.entries(localStorage))")
    for k, v in data.items():
        if any(w in k.lower() for w in ("lat", "lng", "lon", "loc", "pos", "addr")):
            print(f"{k} = {v[:120]}")
    print("--- 全部键 ---")
    print(", ".join(data.keys()))
    ctx.close()
