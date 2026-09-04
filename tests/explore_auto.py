"""Autonomous exploration: find and click 课堂签到, dump DOM + API calls."""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from browser_login import ROOT, _cleanup_stale_profile  # noqa: E402

SHOTS = ROOT / "tests" / "shots"
SHOTS.mkdir(parents=True, exist_ok=True)

api_log = []


def main() -> int:
    _cleanup_stale_profile()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(ROOT / "browser_profile"), headless=True)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.on("response", lambda r: api_log.append((r.status, r.url))
                if "/api/" in r.url else None)

        page.goto("https://skl.hdu.edu.cn/index.html", wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(5000)
        print("URL:", page.url)
        token = page.evaluate("() => window.localStorage.getItem('sessionId') || ''")
        print("sessionId:", (token[:6] + "...") if token else "(无!)")

        page.screenshot(path=str(SHOTS / "01_index.png"))
        # 找含"签到"的可点元素
        els = page.query_selector_all("text=课堂签到") + page.query_selector_all("text=签到")
        print(f"含'签到'元素: {len(els)} 个")
        for i, el in enumerate(els[:10]):
            try:
                print(f"  [{i}] <{el.evaluate('e=>e.tagName')}> visible={el.is_visible()} "
                      f"text={el.inner_text()[:30]!r}")
            except Exception:  # noqa: BLE001
                pass

        vis = [el for el in els if el.is_visible()]
        if vis:
            print("\n== 点击第一个可见的签到元素 ==")
            vis[0].click()
            page.wait_for_timeout(5000)
            print("点击后 URL:", page.url)
            page.screenshot(path=str(SHOTS / "02_after_click.png"))
            # 弹窗/新页面上的按钮与输入框
            print("\n== 可见按钮 ==")
            for b in page.query_selector_all("button, .van-button, [role=button]"):
                try:
                    if b.is_visible():
                        print("  ", repr(b.inner_text().strip()[:24]))
                except Exception:  # noqa: BLE001
                    pass
            print("\n== 可见输入框 ==")
            for inp in page.query_selector_all("input, textarea"):
                try:
                    if inp.is_visible():
                        print(f"   <{inp.evaluate('e=>e.tagName')} type={inp.evaluate('e=>e.type')}> "
                              f"placeholder={inp.evaluate('e=>e.placeholder')!r}")
                except Exception:  # noqa: BLE001
                    pass
        else:
            print("没有可见的签到元素, 截图看看首页结构")

        print("\n== 期间产生的 /api/ 调用 ==")
        seen = set()
        for s, u in api_log[-40:]:
            k = u.split("?")[0]
            if k not in seen:
                seen.add(k)
                print(f"  {s} {k[:100]}")
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
