"""Streaming ASR engine (sherpa-onnx zipformer, provider switchable: cpu/cuda).

Engine interface kept minimal (`accept` -> (finals, partial)) so a future
FunASR / cloud-ASR engine only needs to reimplement this class.
"""
from __future__ import annotations

from pathlib import Path
from typing import List, Tuple

import numpy as np

SAMPLE_RATE = 16000


class StreamingASR:
    def __init__(self, model_dir: str, num_threads: int = 4, provider: str = "cpu"):
        import sherpa_onnx

        d = Path(model_dir)
        self._rec = sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=str(next(d.glob("tokens.txt"))),
            encoder=str(next(d.glob("encoder*.onnx"))),
            decoder=str(next(d.glob("decoder*.onnx"))),
            joiner=str(next(d.glob("joiner*.onnx"))),
            num_threads=num_threads,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            decoding_method="greedy_search",
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,
            rule2_min_trailing_silence=1.2,
            rule3_min_utterance_length=300,
            provider=provider,
        )
        self._stream = self._rec.create_stream()

    def accept(self, samples: np.ndarray) -> Tuple[List[str], str]:
        """Feed one chunk. Returns (finalized sentences since last call, live partial)."""
        self._stream.accept_waveform(SAMPLE_RATE, samples.astype(np.float32).tolist())
        while self._rec.is_ready(self._stream):
            self._rec.decode_stream(self._stream)

        finals: List[str] = []
        partial = self._rec.get_result(self._stream)
        if self._rec.is_endpoint(self._stream):
            if partial.strip():
                finals.append(partial.strip())
            self._rec.reset(self._stream)
            partial = ""
        return finals, partial.strip()

    def flush(self) -> List[str]:
        """Force the remaining partial out as a final sentence (end of stream)."""
        finals = []
        tail = self._rec.get_result(self._stream).strip()
        if tail:
            finals.append(tail)
        self._rec.reset(self._stream)
        return finals
