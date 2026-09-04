"""Full auto sign-in via real browser:
  开App页 -> 点"课堂签到" -> #/sign/in 数字键盘 -> 点码 -> 点签到 -> 抓接口结果

Usage:
  .venv\\Scripts\\python.exe -X utf8 browser_sign.py <4位码>
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

from browser_login import ROOT, _cleanup_stale_profile, load_secrets, try_sso_login

START = "https://skl.hdu.edu.cn/index.html"
# 抓包里的定位(可自行修改)
LAT, LNG = 29.219569, 119.47955


def ensure_logged_in(page, secrets: dict, timeout_s: int = 120) -> str:
    page.goto(START, wait_until="domcontentloaded", timeout=60000)
    deadline = time.time() + timeout_s
    attempted = False
    while time.time() < deadline:
        url = page.url
        if "sso.hdu.edu.cn" in url or "cas.hdu.edu.cn" in url:
            if not attempted:
                page.wait_for_timeout(1500)
                attempted = try_sso_login(page, secrets)
        else:
            token = page.evaluate("() => window.localStorage.getItem('sessionId') || ''")
            if token:
                return token
        page.wait_for_timeout(3000)
    raise RuntimeError("登录态获取失败(超时)")


def click_visible(page, selector: str, text: str | None = None, timeout_ms: int = 8000):
    """Click first visible element matching selector (and exact text if given)."""
    deadline = time.time() + timeout_ms / 1000
    while time.time() < deadline:
        for el in page.query_selector_all(selector):
            try:
                if not el.is_visible():
                    continue
                if text is not None and el.inner_text().strip() != text:
                    continue
                el.click()
                return el
            except Exception:  # noqa: BLE001
                continue
        page.wait_for_timeout(400)
    raise TimeoutError(f"找不到可点击元素: {selector} text={text!r}")


KEYPAD = "button, .van-button, [role=button]"


def sign_with_code(ctx, page, code: str) -> None:
    result: dict = {}

    def on_response(resp):
        u = resp.url
        if "captcha-verify" in u or ("sign" in u and "/api/" in u):
            try:
                result.setdefault("hits", []).append(
                    {"status": resp.status, "url": u[:120], "body": resp.text()[:400]})
            except Exception:  # noqa: BLE001
                pass

    page.on("response", on_response)

    print("[i] 打开 课堂签到 ...")
    click_visible(page, "span, button", "课堂签到", timeout_ms=15000)
    page.wait_for_url("**/sign/in**", timeout=15000)
    page.wait_for_timeout(1200)
    print("[i] 已进入签到键盘页")

    for d in code:
        click_visible(page, KEYPAD, d, timeout_ms=6000)
        page.wait_for_timeout(250)
    print(f"[i] 已输入 {code}")

    # 校验4个码格内容(读码格 div 的文本)
    boxes = [el.inner_text().strip() for el in page.query_selector_all(
        ".code-box, .digit, .van-field, input") if el.is_visible()]
    print(f"[i] 码格显示: {boxes}")

    click_visible(page, KEYPAD, "签到", timeout_ms=6000)
    print("[i] 已点击 签到, 等待接口返回...")

    for _ in range(12):
        if result.get("hits"):
            for h in result["hits"]:
                print(f"[结果] HTTP {h['status']} {h['url']}")
                print(f"[结果] {h['body']}")
            return
        page.wait_for_timeout(1000)
    print("[!] 未捕获到签到接口响应")
    page.screenshot(path=str(ROOT / "tests" / "shots" / "sign_result.png"))


def main() -> int:
    if len(sys.argv) != 2 or not (len(sys.argv[1]) == 4 and sys.argv[1].isdigit()):
        print(__doc__)
        return 2
    code = sys.argv[1]
    secrets = load_secrets()
    _cleanup_stale_profile()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(ROOT / "browser_profile"),
                                                    headless=False)
        ctx.grant_permissions(["geolocation"],
                              origin="https://skl.hdu.edu.cn")
        ctx.set_geolocation({"latitude": LAT, "longitude": LNG, "accuracy": 30})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        token = ensure_logged_in(page, secrets)
        print(f"[i] 登录态 OK ({token[:6]}...)")
        sign_with_code(ctx, page, code)
        ctx.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
