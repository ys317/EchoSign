"""Live sign-in attempt: python sign.py <4位码>

真码有效期窗口内立刻运行, 判定服务端是否强校验阿里验证码:
  - 签到成功            -> 验证码不强制, 纯Python全自动可行
  - 签到码不存在        -> 码错/过期
  - 验证码/参数类错误    -> 服务端强校验, 需转 Playwright 真浏览器方案
WAF 会随机返回 200 空响应, 自动重试多次。
"""
import json
import sys
import time
from pathlib import Path

import requests

USERID = "24270108"
LAT, LNG = 29.219569, 119.47955


def _load_token() -> str:
    p = Path(__file__).resolve().parent / "session_local.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8")).get("x_auth_token", "")
    return ""


TOKEN = _load_token()

HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "X-Auth-Token": TOKEN,
    "Content-Type": "application/x-www-form-urlencoded",
    "User-Agent": "Mozilla/5.0 (Linux; U; Android 16; zh-CN; 23127PN0CC Build/BP2A.250605.031.A3) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/100.0.4896.58 UWS/5.12.14.0 Mobile Safari/537.36 AliApp(DingTalk/8.1.11) com.alibaba.android.rimet/51255538 Channel/700159 language/zh-CN abi/64",
    "Referer": "https://skl.hdu.edu.cn/index.html",
    "Origin": "https://skl.hdu.edu.cn",
    "X-Requested-With": "com.alibaba.android.rimet",
}


def attempt(code: str):
    url = ("https://skl.hdu.edu.cn/api/ali-nvc/captcha-verify?"
           "captchaVerifyParam=%7B%22sceneId%22%3A%222q42bw25%22%7D"
           f"&userid={USERID}&code={code}&latitude={LAT}&longitude={LNG}"
           f"&t={int(time.time() * 1000)}")
    r = requests.post(url, headers=HEADERS, timeout=10)
    return r.status_code, r.text.strip()


def main() -> int:
    if len(sys.argv) < 2 or not (len(sys.argv[1]) == 4 and sys.argv[1].isdigit()):
        print("用法: python sign.py <4位签到码>")
        return 2
    code = sys.argv[1]
    print(f"[i] 尝试签到码 {code}, 最多 5 次(避 WAF 空响应)...")
    for i in range(1, 6):
        try:
            status, body = attempt(code)
        except Exception as e:  # noqa: BLE001
            print(f"  #{i} 网络异常: {e}")
            time.sleep(2)
            continue
        if status == 200 and not body:
            print(f"  #{i} 200空响应(WAF拦截), 重试...")
            time.sleep(1.5)
            continue
        print(f"  #{i} HTTP {status}: {body[:200]}")
        low = body.lower()
        if "成功" in body or '"code":200' in low or '"code":1' in low:
            print("PASS: 签到成功 -> 服务端不强制验证码, 可全自动")
            return 0
        if "不存在" in body or "过期" in body or "错误" in body:
            print("STOP: 码无效或已过期")
            return 1
        if "验证" in body or "captcha" in low or "参数" in body:
            print("STOP: 服务端强校验验证码 -> 需 Playwright 真浏览器方案")
            return 1
        time.sleep(1.5)
    print("FAIL: 未得到明确结果")
    return 1


if __name__ == "__main__":
    sys.exit(main())
