"""Full auto sign-in via real browser:
  开App页 -> 点"课堂签到" -> #/sign/in 数字键盘 -> 点码 -> 点签到 -> 抓接口结果

Usage:
  python -m echosign --sign <4位码>
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
from urllib.parse import parse_qs, urlparse

import yaml
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright

from echosign.browser_login import ROOT, _cleanup_stale_profile, load_secrets, try_sso_login
from echosign.sign_result import SignResult, classify_response
from echosign.runtime import configure_browser_runtime

START = "https://skl.hdu.edu.cn/index.html"


def _location() -> tuple[float, float]:
    cfgp = ROOT / "config.yaml"
    if cfgp.exists():
        try:
            loc = (yaml.safe_load(cfgp.read_text(encoding="utf-8")) or {}).get("location") or {}
            return float(loc.get("lat", 29.219569)), float(loc.get("lng", 119.47955))
        except Exception:  # noqa: BLE001
            pass
    return 29.219569, 119.47955


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


def is_sign_response(response, code: str) -> bool:
    url = urlparse(response.url)
    return (url.scheme == "https" and url.hostname == "skl.hdu.edu.cn"
            and url.path.rstrip("/") == "/api/ali-nvc/captcha-verify"
            and response.request.method == "POST"
            and parse_qs(url.query).get("code") == [code])


def sign_with_code(ctx, page, code: str) -> SignResult:
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

    # Listen only around this submission. Earlier page loads, login, and unrelated
    # captcha responses must not become the result of the current sign-in.
    try:
        with page.expect_response(lambda response: is_sign_response(response, code),
                                  timeout=12000) as pending:
            click_visible(page, KEYPAD, "签到", timeout_ms=6000)
        response = pending.value
    except PlaywrightTimeoutError:
        return SignResult("unknown", code, "未收到本次签到响应，请到平台核对")
    try:
        payload = response.json()
    except (ValueError, PlaywrightTimeoutError):
        payload = None
    return classify_response(code, response.status, payload)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="在本人已授权的课堂中提交四位签到码")
    parser.add_argument("code")
    parser.add_argument("--result-file", type=pathlib.Path)
    args = parser.parse_args(argv)
    code = args.code
    if len(code) != 4 or not code.isascii() or not code.isdigit():
        parser.error("签到码必须是四位数字")
    try:
        configure_browser_runtime()
        secrets = load_secrets()
        _cleanup_stale_profile()
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(str(ROOT / "browser_profile"),
                                                        headless=False)
            try:
                lat, lng = _location()
                ctx.grant_permissions(["geolocation"], origin="https://skl.hdu.edu.cn")
                ctx.set_geolocation({"latitude": lat, "longitude": lng, "accuracy": 30})
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                ensure_logged_in(page, secrets)
                print("[i] 登录态已确认")
                result = sign_with_code(ctx, page, code)
            finally:
                ctx.close()
    except Exception as exc:  # A browser error cannot establish a sign-in outcome.
        result = SignResult("unknown", code, f"浏览器操作异常：{exc}")
    print(f"[结果] {result.status}: {result.message}")
    if args.result_file:
        result.write(args.result_file)
    return result.exit_code


if __name__ == "__main__":
    sys.exit(main())
