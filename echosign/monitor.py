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
import time

import yaml

from echosign.alert import Alerter
from echosign.attendance import make_auto_signer
from echosign.audio import LoopbackSource, StreamingASR, WavFileSource
from echosign.rules import SignInWatcher, build_matchers, extract_codes


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
                        int(a.get("num_threads", 4)), a.get("provider", "cpu"))


def make_alerter(cfg: dict, dedup_override: float | None = None) -> Alerter:
    al = cfg.get("alert", {})
    wh = al.get("webhook", {}) or {}
    return Alerter(al.get("log_file", "alerts.jsonl"),
                   float(al.get("dedup_seconds", 90)) if dedup_override is None else dedup_override,
                   str(wh.get("url", "") or ""), wh.get("levels", ("high", "code")))


def make_watcher(cfg: dict, alerter: Alerter) -> SignInWatcher:
    cw = cfg.get("code_watch", {})
    auto = make_auto_signer(cfg, alerter)

    def on_code(code: str, text: str):
        alerter.notify(text, "code", f"签到码: {code}")
        if auto:
            auto.submit(code)

    w = SignInWatcher(float(cw.get("window_seconds", 60)),
                      float(cw.get("context_seconds", 30)),
                      float(cw.get("code_dedup", 60)),
                      cw.get("log_file", "codes.jsonl"),
                      bool(cw.get("standalone_code", True)))
    w.on_code = on_code
    return w


def run_pipeline(chunks, asr, matchers, alerter, watcher: SignInWatcher | None = None,
                 show_partial: bool = True, stop=None) -> None:
    t0 = time.time()

    def handle(text: str):
        print(f"\r[ASR {time.strftime('%H:%M:%S')}] {text}          ")
        hits = [h for m in matchers if (h := m.match(text))]
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
        finals, partial = asr.accept(chunk)
        if stop is not None and stop.is_set():
            break
        for text in finals:
            handle(text)
        if partial and watcher and watcher.active:
            for code, src in watcher.feed(partial, final=False):
                watcher.on_code(code, src)
        if show_partial and partial:
            line = f"…识别中: {partial}"
            sys.stdout.write("\r" + line.ljust(78)[:78])
            sys.stdout.flush()
    remaining = asr.flush()
    if stop is None or not stop.is_set():
        for text in remaining:
            handle(text)
    print(f"\n结束, 共处理音频 {time.time() - t0:.1f}s(墙钟)")


def cmd_run(cfg: dict, stop=None) -> None:
    chunk = float(cfg.get("chunk_seconds", 0.25))
    src = LoopbackSource(cfg.get("device") or None, chunk)
    print(f"[i] 正在监听输出设备: {src.speaker_name} (内录环回)")
    alerter = make_alerter(cfg)
    matchers = build_matchers(cfg)
    watcher = make_watcher(cfg, alerter)
    print(f"[i] 匹配器: {[type(m).__name__ for m in matchers]}")
    asr = make_engine(cfg)
    print("[i] ASR 就绪, Ctrl+C 停止\n")
    try:
        with closing(src.chunks(stop=stop)) as chunks:
            run_pipeline(chunks, asr, matchers, alerter, watcher, stop=stop)
    except KeyboardInterrupt:
        print("\n已停止")


def cmd_test(cfg: dict, wav: str, realtime: bool) -> None:
    src = WavFileSource(wav, float(cfg.get("chunk_seconds", 0.25)), realtime)
    alerter = make_alerter(cfg, dedup_override=0)
    matchers = build_matchers(cfg)
    watcher = make_watcher(cfg, alerter)
    asr = make_engine(cfg)
    run_pipeline(src.chunks(), asr, matchers, alerter, watcher)


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
    print(f"发送测试消息到: {alerter.webhook_url[:60]}...")
    alerter._send_wechat(time.strftime("%H:%M:%S"), "high", "推送链路测试",
                         "这是一条 Automonitor 测试消息, 收到说明企业微信推送正常")


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
