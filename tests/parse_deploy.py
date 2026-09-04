import re

js = open(r"C:\Users\35285\AppData\Local\Temp\skl_recon\deploy.js",
          encoding="utf-8", errors="ignore").read()
print("len", len(js))
print("== script src ==")
for x in sorted(set(re.findall(r"""src\s*[:=]\s*["']([^"']{4,120})""", js)))[:20]:
    print(" ", x)
print("== urls ==")
for x in sorted(set(re.findall(r"""https?://[^"'\s]{5,80}""", js)))[:15]:
    print(" ", x)
print("== casPageInit context ==")
for x in re.findall(r""".{60}casPageInit.{140}""", js)[:4]:
    print(" ", x.replace("\n", " ")[:220])
print("== js/css chunks ==")
for x in sorted(set(re.findall(r"""["']([^"']*\.js[^"']*)["']""", js)))[:25]:
    print(" ", x)
print("== login/encrypt keywords ==")
for x in list(re.findall(r""".{50}(?:encrypt|publicKey|BEGIN PUBLIC).{110}""", js, re.I))[:6]:
    print(" ", x.replace("\n", " ")[:200])
