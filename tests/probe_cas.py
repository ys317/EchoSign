"""Inspect HDU CAS login page structure."""
import re

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/126"}
service = "https://skl.hdu.edu.cn/api/cas/login?state=test123&index="
s = requests.Session()
r = s.get("https://cas.hdu.edu.cn/cas/login",
          params={"service": service, "state": "test123"},
          headers=UA, timeout=15)
print("HTTP", r.status_code, "| len", len(r.text))
print("最终URL:", r.url[:130])
print("标题:", re.findall(r"<title>(.*?)</title>", r.text))
print("form action:", re.findall(r'<form[^>]*action="([^"]+)"', r.text)[:2])
for m in re.findall(r"<input[^>]*>", r.text)[:12]:
    print("INPUT:", m[:160])
print("表单外隐藏字段(execution/lt):", re.findall(r'name="(execution|lt|_eventId)"[^>]*value="([^"]{0,40})', r.text))
