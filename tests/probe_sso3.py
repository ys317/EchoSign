"""Fetch SSO frontend JS (deploy.js / loginNew.js) and locate login API + RSA key."""
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"}
html = requests.get("https://sso.hdu.edu.cn/login", headers=UA, timeout=40).text
m = re.search(r'id="frontend-addr"[^>]*>([^<]+)<', html)
addr = m.group(1).strip() if m else ""
print("frontend-addr:", addr)
if not addr.startswith("http"):
    addr = "https://sso.hdu.edu.cn" + addr

for name in ("utils/loginNew.js", "deploy/deploy.js"):
    url = f"{addr}/{name}"
    try:
        js = requests.get(url, headers=UA, timeout=40).text
    except Exception as e:  # noqa: BLE001
        print(f"{name}: 失败 {e}")
        continue
    print(f"\n== {name} ({len(js)//1024}KB) ==")
    pats = {
        "login提交": r".{60}(?:login|Login).{0,20}(?:url|Url|post|POST).{100}",
        "加密": r".{60}(?:encrypt|Encrypt|RSA|rsa).{110}",
        "公钥": r".{0,60}(?:BEGIN|MIGf|MA0G|publicKey|PublicKey).{130}",
        "密码字段": r".{50}password.{100}",
        "验证码": r".{40}(?:captcha|Captcha|verifycode|kaptcha).{80}",
    }
    seen = set()
    for label, pat in pats.items():
        hits = [x.replace("\n", " ") for x in re.findall(pat, js)][:4]
        for h in hits:
            k = h[:80]
            if k in seen:
                continue
            seen.add(k)
            print(f"  [{label}] ...{h[:210]}")
