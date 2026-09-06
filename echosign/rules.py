"""Keyword and semantic matching, plus spoken attendance-code extraction."""
from __future__ import annotations

import json
import re
import time
from collections import deque
from typing import List, Optional, Sequence, Tuple

_RE_NON_ALNUM_CJK = re.compile(r"[^0-9a-zA-Z一-鿿]+")


def normalize(text) -> str:
    return _RE_NON_ALNUM_CJK.sub("", str(text).lower())


class RuleMatcher:
    """strong: any term hit -> high; weak_groups: all terms of a group -> medium.
    strong terms prefixed with "re:" are treated as regex (e.g. "re:(?<![0-9])点到")."""

    def __init__(self, strong: Sequence[str], weak_groups: Sequence[Sequence[str]]):
        self.strong = [normalize(t) for t in strong if t.strip() and not t.startswith("re:")]
        self.strong_re = [re.compile(t[3:]) for t in strong if t.startswith("re:")]
        self.weak_groups = [[normalize(t) for t in g] for g in weak_groups if g]

    def match(self, text: str) -> Optional[Tuple[str, str]]:
        t = normalize(text)
        if not t:
            return None
        for term in self.strong:
            if term and term in t:
                return ("high", f"强关键词:{term}")
        for pat in self.strong_re:
            if pat.search(t):
                return ("high", f"强规则:{pat.pattern}")
        for group in self.weak_groups:
            hit = [g for g in group if g in t]
            if len(hit) == len(group):
                return ("medium", f"弱词组合:{group}")
        return None


class SemanticMatcher:
    """Optional cosine-similarity matcher against template sentences (fastembed)."""

    def __init__(self, templates: Sequence[str], model: str, threshold: float):
        self.threshold = threshold
        self.templates = list(templates)
        from fastembed import TextEmbedding  # lazy; only when enabled

        from echosign.runtime import semantic_model_options

        self._model = TextEmbedding(model_name=model, **semantic_model_options(model))

        import numpy as np

        embs = list(self._model.embed(self.templates))
        self._t_embs = np.array(embs)
        self._t_embs /= np.linalg.norm(self._t_embs, axis=1, keepdims=True) + 1e-9

    def match(self, text: str) -> Optional[Tuple[str, str]]:
        import numpy as np

        emb = next(iter(self._model.embed([text])))
        emb = emb / (np.linalg.norm(emb) + 1e-9)
        sims = self._t_embs @ emb
        i = int(np.argmax(sims))
        if sims[i] >= self.threshold:
            return ("semantic", f"语义[{self.templates[i]}]得分{sims[i]:.2f}")
        return None


def build_matchers(cfg: dict):
    rules = cfg.get("rules", {})
    matchers: List = [RuleMatcher(rules.get("strong", []), rules.get("weak_groups", []))]
    sem = rules.get("semantic", {})
    if sem.get("enabled"):
        try:
            matchers.append(SemanticMatcher(sem.get("templates", []), sem.get("model"),
                                            float(sem.get("threshold", 0.78))))
        except Exception as e:  # noqa: BLE001
            print(f"[warn] 语义匹配初始化失败, 回退到纯规则: {e}")
    return matchers


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
