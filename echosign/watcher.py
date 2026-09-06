"""Sign-in code watcher: digit normalization, 4-digit code extraction,
watch-window transcript after a sign-in trigger."""
from __future__ import annotations

import json
import re
import time
from collections import deque
from typing import List, Optional, Tuple

CN_DIGITS = {"零": "0", "〇": "0", "一": "1", "幺": "1", "二": "2", "两": "2",
             "三": "3", "四": "4", "五": "5", "六": "6", "七": "7", "八": "8",
             "九": "9"}
_DIGIT_RUN = re.compile("[0-9" + "".join(CN_DIGITS) + "]+")
_CODE = re.compile(r"(?<!\d)\d{4}(?!\d)")


def _convert_run(s: str) -> str:
    """Pure-ASCII runs stay as-is; 4-char Chinese runs read digit-by-digit."""
    if s.isdigit():
        return s
    if len(s) == 4 and all(ch in CN_DIGITS for ch in s):
        return "".join(CN_DIGITS[ch] for ch in s)
    return s


def extract_codes(text: str) -> Tuple[str, List[str]]:
    """Return (digit-normalized text, list of 4-digit codes)."""
    converted = _DIGIT_RUN.sub(lambda m: _convert_run(m.group()), text)
    return converted, _CODE.findall(converted)


class SignInWatcher:
    """Collects recent sentences; on trigger keeps a transcript open for
    `window_seconds` and extracts 4-digit codes from everything heard."""

    def __init__(self, window_seconds: float = 60, context_seconds: float = 30,
                 code_dedup: float = 60, log_file: str = "codes.jsonl",
                 standalone_code: bool = True):
        self.window_seconds = window_seconds
        self.context_seconds = context_seconds
        self.code_dedup = code_dedup
        self.log_file = log_file
        self.standalone_code = standalone_code
        self.recent: deque = deque()          # (ts, text) finals for context dump
        self.watch_until = 0.0
        self._last_code: dict = {}
        self.codes_found: List[Tuple[str, str]] = []  # (code, source text)
        self.on_code = lambda code, text: None  # set by caller

    @property
    def active(self) -> bool:
        return time.time() < self.watch_until

    def trigger(self, text: str, reason: str) -> None:
        now = time.time()
        self.watch_until = now + self.window_seconds
        print(f"\n{'=' * 62}")
        print(f"[监码窗口开启 {time.strftime('%H:%M:%S')}] 触发: {reason}")
        print(f"--- 触发前 {int(self.context_seconds)}s 上下文 ---")
        for ts, t in self.recent:
            print(f"  -{now - ts:4.0f}s | {t}")
        print(f"--- 触发句 ---")
        print(f"   0s  | {text}")
        print(f"接下来 {int(self.window_seconds)}s 内的所有识别文本将实时输出, 关注4位数字")
        print(f"{'=' * 62}\n")

    def feed(self, text: str, final: bool = True) -> List[Tuple[str, str]]:
        """Feed recognized text; returns newly found (code, source) pairs."""
        now = time.time()
        if final:
            self.recent.append((now, text))
            while self.recent and now - self.recent[0][0] > self.context_seconds:
                self.recent.popleft()
        if not self.active and not (final and self.standalone_code):
            return []

        norm, codes = extract_codes(text)
        if not self.active:
            # 窗口未开时只认" essentially 就是一个码"的短句, 避免长句里的年份等误报
            residue = norm.replace(str(codes[0]), "", 1) if codes else norm
            if not codes or len(residue.strip()) > 4:
                return []
        found = []
        for c in codes:
            if now - self._last_code.get(c, 0) < self.code_dedup:
                continue
            self._last_code[c] = now
            found.append((c, text))
            self.codes_found.append((c, text))
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(json.dumps({"ts": now, "time": time.strftime("%H:%M:%S"),
                                        "code": c, "text": text},
                                       ensure_ascii=False) + "\n")
            except OSError:
                pass
        return found
