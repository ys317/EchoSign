"""One-time interactive browser login: skl.hdu.edu.cn -> CAS SSO -> persist profile.

Run: .venv\\Scripts\\python.exe -X utf8 browser_login.py
Uses secrets_local.json credentials when the SSO login form appears.
Prints localStorage sessionId (= X-Auth-Token) at the end and saves to
session_local.json. The browser profile is kept in browser_profile/ so
later sign-ins are already logged in.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

from playwright.sync_api import sync_playwright

if getattr(sys, "frozen", False):
    ROOT = pathlib.Path(sys.executable).parent  # PyInstaller: exe 所在目录
    # 冻结环境下 playwright 会误找包内 .local-browsers, 指回系统浏览器目录
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(
        pathlib.Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright")
else:
    ROOT = pathlib.Path(__file__).resolve().parent
PROFILE = ROOT / "browser_profile"
START = "https://skl.hdu.edu.cn/index.html"


def load_secrets() -> dict:
    p = ROOT / "secrets_local.json"
    if not p.exists():
        print(f"请创建 {p} 并填入 skl_username / skl_password")
        sys.exit(2)
    return json.loads(p.read_text(encoding="utf-8"))


def try_sso_login(page, secrets: dict) -> bool:
    """Heuristic CAS/SSO form fill. Returns True if a login submit was attempted."""
    user = secrets["skl_username"]
    pwd = secrets["skl_password"]

    user_selectors = ["#username", "input[name=username]", "input[name=account]",
                      "input[type=text]:not([name*=ver])", "input[placeholder*=账号]",
                      "input[placeholder*=学号]", "input[placeholder*=用户名]"]
    filled_user = None
    for sel in user_selectors:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.fill(user)
            filled_user = sel
            break
    pw_selectors = ["#password", "input[name=password]", "input[type=password]"]
    filled_pw = None
    for sel in pw_selectors:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.fill(pwd)
            filled_pw = sel
            break
    if not (filled_user and filled_pw):
        print(f"[!] 没找齐输入框 (user={filled_user}, pwd={filled_pw}), 请手动在浏览器里完成登录")
        return False

    print(f"[i] 自动填充登录表单 ({filled_user} / {filled_pw})")
    for sel in ["button:has-text('登 录')", "button:has-text('登录')", "#login_submit",
                "input[type=submit]", "button[type=submit]", ".login-btn", "#loginBtn"]:
        el = page.query_selector(sel)
        if el and el.is_visible():
            el.click()
            print(f"[i] 点击登录: {sel}")
            return True
    print("[i] 未找到登录按钮, 尝试回车提交")
    page.keyboard.press("Enter")
    return True


def _cleanup_stale_profile() -> None:
    """Kill leftover chromium instances bound to our profile dir, then remove lock."""
    import subprocess

    ps = ("Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
          "Where-Object { $_.CommandLine -like '*browser_profile*' } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }")
    subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                   capture_output=True, timeout=30)
    time.sleep(1)
    for lock in ("lockfile", "SingletonLock", "SingletonCookie", "SingletonSocket"):
        p = PROFILE / lock
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass


def main() -> int:
    secrets = load_secrets()
    _cleanup_stale_profile()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(PROFILE), headless=False)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(START, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        deadline = time.time() + 180
        login_attempted = False
        while time.time() < deadline:
            url = page.url
            if "sso.hdu.edu.cn" in url or "cas.hdu.edu.cn" in url:
                if not login_attempted:
                    page.wait_for_timeout(1500)
                    login_attempted = try_sso_login(page, secrets)
            elif "skl.hdu.edu.cn" in url:
                token = page.evaluate("() => window.localStorage.getItem('sessionId') || ''")
                if token:
                    print(f"[OK] 已登录, sessionId(X-Auth-Token) = {token[:8]}...{token[-4:]}")
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
            page.wait_for_timeout(5000)

        print("[!] 超时未确认登录态; profile 已保留, 可重跑")
        ctx.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
