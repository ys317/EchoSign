"""System playback and WAV sources, resampling, and streaming speech recognition."""
from __future__ import annotations

import math
import queue
import tempfile
import threading
import time
import warnings
import wave
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

import numpy as np

SAMPLE_RATE = 16000


class StreamingASR:
    def __init__(self, model_dir: str, num_threads: int = 1, provider: str = "cpu",
                 hotwords: Optional[List[str]] = None, hotwords_score: float = 1.5,
                 decoding_method: Optional[str] = None):
        import sherpa_onnx

        d = Path(model_dir)
        if isinstance(hotwords, str):
            hotwords = [hotwords]
        hotwords = [str(h).strip() for h in (hotwords or []) if h is not None and str(h).strip()]
        options = {"decoding_method": decoding_method or "greedy_search"}
        hotwords_file: Optional[Path] = None
        if hotwords:
            # Contextual biasing needs beam search; phrases are spelt one token per
            # character for this character-level Chinese model. The file is only
            # read while the recognizer is being built.
            handle, name = tempfile.mkstemp(prefix="echosign-hotwords-", suffix=".txt")
            hotwords_file = Path(name)
            with open(handle, "w", encoding="utf-8") as stream:
                stream.write("\n".join(" ".join(h.replace(" ", "")) for h in hotwords) + "\n")
            options.update(hotwords_file=name, hotwords_score=float(hotwords_score),
                           modeling_unit="cjkchar", decoding_method="modified_beam_search")
        try:
            self._rec = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(next(d.glob("tokens.txt"))),
                encoder=str(next(d.glob("encoder*.onnx"))),
                decoder=str(next(d.glob("decoder*.onnx"))),
                joiner=str(next(d.glob("joiner*.onnx"))),
                num_threads=num_threads,
                sample_rate=SAMPLE_RATE,
                feature_dim=80,
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=2.4,
                rule2_min_trailing_silence=1.2,
                rule3_min_utterance_length=300,
                provider=provider,
                **options,
            )
        finally:
            if hotwords_file is not None:
                try:
                    hotwords_file.unlink()
                except OSError:
                    pass
        self.restart()

    def accept(self, samples: np.ndarray) -> Tuple[List[str], str]:
        """Feed one chunk. Returns (finalized sentences since last call, live partial)."""
        self._has_audio = self._has_audio or bool(len(samples))
        self._stream.accept_waveform(SAMPLE_RATE, samples.astype(np.float32).tolist())
        while self._rec.is_ready(self._stream):
            self._rec.decode_stream(self._stream)
            self.revision += 1

        finals: List[str] = []
        partial = self._rec.get_result(self._stream)
        if self._rec.is_endpoint(self._stream):
            if partial.strip():
                finals.append(partial.strip())
            self._rec.reset(self._stream)
            partial = ""
        return finals, partial.strip()

    def flush(self) -> List[str]:
        """Finish decoding buffered audio before committing the final utterance."""
        if not self._has_audio:
            return []
        # The streaming model needs right context for its last frames. Reading
        # get_result() directly can promote an incomplete digit prefix to a code.
        self._stream.accept_waveform(SAMPLE_RATE, [0.0] * int(0.3 * SAMPLE_RATE))
        self._stream.input_finished()
        while self._rec.is_ready(self._stream):
            self._rec.decode_stream(self._stream)
        tail = self._rec.get_result(self._stream).strip()
        self.restart()
        return [tail] if tail else []

    def restart(self) -> None:
        """Start a fresh stream so one loaded model can serve several recordings."""
        self._stream = self._rec.create_stream()
        self._has_audio = False
        self.revision = 0


class StreamingResampler:
    """Band-limited mono resampling with shared filter history and sample phase.

    A Blackman-windowed sinc leaves a transition band below the lower Nyquist
    frequency. About 2 ms of lookahead avoids padding every capture block; only
    the start and the final flush are zero-padded.
    """

    def __init__(self, src_rate: int):
        if src_rate <= 0:
            raise ValueError("采样率必须大于零")
        self.src_rate = src_rate
        self._received = 0
        self._output = 0
        self._finished = False
        self._radius = math.ceil(32 * max(1, src_rate / SAMPLE_RATE))
        self._origin = -self._radius
        self._buffer = np.zeros(self._radius, dtype=np.float32)
        if src_rate == SAMPLE_RATE:
            return

        divisor = math.gcd(src_rate, SAMPLE_RATE)
        self._up = SAMPLE_RATE // divisor
        self._down = src_rate // divisor
        offsets = np.arange(-self._radius, self._radius + 1)
        distance = offsets[None, :] - np.arange(self._up)[:, None] / self._up
        window = (0.42 + 0.5 * np.cos(np.pi * distance / self._radius)
                  + 0.08 * np.cos(2 * np.pi * distance / self._radius))
        window[np.abs(distance) > self._radius] = 0
        cutoff = 0.9 * min(1, SAMPLE_RATE / src_rate)
        weights = cutoff * np.sinc(cutoff * distance) * window
        weights /= weights.sum(axis=1, keepdims=True)
        self._weights = weights.astype(np.float32)

    def accept(self, data: np.ndarray, *, final: bool = False) -> np.ndarray:
        if self._finished:
            raise RuntimeError("重采样已结束，请为新的音频创建重采样器")
        data = np.asarray(data, dtype=np.float32)
        if data.ndim != 1:
            raise ValueError("重采样输入必须为单声道音频")
        self._finished = final
        if self.src_rate == SAMPLE_RATE:
            return data

        self._received += len(data)
        self._buffer = np.concatenate((self._buffer, data))
        available = self._received - (0 if final else self._radius)
        end = max(0, (available * SAMPLE_RATE + self.src_rate - 1) // self.src_rate)
        if final:
            self._buffer = np.pad(self._buffer, (0, self._radius))
        if end <= self._output:
            return np.empty(0, dtype=np.float32)

        positions = np.arange(self._output, end, dtype=np.int64) * self._down
        centers, phases = np.divmod(positions, self._up)
        starts = centers - self._radius - self._origin
        windows = np.lib.stride_tricks.sliding_window_view(
            self._buffer, 2 * self._radius + 1)
        result = np.einsum("ij,ij->i", windows[starts], self._weights[phases])
        self._output = end
        keep_from = end * self._down // self._up - self._radius
        discard = max(0, keep_from - self._origin)
        self._buffer = self._buffer[discard:].copy()
        self._origin += discard
        return result

    def flush(self) -> np.ndarray:
        if self._finished:
            return np.empty(0, dtype=np.float32)
        return self.accept(np.empty(0, dtype=np.float32), final=True)


def resample_to_16k(data: np.ndarray, src_rate: int) -> np.ndarray:
    """Resample a complete clip; live sources retain a StreamingResampler instead."""
    return StreamingResampler(src_rate).accept(data, final=True)


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
                resampler = StreamingResampler(self.RECORD_RATE)
                with self._mic.recorder(samplerate=self.RECORD_RATE, channels=1) as rec:
                    while not stopping():
                        block = rec.record(numframes=self.chunk_frames)
                        if stopping():
                            break
                        mono = block.mean(axis=1) if block.ndim > 1 else block
                        data = resampler.accept(mono)
                        if not len(data):
                            continue
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
            resampler = StreamingResampler(src_rate)
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
                out = resampler.accept(data)
                if not len(out):
                    continue
                if self.realtime:
                    time.sleep(len(out) / SAMPLE_RATE)
                yield out
            tail = resampler.flush()
            if len(tail):
                if self.realtime:
                    time.sleep(len(tail) / SAMPLE_RATE)
                yield tail
