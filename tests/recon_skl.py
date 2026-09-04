"""Recon skl.hdu.edu.cn SPA: find auth/login endpoints in frontend assets."""
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

html = requests.get("https://skl.hdu.edu.cn/index.html", headers=UA, timeout=10).text
assets = re.findall(r'src="(/assets/[^"]+\.js)"', html) + re.findall(r'href="(/assets/[^"]+\.js)"', html)
print("JS 资产:", assets)

found = set()
for a in set(assets):
    try:
        js = requests.get("https://skl.hdu.edu.cn" + a, headers=UA, timeout=15).text
    except Exception as e:  # noqa: BLE001
        print(f"  {a} 下载失败: {e}")
        continue
    # api 路径
    for m in re.findall(r'["\'](/api/[a-zA-Z0-9/_\-\.]+)["\']', js):
        found.add(m)
    # 登录/鉴权相关关键词上下文
    for kw in ("login", "Login", "auth", "Auth", "sso", "cas", "ticket", "qrcode"):
        for m in re.findall(r'["\']([^"\']{0,60}' + kw + r'[^"\']{0,60})["\']', js):
            if "/" in m or "http" in m:
                found.add("KW:" + m.strip()[:100])

print("\n== /api/ 端点 ==")
for f in sorted(x for x in found if not x.startswith("KW:")):
    print(" ", f)
print("\n== 登录相关字符串 ==")
for f in sorted(x for x in found if x.startswith("KW:"))[:40]:
    print(" ", f[3:])
