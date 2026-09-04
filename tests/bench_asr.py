import sys
import time
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from automonitor.asr import StreamingASR
from automonitor.capture import WavFileSource

MODEL = "models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
WAV = "models/sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30/test_wavs/1.wav"

chunks = list(WavFileSource(WAV, 0.25).chunks())
audio_sec = sum(len(c) for c in chunks) / 16000
print(f"音频时长 {audio_sec:.1f}s, 共 {len(chunks)} 块")

for threads in (4, 6, 8):
    asr = StreamingASR(MODEL, num_threads=threads)
    t0 = time.perf_counter()
    for c in chunks:
        asr.accept(c)
    dt = time.perf_counter() - t0
    print(f"threads={threads}: 解码 {dt:.2f}s, 实时率 x{audio_sec / dt:.2f} (>1 表示快于实时)")
