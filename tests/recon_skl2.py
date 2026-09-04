"""Download key JS chunks and extract api endpoints + auth flow."""
import re
import time

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
FILES = ["/assets/login-CKREth_3.js", "/assets/useAuthSession-IiIFQN9q.js",
         "/assets/index-DM3OAXGa.js", "/assets/index-DRsklI0E.js"]

apis = set()
for f in FILES:
    js = None
    for attempt in range(3):
        try:
            js = requests.get("https://skl.hdu.edu.cn" + f, headers=UA, timeout=30).text
            break
        except Exception as e:  # noqa: BLE001
            print(f"  {f} 重试{attempt + 1}: {e}")
            time.sleep(2)
    if not js:
        continue
    apis |= set(re.findall(r'["\'](/api/[a-zA-Z0-9/_\-\.]+)["\']', js))
    print(f"== {f} ({len(js) // 1024}KB) ==")
    # 登录流程线索
    for pat in (r'.{80}[Aa]uth-[Tt]oken.{80}', r'.{60}skl-ticket.{80}', r'.{50}dingtalk.{100}',
                r'.{60}(?:password|passwd).{80}', r'.{40}/api/(?:login|auth|sso)[^"\']{0,40}.'):
        for m in list(re.findall(pat, js))[:4]:
            print("  ...", m.replace("\n", " ")[:200])
    print()

print("== 全部 /api/ 端点 ==")
for a in sorted(apis):
    print(" ", a)
