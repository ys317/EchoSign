"""Two-tier matcher: cheap rules first, optional embedding semantics second."""
from __future__ import annotations

import re
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

        self._model = TextEmbedding(model_name=model)

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
