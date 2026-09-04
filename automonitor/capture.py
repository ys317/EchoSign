"""Audio sources: WASAPI loopback (system playback capture) and WAV file.

All sources yield mono float32 numpy arrays resampled to SAMPLE_RATE.
"""
from __future__ import annotations

import queue
import threading
import time
import warnings
import wave
from typing import Iterator, Optional

import numpy as np

warnings.filterwarnings("ignore", message="data discontinuity in recording")

SAMPLE_RATE = 16000


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

    def chunks(self) -> Iterator[np.ndarray]:
        """Capture in a dedicated thread so ASR decode time never stalls the
        recorder (stalls cause WASAPI buffer gaps / 'data discontinuity').
        If ASR falls behind, oldest chunks are dropped to keep latency bounded."""
        buf: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=40)  # ~10s @0.25s
        dropped = [0]

        def _worker():
            with self._mic.recorder(samplerate=self.RECORD_RATE, channels=1) as rec:
                while True:
                    block = rec.record(numframes=self.chunk_frames)  # float32 (frames, 1)
                    mono = block.mean(axis=1) if block.ndim > 1 else block
                    data = resample_to_16k(mono, self.RECORD_RATE)
                    if buf.full():
                        try:
                            buf.get_nowait()
                            dropped[0] += 1
                        except queue.Empty:
                            pass
                    buf.put(data)

        threading.Thread(target=_worker, daemon=True).start()

        while True:
            yield buf.get()


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
