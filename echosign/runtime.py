"""Resolve portable application resources without using a user's browser cache."""
from __future__ import annotations

import os
from pathlib import Path
import sys

SEMANTIC_MODEL = "BAAI/bge-small-zh-v1.5"
SEMANTIC_FOLDER = "bge-small-zh-v1.5"
SEMANTIC_FILES = ("model_optimized.onnx", "config.json", "tokenizer.json",
                  "tokenizer_config.json", "special_tokens_map.json")
ASR_FOLDER = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
ASR_FILES = ("encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt")


def application_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def resource_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", application_root()))


def configure_browser_runtime() -> None:
    """Frozen apps use only the browser shipped with their own Playwright build."""
    if getattr(sys, "frozen", False):
        browsers = resource_root() / "browsers"
        if not browsers.is_dir():
            raise RuntimeError("浏览器组件缺失，请重新完整解压 EchoSign 发行包。")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)


def semantic_model_options(model: str) -> dict:
    if model != SEMANTIC_MODEL:
        return {}
    directory = application_root() / "models" / SEMANTIC_FOLDER
    if all((directory / name).is_file() for name in SEMANTIC_FILES):
        return {"specific_model_path": str(directory), "local_files_only": True}
    if getattr(sys, "frozen", False):
        raise RuntimeError("语义模型不完整，请重新完整解压 EchoSign 发行包。")
    return {}


def check_runtime(report_path: str) -> int:
    """Offline package check; never touches account data, live audio or the school."""
    import json
    import tempfile
    import traceback

    from echosign import __version__

    report = {"version": __version__, "ok": False}
    try:
        import numpy as np
        from fastembed import TextEmbedding
        from playwright.sync_api import sync_playwright
        from echosign.asr import StreamingASR

        configure_browser_runtime()
        with tempfile.TemporaryDirectory(prefix="echosign-check-") as temporary:
            # Keep inference independent of an existing Hugging Face/model cache.
            embedding = TextEmbedding(model_name=SEMANTIC_MODEL,
                                      cache_dir=str(Path(temporary) / "models"),
                                      **semantic_model_options(SEMANTIC_MODEL))
            vector = next(iter(embedding.embed(["课堂签到提醒"])))
            if len(vector) != 512 or not np.isfinite(vector).all():
                raise RuntimeError("语义模型未返回有效向量")
            asr = StreamingASR(str(application_root() / "models" / ASR_FOLDER))
            asr.accept(np.zeros(4000, dtype=np.float32))
            asr.flush()
            with sync_playwright() as playwright:
                executable = Path(playwright.chromium.executable_path).resolve()
                if not executable.is_relative_to(resource_root() / "browsers"):
                    raise RuntimeError("浏览器未从发行包加载")
                context = playwright.chromium.launch_persistent_context(
                    str(Path(temporary) / "profile"), headless=True, channel="chromium")
                try:
                    context.route("**/*", lambda route: route.abort())
                    page = context.pages[0] if context.pages else context.new_page()
                    page.set_content("<title>EchoSign</title><p>课堂辅助</p>")
                    if page.title() != "EchoSign":
                        raise RuntimeError("浏览器启动检查失败")
                    cdp = context.new_cdp_session(page)
                    report["browser_version"] = cdp.send("Browser.getVersion")["product"]
                    cdp.detach()
                    report["browser_path"] = str(executable.relative_to(resource_root()))
                finally:
                    context.close()
        report.update(ok=True, asr=True, semantic=True, browser=True)
    except Exception:
        report["error"] = traceback.format_exc()
    Path(report_path).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if report["ok"] else 1
