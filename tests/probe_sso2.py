"""Extract inline login logic from sso.hdu.edu.cn."""
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"}
for attempt in range(3):
    try:
        html = requests.get("https://sso.hdu.edu.cn/login", headers=UA, timeout=40).text
        break
    except Exception as e:  # noqa: BLE001
        print(f"重试{attempt + 1}: {e}")
        time.sleep(3)
else:
    raise SystemExit("SSO 页面获取失败")
scripts = re.findall(r"<script[^>]*>(.*?)</script>", html, re.S)
print(f"内联脚本 {len(scripts)} 段")
for i, sc in enumerate(scripts):
    if len(sc.strip()) < 10:
        continue
    print(f"\n===== 段{i} ({len(sc)} chars) =====")
    # 找登录/加密关键行
    for line in sc.splitlines():
        l = line.strip()
        if re.search(r"rsa|Rsa|encrypt|publicKey|login|password|ajax|url|post", l, re.I) and len(l) > 15:
            print("  ", l[:220])
