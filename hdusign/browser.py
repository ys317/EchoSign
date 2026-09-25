"""Browser login and attendance workflows for HDU's 上课啦."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
import time
from urllib.parse import parse_qs, urlparse

import yaml
from playwright.sync_api import Error as PlaywrightError, TimeoutError as PlaywrightTimeoutError, sync_playwright

from hdusign.attendance import SignResult, classify_response, write_json
from hdusign.location import DEFAULT_LAT, DEFAULT_LNG
from hdusign.processes import hidden_subprocess_options
from hdusign.runtime import application_root, configure_browser_runtime

ROOT = application_root()
PROFILE = ROOT / "browser_profile"
START = "https://skl.hdu.edu.cn/index.html"


def account_profile(secrets: dict) -> Path:
    """Keep attendance sessions tied to the account entered on the home page."""
    username = str(secrets.get("skl_username", "")).strip()
    if not username:
        return PROFILE
    identity = hashlib.sha256(username.encode("utf-8")).hexdigest()
    return PROFILE / "accounts" / identity


def load_secrets() -> dict:
    p = ROOT / "secrets_local.json"
    if not p.exists():
        print(f"请创建 {p} 并填入 skl_username / skl_password")
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def try_sso_login(page, secrets: dict) -> bool:
    """Fill the HDU SSO form. Returns True if a login submit was attempted.

    The current 统一身份认证 page is an Angular form whose 登录 button stays
    disabled until both fields register input, so fields are clicked before
    filling and the button is awaited. Older CAS layouts fall back to heuristics.
    """
    user = secrets["skl_username"]
    pwd = secrets["skl_password"]

    user_selectors = ["input[name=username]", "#username", "input[name=account]",
                      "input[type=text]:not([name*=ver])", "input[placeholder*=账号]",
                      "input[placeholder*=学号]", "input[placeholder*=用户名]"]
    filled_user = None
    for sel in user_selectors:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.click()
            el.fill(user)
            filled_user = sel
            break
    pw_selectors = ["input[type=password]", "#password", "input[name=password]"]
    filled_pw = None
    for sel in pw_selectors:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.click()
            el.fill(pwd)
            filled_pw = sel
            break
    if not (filled_user and filled_pw):
        print(f"[!] 没找齐输入框 (user={filled_user}, pwd={filled_pw}), 请手动在浏览器里完成登录")
        return False

    print(f"[i] 自动填充登录表单 ({filled_user} / {filled_pw})")
    try:
        page.wait_for_function(
            "() => { const b = document.querySelector('button.login-button');"
            " return !b || (!b.disabled && !b.classList.contains('disabled')); }", timeout=8000)
    except PlaywrightTimeoutError:
        print("[!] 登录按钮未启用，请在浏览器中手动完成登录")
        return False
    for sel in ["button.login-button", "button:has-text('登 录')", "button:has-text('登录')",
                "#login_submit", "input[type=submit]", "button[type=submit]", ".login-btn", "#loginBtn"]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            try:
                el.click(timeout=5000)
            except PlaywrightTimeoutError:
                print(f"[!] 无法点击登录按钮 {sel}，请在浏览器中手动完成登录")
                return False
            print(f"[i] 点击登录: {sel}")
            return True
    print("[i] 未找到登录按钮, 尝试回车提交")
    page.keyboard.press("Enter")
    return True


CAMPUS_HOSTS = ("skl.hdu.edu.cn", "sso.hdu.edu.cn", "cas.hdu.edu.cn")


def _browser_args() -> list[str]:
    """Optional network workarounds from config.yaml `browser:`.

    ipv4_only pins campus hosts to their IPv4 addresses (some networks close
    IPv6 TLS to hdu.edu.cn); bypass_proxy ignores a system proxy such as Clash
    that breaks TLS to those hosts. Both default to off.
    """
    options = {}
    cfgp = ROOT / "config.yaml"
    if cfgp.exists():
        try:
            options = (yaml.safe_load(cfgp.read_text(encoding="utf-8")) or {}).get("browser") or {}
        except Exception:  # noqa: BLE001
            options = {}
    args: list[str] = []
    if options.get("bypass_proxy"):
        args.append("--no-proxy-server")
    if options.get("ipv4_only"):
        import socket

        rules = []
        for host in CAMPUS_HOSTS:
            try:
                addresses = sorted({a[4][0] for a in socket.getaddrinfo(host, 443, socket.AF_INET)})
            except socket.gaierror:
                continue
            if addresses:
                rules.append(f"MAP {host} {addresses[0]}")
        if rules:
            args.append("--host-resolver-rules=" + ", ".join(rules))
    return args


def _cleanup_stale_profile() -> None:
    """Kill leftover chromium instances bound to our profile dir, then remove lock."""
    import subprocess

    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*browser_profile*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-WindowStyle", "Hidden",
                    "-Command", ps],
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=30,
                   **hidden_subprocess_options())
    time.sleep(1)
    for lock in ("lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = PROFILE / lock
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def login(stop=None) -> int:
    if stop is not None and stop.is_set():
        return 0
    configure_browser_runtime()
    secrets = load_secrets()
    _cleanup_stale_profile()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(account_profile(secrets)), headless=False, args=_browser_args())
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def wait(milliseconds):
            # Keep Playwright dispatching events while allowing window close to
            # cancel manual login instead of waiting for its three-minute limit.
            remaining = milliseconds
            while remaining > 0:
                if stop is not None and stop.is_set():
                    return False
                step = min(100, remaining)
                page.wait_for_timeout(step)
                remaining -= step
            return stop is None or not stop.is_set()

        page.goto(START, wait_until="domcontentloaded", timeout=60000)
        if not wait(3000):
            ctx.close()
            return 0

        deadline = time.time() + 180
        login_attempted = False
        while time.time() < deadline:
            if stop is not None and stop.is_set():
                ctx.close()
                return 0
            url = page.url
            if "sso.hdu.edu.cn" in url or "cas.hdu.edu.cn" in url:
                if not login_attempted:
                    if not wait(1500):
                        ctx.close()
                        return 0
                    login_attempted = try_sso_login(page, secrets)
            elif "skl.hdu.edu.cn" in url:
                token = page.evaluate("() => window.localStorage.getItem('sessionId') || ''")
                if token:
                    print("[OK] 已确认登录态")
                    (ROOT / "session_local.json").write_text(
                        json.dumps({"x_auth_token": token, "captured_at": time.time()},
                                   ensure_ascii=False, indent=2), encoding="utf-8")
                    print("[i] 已保存到 session_local.json")
                    ctx.close()
                    return 0
                print(f"[i] 在 skl 页面但 localStorage 还没有 sessionId, url={url[:80]}")
            else:
                print(f"[i] 当前页面: {url[:90]}")
            print("    (180秒内自动检测, 也可手动在浏览器里完成任何操作)")
            if not wait(5000):
                ctx.close()
                return 0

        print("[!] 超时未确认登录态; profile 已保留, 可重跑")
        ctx.close()
        return 1


def _location() -> tuple[float, float]:
    cfgp = ROOT / "config.yaml"
    if cfgp.exists():
        try:
            loc = (yaml.safe_load(cfgp.read_text(encoding="utf-8")) or {}).get("location") or {}
            return float(loc.get("lat", DEFAULT_LAT)), float(loc.get("lng", DEFAULT_LNG))
        except Exception:  # noqa: BLE001
            pass
    return DEFAULT_LAT, DEFAULT_LNG


def ensure_logged_in(page, secrets: dict, timeout_s: int = 120) -> str:
    page.goto(START, wait_until="domcontentloaded", timeout=60000)
    deadline = time.monotonic() + timeout_s
    attempted = False
    while time.monotonic() < deadline:
        url = page.url
        if "sso.hdu.edu.cn" in url or "cas.hdu.edu.cn" in url:
            if not attempted:
                try:
                    page.locator("input[type=password]").first.wait_for(state="visible", timeout=5000)
                    attempted = try_sso_login(page, secrets)
                except PlaywrightTimeoutError:
                    pass
        else:
            try:
                token = page.evaluate("() => window.localStorage.getItem('sessionId') || ''")
            except PlaywrightError as exc:
                if "Execution context was destroyed" not in str(exc):
                    raise
                token = ""
            if token:
                return token
        page.wait_for_timeout(100)
    raise RuntimeError("登录态获取失败(超时)")


def click_visible(page, selector: str, text: str | None = None, timeout_ms: int = 8000):
    """Click first visible element matching selector (and exact text if given)."""
    locator = page.locator(selector)
    if text is not None:
        locator = locator.filter(has_text=re.compile(r"^\s*" + re.escape(text) + r"\s*$"))
    target = locator.filter(visible=True).first
    target.click(timeout=timeout_ms)
    return target


KEYPAD = "button, .van-button, [role=button]"


def is_sign_response(response, code: str) -> bool:
    url = urlparse(response.url)
    return (url.scheme == "https" and url.hostname == "skl.hdu.edu.cn"
            and url.path.rstrip("/") == "/api/ali-nvc/captcha-verify"
            and response.request.method == "POST"
            and parse_qs(url.query).get("code") == [code])


def open_sign_in(page) -> None:
    if not isinstance(page.url, str) or "/sign/in" not in page.url:
        print("[i] 打开 课堂签到 ...")
        click_visible(page, "span, button", "课堂签到", timeout_ms=15000)
        page.wait_for_url("**/sign/in**", timeout=15000)
    page.locator(KEYPAD).filter(has_text=re.compile(r"^\s*0\s*$")).filter(
        visible=True).first.wait_for(state="visible", timeout=15000)


def sign_with_code(ctx, page, code: str, *, on_stage=None, cancelled=None) -> SignResult:
    stage = on_stage or (lambda name, when: None)
    def check_cancelled():
        if cancelled is not None and cancelled():
            raise InterruptedError("监控已停止，未继续提交")

    check_cancelled()
    open_sign_in(page)
    stage("page_ready", time.time())
    print("[i] 已进入签到键盘页")

    for d in code:
        check_cancelled()
        click_visible(page, KEYPAD, d, timeout_ms=6000)
    stage("digits_entered", time.time())
    print(f"[i] 已输入 {code}")

    # 校验4个码格内容(读码格 div 的文本)
    boxes = [el.inner_text().strip() for el in page.query_selector_all(
        ".code-box, .digit, .van-field, input") if el.is_visible()]
    print(f"[i] 码格显示: {boxes}")

    # Listen only around this submission. Earlier page loads, login, and unrelated
    # captcha responses must not become the result of the current sign-in.
    try:
        check_cancelled()
        with page.expect_response(lambda response: is_sign_response(response, code),
                                  timeout=12000) as pending:
            click_visible(page, KEYPAD, "签到", timeout_ms=6000)
            stage("submit", time.time())
        response = pending.value
        stage("response", time.time())
    except PlaywrightTimeoutError:
        return SignResult("unknown", code, "未收到本次签到响应，请到平台核对")
    try:
        payload = response.json()
    except (ValueError, PlaywrightTimeoutError):
        payload = None
    return classify_response(code, response.status, payload)


def sign(argv=None) -> int:
    parser = argparse.ArgumentParser(description="在本人已授权的课堂中提交四位签到码")
    parser.add_argument("code")
    parser.add_argument("--result-file", type=Path)
    args = parser.parse_args(argv)
    code = args.code
    if len(code) != 4 or not code.isascii() or not code.isdigit():
        parser.error("签到码必须是四位数字")
    try:
        configure_browser_runtime()
        secrets = load_secrets()
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(str(account_profile(secrets)),
                                                        headless=False, args=_browser_args())
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


def serve_prepared(ctx, page, secrets: dict, directory: Path) -> None:
    """Read-only preparation, followed only by explicitly confirmed requests."""
    ensure_logged_in(page, secrets)
    open_sign_in(page)
    ready_at = time.time()
    write_json(directory / "ready.json", {"status": "ready", "page_ready_at": ready_at})
    last_request = 0
    while not (directory / "stop.json").exists():
        request_path = directory / f"request-{last_request + 1}.json"
        if not request_path.exists():
            time.sleep(0.05)
            continue
        request = json.loads(request_path.read_text(encoding="utf-8"))
        sequence = request.get("id")
        if type(sequence) is not int or sequence != last_request + 1:
            raise ValueError("无效的签到请求序号")
        code = request.get("code")
        if not isinstance(code, str) or len(code) != 4 or not code.isascii() or not code.isdigit():
            raise ValueError("签到码必须是四位数字")
        last_request = sequence
        if (directory / "stop.json").exists():
            return
        timings = {"detected_at": request.get("detected_at"), "prewarmed_page_ready": ready_at}
        try:
            result = sign_with_code(ctx, page, code,
                                    on_stage=lambda name, when: timings.update({name: when}),
                                    cancelled=lambda: (directory / "stop.json").exists())
        except Exception as exc:
            result = SignResult("unknown", code, f"浏览器操作异常：{exc}")
        write_json(directory / f"timing-{sequence}.json", timings)
        result.write(directory / f"result-{sequence}.json")
        if (directory / "stop.json").exists():
            return
        # Return to a fresh, empty keypad while waiting for another sign-in in
        # the same lesson. Never reuse the previous four digits or response.
        ensure_logged_in(page, secrets)
        open_sign_in(page)
        ready_at = time.time()


def sign_worker(argv=None) -> int:
    parser = argparse.ArgumentParser(description="预备签到页并等待本次监控确认的签到码")
    parser.add_argument("--exchange-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    directory = args.exchange_dir.resolve(strict=True)
    try:
        configure_browser_runtime()
        secrets = load_secrets()
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(str(account_profile(secrets)), headless=False, args=_browser_args())
            try:
                lat, lng = _location()
                ctx.grant_permissions(["geolocation"], origin="https://skl.hdu.edu.cn")
                ctx.set_geolocation({"latitude": lat, "longitude": lng, "accuracy": 30})
                page = ctx.pages[0] if ctx.pages else ctx.new_page()
                serve_prepared(ctx, page, secrets, directory)
            finally:
                ctx.close()
    except Exception as exc:
        write_json(directory / "ready.json", {"status": "error", "message": str(exc)[:240]})
        return 2
    return 0
