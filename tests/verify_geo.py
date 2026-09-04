"""Verify: does the captcha-verify request carry the config lat/lng? (fake code, harmless)"""
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from urllib.parse import parse_qs, urlparse  # noqa: E402

import browser_sign as bs  # noqa: E402
from browser_login import _cleanup_stale_profile, load_secrets  # noqa: E402

captured = []


def main() -> int:
    _cleanup_stale_profile()
    from playwright.sync_api import sync_playwright

    secrets = load_secrets()
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(str(bs.ROOT / "browser_profile"),
                                                    headless=False)
        lat, lng = bs._location()
        print(f"[config 定位] lat={lat} lng={lng}")
        ctx.grant_permissions(["geolocation"], origin="https://skl.hdu.edu.cn")
        ctx.set_geolocation({"latitude": lat, "longitude": lng, "accuracy": 30})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_resp(r):
            if "captcha-verify" in r.url:
                q = parse_qs(urlparse(r.url).query)
                captured.append((q.get("latitude"), q.get("longitude"), r.text()[:80]))

        page.on("response", on_resp)
        bs.ensure_logged_in(page, secrets)
        bs.sign_with_code(ctx, page, "0000")
        ctx.close()

    print("\n== 提交给服务器的坐标 ==")
    ok = False
    for la, ln, body in captured:
        print(f"latitude={la and la[0]} longitude={ln and ln[0]}")
        print(f"  返回: {body}")
        if la and la[0] == str(lat) and ln and ln[0] == str(lng):
            ok = True
    print("PASS: 服务器收到的就是 config 里设的坐标" if ok else "FAIL: 坐标不一致或未捕获")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
