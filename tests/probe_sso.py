"""Inspect sso.hdu.edu.cn login SPA: find login API + password encryption."""
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"}
s = requests.Session()
r = s.get("https://sso.hdu.edu.cn/login", headers=UA, timeout=20)
html = r.text
print("len", len(html))
print("输入框:", re.findall(r"<input[^>]*>", html)[:8])
print("script src:", re.findall(r'src="([^"]+\.js[^"]*)"', html)[:15])
print("内联脚本关键片段:")
for m in re.findall(r"(encrypt|rsa|aes|publicKey|login).{0,120}", html, re.I)[:10]:
    print("  ...", m[:150].replace("\n", " "))

assets = sorted(set(re.findall(r'(?:src|href)="([^"]+\.js[^"]*)"', html)))
for a in assets[:12]:
    url = a if a.startswith("http") else "https://sso.hdu.edu.cn" + a
    try:
        js = s.get(url, headers=UA, timeout=20).text
    except Exception as e:  # noqa: BLE001
        print(f"  {a}: 下载失败 {e}")
        continue
    hits = []
    for pat in (r".{50}(?:/login|loginUrl|auth/login).{80}", r".{40}encrypt.{100}",
                r".{40}publicKey.{100}", r".{30}password.{90}"):
        hits += [x.replace("\n", " ") for x in re.findall(pat, js, re.I)][:3]
    if hits:
        print(f"== {a} ({len(js)//1024}KB) ==")
        for h in hits[:8]:
            print("   ...", h[:190])
    time.sleep(0.3)
