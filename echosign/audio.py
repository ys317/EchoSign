"""System playback and WAV sources, resampling, and streaming speech recognition."""
from __future__ import annotations

import queue
import threading
import time
import warnings
import wave
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

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


def resample_to_16k(data: np.ndarray, src_rate: int) -> np.ndarray:
    """Anti-aliased decimation when possible, else linear interpolation."""
    if src_rate == SAMPLE_RATE or len(data) == 0:
        return data.astype(np.float32)
    if src_rate % SAMPLE_RATE == 0:
        factor = src_rate // SAMPLE_RATE
        n = 8 * factor + 1
        win = np.blackman(n)
        h = np.sinc(np.arange(n) - (n - 1) / 2) * win
        h /= h.sum()
        y = np.convolve(data, h, mode="same")
        return y[::factor].astype(np.float32)
    n_out = int(len(data) * SAMPLE_RATE / src_rate)
    if n_out < 1:
        return np.empty(0, dtype=np.float32)
    x_old = np.arange(len(data), dtype=np.float64)
    x_new = np.linspace(0, len(data) - 1, n_out)
    return np.interp(x_new, x_old, data).astype(np.float32)


class LoopbackSource:
    """Capture what the default (or chosen) speaker is playing via WASAPI loopback."""

    RECORD_RATE = 48000

    def __init__(self, name_hint: Optional[str] = None, chunk_seconds: float = 0.25):
        import soundcard as sc

        # soundcard 在导入时会 simplefilter('always', SoundcardRuntimeWarning) 顶掉
        # 模块顶部的 ignore, 因此必须在导入 soundcard 之后再注册:
        warnings.filterwarnings("ignore", message="data discontinuity in recording")

        if name_hint:
            speakers = [s for s in sc.all_speakers() if name_hint.lower() in s.name.lower()]
            if not speakers:
                raise RuntimeError(f"找不到名称包含 {name_hint!r} 的输出设备, 用 devices 命令查看")
            speaker = speakers[0]
        else:
            speaker = sc.default_speaker()
        self.speaker_name = speaker.name
        self._mic = sc.get_microphone(speaker.name, include_loopback=True)
        self.chunk_frames = int(self.RECORD_RATE * chunk_seconds)

    def chunks(self, stop: threading.Event | None = None) -> Iterator[np.ndarray]:
        """Capture in a dedicated thread so ASR decode time never stalls the
        recorder (stalls cause WASAPI buffer gaps / 'data discontinuity').
        If ASR falls behind, oldest chunks are dropped to keep latency bounded."""
        buf: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=40)  # ~10s @0.25s
        shutdown = threading.Event()
        finished = threading.Event()
        errors: queue.Queue[Exception] = queue.Queue(maxsize=1)

        def stopping():
            return shutdown.is_set() or (stop is not None and stop.is_set())

        if stopping():
            return

        def _worker():
            try:
                with self._mic.recorder(samplerate=self.RECORD_RATE, channels=1) as rec:
                    while not stopping():
                        block = rec.record(numframes=self.chunk_frames)
                        if stopping():
                            break
                        mono = block.mean(axis=1) if block.ndim > 1 else block
                        data = resample_to_16k(mono, self.RECORD_RATE)
                        try:
                            buf.put_nowait(data)
                        except queue.Full:
                            try:
                                buf.get_nowait()
                            except queue.Empty:
                                pass
                            buf.put_nowait(data)
            except Exception as exc:
                errors.put_nowait(exc)
            finally:
                finished.set()

        worker = threading.Thread(target=_worker, name="EchoSign audio capture", daemon=True)
        worker.start()
        try:
            while not stopping():
                if finished.is_set():
                    if not errors.empty():
                        exc = errors.get_nowait()
                        raise RuntimeError(f"音频采集失败：{exc}") from exc
                    if buf.empty():
                        break
                try:
                    data = buf.get(timeout=0.1)
                except queue.Empty:
                    continue
                if not stopping():
                    yield data
        finally:
            shutdown.set()
            worker.join(timeout=max(2.0, 3 * self.chunk_frames / self.RECORD_RATE))
            if worker.is_alive():
                raise RuntimeError("音频设备未响应停止，请关闭程序后检查输出设备")


class WavFileSource:
    """Feed a WAV file through the same pipeline (for offline testing / replay)."""

    def __init__(self, path: str, chunk_seconds: float = 0.25, realtime: bool = False):
        self.path = path
        self.chunk_seconds = chunk_seconds
        self.realtime = realtime

    def chunks(self) -> Iterator[np.ndarray]:
        with wave.open(self.path, "rb") as wf:
            src_rate = wf.getframerate()
            nch = wf.getnchannels()
            width = wf.getsampwidth()
            frames_per_chunk = int(src_rate * self.chunk_seconds)
            while True:
                raw = wf.readframes(frames_per_chunk)
                if not raw:
                    break
                if width == 2:
                    data = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
                elif width == 4:
                    data = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2**31
                else:
                    raise RuntimeError(f"不支持的采样位宽: {width * 8}bit")
                if nch > 1:
                    data = data[: len(data) - (len(data) % nch)].reshape(-1, nch).mean(axis=1)
                out = resample_to_16k(data, src_rate)
                if self.realtime:
                    time.sleep(len(out) / SAMPLE_RATE)
                yield out
