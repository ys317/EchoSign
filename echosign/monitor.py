"""Entry point.

  python -m echosign devices        # 列出可用输出设备
  python -m echosign run            # 启动监控
  python -m echosign test FILE.wav  # 识别音频文件
  python -m echosign demo           # 检查规则匹配
"""
from __future__ import annotations

import argparse
from contextlib import closing
import sys
import threading
import time

import yaml

from echosign.alert import Alerter
from echosign.attendance import make_auto_signer
from echosign.audio import SAMPLE_RATE, LoopbackSource, StreamingASR, WavFileSource
from echosign.rules import RuleMatcher, SignInWatcher, build_matchers, extract_codes


def load_config(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def cmd_devices() -> None:
    import soundcard as sc

    print("可用输出设备(扬声器):")
    d = sc.default_speaker()
    for s in sc.all_speakers():
        mark = "  <- 默认" if s.name == d.name else ""
        print(f"  {s.name}{mark}")


def make_engine(cfg: dict) -> StreamingASR:
    a = cfg.get("asr", {})
    return StreamingASR(a.get("model_dir", "models/sherpa-onnx-streaming-zipformer-zh-14M"),
                        int(a.get("num_threads", 4)), a.get("provider", "cpu"),
                        hotwords=a.get("hotwords") or [],
                        hotwords_score=float(a.get("hotwords_score", 1.5)),
                        decoding_method=a.get("decoding_method") or None)


def make_alerter(cfg: dict, dedup_override: float | None = None, clock=None) -> Alerter:
    al = cfg.get("alert", {})
    wh = al.get("webhook", {}) or {}
    return Alerter(al.get("log_file", "alerts.jsonl"),
                   float(al.get("dedup_seconds", 90)) if dedup_override is None else dedup_override,
                   str(wh.get("url", "") or ""), wh.get("levels", ("high", "code")), clock=clock)


def make_watcher(cfg: dict, alerter: Alerter, auto=None, stop=None, clock=None) -> SignInWatcher:
    cw = cfg.get("code_watch", {})

    def on_code(code: str, text: str):
        if stop is not None and stop.is_set():
            return
        if auto:
            auto.submit(code)
        alerter.notify(text, "code", f"签到码: {code}")

    w = SignInWatcher(float(cw.get("window_seconds", 60)),
                      float(cw.get("context_seconds", 30)),
                      float(cw.get("code_dedup", 60)),
                      cw.get("log_file", "codes.jsonl"),
                      bool(cw.get("standalone_code", True)), clock=clock,
                      early_code=bool(cw.get("early_code", True)),
                      early_stable_seconds=float(cw.get("early_stable_seconds", 0.4)))
    w.on_code = on_code
    if auto is not None:
        w.on_prepare = lambda: auto.prepare() if stop is None or not stop.is_set() else None
    return w


class AudioClock:
    """Position inside a replayed recording, in seconds.

    Replaying a file is much faster than real time, so alert de-duplication and
    the code-watch window must follow the audio position, not the wall clock.
    """

    def __init__(self, start: float = 0.0):
        self.seconds = float(start)

    def __call__(self) -> float:
        return self.seconds

    def advance(self, chunks):
        """Yield chunks while moving the clock to the end of each chunk."""
        for chunk in chunks:
            self.seconds += len(chunk) / SAMPLE_RATE
            yield chunk

    def stamp(self) -> str:
        total = int(self.seconds)
        return f"{total // 3600:02d}:{total // 60 % 60:02d}:{total % 60:02d}"


def run_pipeline(chunks, asr, matchers, alerter, watcher: SignInWatcher | None = None,
                 show_partial: bool = True, stop=None, clock: AudioClock | None = None) -> None:
    t0 = time.time()
    audio_time = 0.0
    partial_matchers = [m for m in matchers if isinstance(m, RuleMatcher)]

    def handle(text: str):
        if stop is not None and stop.is_set():
            return
        stamp = clock.stamp() if clock is not None else time.strftime("%H:%M:%S")
        print(f"\r[ASR {stamp}] {text}          ")
        hits = [h for m in matchers if (h := m.match(text))]
        if stop is not None and stop.is_set():
            return
        if hits and watcher:
            level, reason = max(hits, key=lambda h: {"high": 2, "medium": 1}.get(h[0], 0))
            if alerter.notify(text, level, reason):
                watcher.trigger(text, reason)
        elif hits:
            level, reason = max(hits, key=lambda h: {"high": 2, "medium": 1}.get(h[0], 0))
            alerter.notify(text, level, reason)
        if watcher:
            for code, src in watcher.feed(text, final=True):
                watcher.on_code(code, src)

    for chunk in chunks:
        if stop is not None and stop.is_set():
            print("\n[i] 收到停止信号")
            break
        audio_time += len(chunk) / SAMPLE_RATE
        finals, partial = asr.accept(chunk)
        if stop is not None and stop.is_set():
            break
        for text in finals:
            handle(text)
        if watcher and (stop is None or not stop.is_set()):
            cue = any((hit := matcher.match(partial)) and hit[0] == "high"
                      for matcher in partial_matchers)
            for code, src in watcher.feed_partial(
                    partial, revision=getattr(asr, "revision", None), audio_time=audio_time, cue=cue):
                if stop is None or not stop.is_set():
                    watcher.on_code(code, src)
        if show_partial and partial and sys.stdout is not None:
            line = f"…识别中: {partial}"
            sys.stdout.write("\r" + line.ljust(78)[:78])
            sys.stdout.flush()
    if stop is None or not stop.is_set():
        for text in asr.flush():
            handle(text)
    print(f"\n结束, 共处理音频 {time.time() - t0:.1f}s(墙钟)")


def cmd_run(cfg: dict, stop=None) -> None:
    stop = stop if stop is not None else threading.Event()
    chunk = float(cfg.get("chunk_seconds", 0.25))
    src = LoopbackSource(cfg.get("device") or None, chunk)
    print(f"[i] 正在监听输出设备: {src.speaker_name} (内录环回)")
    alerter = make_alerter(cfg)
    auto = make_auto_signer(cfg, alerter, stop)
    try:
        matchers = build_matchers(cfg)
        watcher = make_watcher(cfg, alerter, auto, stop)
        print(f"[i] 匹配器: {[type(m).__name__ for m in matchers]}")
        asr = make_engine(cfg)
        if stop.is_set():
            return
        print("[i] ASR 就绪, Ctrl+C 停止\n")
        with closing(src.chunks(stop=stop)) as chunks:
            run_pipeline(chunks, asr, matchers, alerter, watcher, stop=stop)
    except KeyboardInterrupt:
        stop.set()
        print("\n已停止")
    finally:
        if auto is not None:
            auto.close()


def cmd_test(cfg: dict, wav: str, realtime: bool) -> None:
    stop = threading.Event()
    clock = AudioClock()
    src = WavFileSource(wav, float(cfg.get("chunk_seconds", 0.25)), realtime)
    alerter = make_alerter(cfg, dedup_override=0, clock=clock)
    auto = make_auto_signer(cfg, alerter, stop)
    completed = False
    try:
        matchers = build_matchers(cfg)
        watcher = make_watcher(cfg, alerter, auto, stop, clock=clock)
        asr = make_engine(cfg)
        with closing(src.chunks()) as chunks:
            run_pipeline(clock.advance(chunks), asr, matchers, alerter, watcher,
                         stop=stop, clock=clock)
        completed = True
    finally:
        if auto is not None:
            auto.close(cancel=not completed)


def cmd_demo(cfg: dict) -> None:
    samples = [
        "好的同学们, 现在我们开始签到, 请大家打开我的课堂",
        "今天天气不错, 我们直接开始上课吧",
        "来, 扫一下这个二维码就可以进入了哦",
        "看到的同学在群里扣个一",
        "PPT 链接我稍后发给你们",
    ]
    matchers = build_matchers(cfg)
    for s in samples:
        hits = [m.match(s) for m in matchers]
        hits = [h for h in hits if h]
        print(f"\n> {s}")
        if hits:
            for level, reason in hits:
                print(f"    -> 命中 [{level}] {reason}")
        else:
            print("    -> 未命中")


def cmd_webhook_test(cfg: dict) -> None:
    alerter = make_alerter(cfg, dedup_override=0)
    if not alerter.webhook_url:
        print("config.yaml 里 alert.webhook.url 为空, 请先填入机器人 Webhook 地址")
        return
    print("正在发送 EchoSign 测试推送…")
    alerter._send_wechat(time.strftime("%H:%M:%S"), "test", "EchoSign 测试推送",
                         "这是一条 EchoSign 测试消息，收到说明企业微信推送正常。")


def cmd_code() -> None:
    samples = [
        "签到码是1234",
        "签到码幺二三四",
        "好的签到码是一二三四大家抓紧输入",
        "请输入签到码2026",
        "一分钟时间抓紧",
        "电话号码13812345678不是签到码",
    ]
    for s in samples:
        norm, codes = extract_codes(s)
        print(f"> {s}\n    归一: {norm}\n    码: {codes or '无'}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="echosign")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("devices")
    prun = sub.add_parser("run")
    prun.add_argument("--config", default="config.yaml")
    ptest = sub.add_parser("test")
    ptest.add_argument("wav")
    ptest.add_argument("--config", default="config.yaml")
    ptest.add_argument("--realtime", action="store_true")
    pdemo = sub.add_parser("demo")
    pdemo.add_argument("--config", default="config.yaml")
    sub.add_parser("code")
    pwh = sub.add_parser("webhook-test")
    pwh.add_argument("--config", default="config.yaml")
    args = p.parse_args(argv)

    if args.cmd == "devices":
        cmd_devices()
    elif args.cmd == "run":
        cmd_run(load_config(args.config))
    elif args.cmd == "test":
        cmd_test(load_config(args.config), args.wav, args.realtime)
    elif args.cmd == "demo":
        cmd_demo(load_config(args.config))
    elif args.cmd == "code":
        cmd_code()
    elif args.cmd == "webhook-test":
        cmd_webhook_test(load_config(args.config))

    return 0
