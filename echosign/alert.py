"""Alerting: console highlight + JSONL log + 企业微信机器人, with dedup."""
from __future__ import annotations

import json
import threading
import time
import urllib.request
from typing import Dict, Iterable


class Alerter:
    def __init__(self, log_file: str = "alerts.jsonl", dedup_seconds: float = 90,
                 webhook_url: str = "", webhook_levels: Iterable[str] = ("high", "code")):
        self.log_file = log_file
        self.dedup_seconds = dedup_seconds
        self.webhook_url = webhook_url.strip()
        self.webhook_levels = tuple(webhook_levels)
        self._last_fire: Dict[str, float] = {}

    def notify(self, text: str, level: str, reason: str) -> bool:
        key = f"{level}|{text.strip()[:40]}"
        now = time.time()
        if now - self._last_fire.get(key, 0) < self.dedup_seconds:
            return False
        self._last_fire[key] = now

        ts = time.strftime("%H:%M:%S")
        print(f"\n{'!' * 60}")
        print(f"*** 签到提醒 [{level}] {ts}: {reason}")
        print(f"*** 原文: {text}")
        print(f"{'!' * 60}")
        if self.webhook_url and level in self.webhook_levels:
            threading.Thread(target=self._send_wechat, args=(ts, level, reason, text),
                             daemon=True).start()
        try:
            with open(self.log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps({"ts": now, "time": ts, "level": level,
                                    "reason": reason, "text": text},
                                   ensure_ascii=False) + "\n")
        except OSError:
            pass
        return True

    def _send_wechat(self, ts: str, level: str, reason: str, text: str) -> None:
        label = {"high": "签到", "medium": "疑似签到", "code": "签到码", "semantic": "语义"}.get(level, level)
        if level == "code":
            body = f"**【{label}】{reason}**\n> 时间: {ts}\n> 原句: {text}"
        else:
            body = (f"**【{label}】{reason}**\n"
                    f"> 时间: {ts}\n> 原句: {text}")
        payload = {"msgtype": "markdown", "markdown": {"content": body}}
        req = urllib.request.Request(
            self.webhook_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                out = json.loads(resp.read().decode("utf-8"))
                if out.get("errcode") != 0:
                    print(f"[warn] 企业微信返回异常: {out}")
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 企业微信推送失败: {e}")
