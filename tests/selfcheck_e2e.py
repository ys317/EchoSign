"""End-to-end smoke test: play TTS wav through speakers -> loopback capture -> ASR -> matcher.

Run: .venv\\Scripts\\python.exe tests\\selfcheck_e2e.py
Exit code 0 if at least one 'high' alert fired, else 1.
"""
from __future__ import annotations

import pathlib
import sys
import threading
import time
import wave
import winsound

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from automonitor.alert import Alerter  # noqa: E402
from automonitor.asr import StreamingASR  # noqa: E402
from automonitor.capture import LoopbackSource  # noqa: E402
from automonitor.matcher import build_matchers  # noqa: E402
from automonitor.watcher import SignInWatcher  # noqa: E402

TEST_WAV = ROOT / "tests" / "tts_signin.wav"
LEAD_SECONDS = 1.0      # start recording before playback
TAIL_SECONDS = 4.0      # keep recording after playback ends


def wav_seconds(path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


class RecordingAlerter(Alerter):
    def __init__(self):
        super().__init__(log_file=str(ROOT / "tests" / "e2e_alerts.jsonl"),
                         dedup_seconds=0)
        self.hits = []

    def notify(self, text, level, reason):
        self.hits.append((level, reason, text))
        print(f"  [ALERT-{level}] {reason} | {text}")
        return True

def collect_matches(texts, matchers):
    for t in texts:
        for m in matchers:
            if (hit := m.match(t)):
                level, reason = hit
                return level, reason, t
    return None


def main() -> int:
    cfg = yaml.safe_load(open(ROOT / "config.yaml", encoding="utf-8"))
    audio_len = wav_seconds(TEST_WAV)
    total = LEAD_SECONDS + audio_len + TAIL_SECONDS
    print(f"[i] 播放 {audio_len:.1f}s 测试语音, 共录制 {total:.1f}s")

    src = LoopbackSource(cfg.get("device") or None, float(cfg.get("chunk_seconds", 0.25)))
    a = cfg["asr"]
    asr = StreamingASR(a["model_dir"], int(a.get("num_threads", 4)), a.get("provider", "cpu"))
    matchers = build_matchers(cfg)
    alerter = RecordingAlerter()
    cw = cfg.get("code_watch", {})
    watcher = SignInWatcher(float(cw.get("window_seconds", 60)),
                            float(cw.get("context_seconds", 30)),
                            float(cw.get("code_dedup", 60)),
                            str(ROOT / "tests" / "e2e_codes.jsonl"))

    def play():
        time.sleep(LEAD_SECONDS)
        winsound.PlaySound(str(TEST_WAV), winsound.SND_FILENAME | winsound.SND_ASYNC)

    threading.Thread(target=play, daemon=True).start()

    chunks = src.chunks()
    deadline = time.time() + total
    for chunk in chunks:
        if time.time() > deadline:
            break
        finals, partial = asr.accept(chunk)
        for t in finals:
            print(f"[ASR] {t}")
            hit = collect_matches([t], matchers)
            if hit:
                alerter.notify(hit[2], hit[0], hit[1])
                watcher.trigger(t, hit[1])
            for code, src_text in watcher.feed(t, final=True):
                alerter.notify(src_text, "code", f"签到码: {code}")
        if partial and watcher.active:
            for code, src_text in watcher.feed(partial, final=False):
                alerter.notify(src_text, "code", f"签到码: {code}")
        if partial:
            sys.stdout.write("\r…识别中: " + partial.ljust(70)[:70])
            sys.stdout.flush()
    tail = collect_matches(asr.flush(), matchers)
    if tail:
        print(f"\n[ASR-tail] {tail[2]}")
        alerter.notify(tail[2], tail[0], tail[1])

    print()
    highs = [h for h in alerter.hits if h[0] == "high"]
    codes = [h for h in alerter.hits if h[0] == "code"]
    if highs and codes:
        print(f"PASS: high 告警 {len(highs)} 条, 签到码 {codes[0][1]}")
        return 0
    print(f"FAIL: high={len(highs)} code={len(codes)} (总命中 {len(alerter.hits)})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
