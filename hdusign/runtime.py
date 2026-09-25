"""Resolve portable application resources without using a user's browser cache."""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

SEMANTIC_MODEL = "BAAI/bge-small-zh-v1.5"
SEMANTIC_FOLDER = "bge-small-zh-v1.5"
SEMANTIC_FILES = ("model_optimized.onnx", "config.json", "tokenizer.json",
                  "tokenizer_config.json", "special_tokens_map.json")
ASR_FOLDER = "sherpa-onnx-streaming-zipformer-zh-int8-2025-06-30"
ASR_FILES = ("encoder.int8.onnx", "decoder.onnx", "joiner.int8.onnx", "tokens.txt")
FFMPEG_FILES = ("ffmpeg.exe", "LICENSE", "README.txt", "SOURCE.json", "version.txt",
                "buildconf.txt", "license-notice.txt")


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
            raise RuntimeError("浏览器组件缺失，请重新完整解压 HDUSign 发行包。")
        os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(browsers)


def semantic_model_options(model: str) -> dict:
    if model != SEMANTIC_MODEL:
        return {}
    directory = application_root() / "models" / SEMANTIC_FOLDER
    if all((directory / name).is_file() for name in SEMANTIC_FILES):
        return {"specific_model_path": str(directory), "local_files_only": True}
    if getattr(sys, "frozen", False):
        raise RuntimeError("语义模型不完整，请重新完整解压 HDUSign 发行包。")
    return {}


def check_ffmpeg_runtime(executable: str | Path | None = None) -> dict:
    """Verify network capability and a synthetic audio round trip without a connection."""
    import io
    import wave

    import numpy as np

    from hdusign.processes import hidden_subprocess_options

    if executable is None:
        from hdusign.media import find_ffmpeg
        executable = find_ffmpeg()
    executable = Path(executable).resolve()

    def run(*arguments: str, data: bytes | None = None) -> bytes:
        options = {"stdin": subprocess.DEVNULL} if data is None else {"input": data}
        try:
            result = subprocess.run(
                [str(executable), "-hide_banner", "-loglevel", "error", "-nostdin", *arguments],
                capture_output=True, check=True, timeout=20,
                **options, **hidden_subprocess_options(),
            )
        except (OSError, subprocess.SubprocessError) as exc:
            detail = getattr(exc, "stderr", b"") or b""
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace")
            raise RuntimeError(f"FFmpeg 离线音频检查失败：{detail.strip()[:500] or exc}") from exc
        return result.stdout

    version_output = run("-version").decode("utf-8", errors="replace")
    if not version_output.startswith("ffmpeg version "):
        raise RuntimeError("FFmpeg 未返回有效版本信息")
    protocols = run("-protocols").decode("utf-8", errors="replace")
    input_protocols = protocols.partition("Input:")[2].partition("Output:")[0].split()
    required_protocols = {"file", "pipe", "http", "https", "tcp", "tls"}
    if missing := required_protocols.difference(input_protocols):
        raise RuntimeError("FFmpeg 缺少直播输入协议：" + ", ".join(sorted(missing)))

    # A short stereo tone exercises AAC encode/decode, mono downmix, resampling,
    # and the exact float32 pipe format consumed by the live recognizer.
    source_rate = 48000
    samples = np.arange(source_rate // 4, dtype=np.float64)
    tone = (0.2 * np.sin(2 * np.pi * 440 * samples / source_rate) * 32767).astype("<i2")
    wav = io.BytesIO()
    with wave.open(wav, "wb") as stream:
        stream.setnchannels(2)
        stream.setsampwidth(2)
        stream.setframerate(source_rate)
        stream.writeframes(np.column_stack((tone, tone)).tobytes())
    common = ("-threads", "1", "-filter_threads", "1", "-protocol_whitelist", "pipe")
    encoded = run(*common, "-f", "wav", "-i", "pipe:0", "-map", "0:a:0",
                  "-vn", "-sn", "-dn", "-c:a", "aac", "-b:a", "64k", "-threads", "1",
                  "-f", "adts", "pipe:1", data=wav.getvalue())
    if not encoded:
        raise RuntimeError("FFmpeg 未生成离线音频测试样本")
    decoded = run(*common, "-f", "aac", "-i", "pipe:0", "-map", "0:a:0",
                  "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-threads", "1",
                  "-c:a", "pcm_f32le", "-f", "f32le", "pipe:1", data=encoded)
    if len(decoded) % 4:
        raise RuntimeError("FFmpeg 未返回完整的 float32 音频样本")
    audio = np.frombuffer(decoded, dtype="<f4")
    if not (3200 <= len(audio) <= 8000 and np.isfinite(audio).all()
            and 0.01 < float(np.sqrt(np.mean(audio.astype(np.float64) ** 2))) < 0.5):
        raise RuntimeError("FFmpeg 未返回有效的 16 kHz 单声道音频")
    return {"version": version_output.splitlines()[0].removeprefix("ffmpeg version ").split()[0],
            "sample_rate": 16000, "channels": 1, "decoded_samples": len(audio)}


def check_runtime(report_path: str) -> int:
    """Offline package check; never touches account data, live audio or the school."""
    import json
    import tempfile
    import traceback

    from hdusign import __version__

    report = {"version": __version__, "ok": False}
    try:
        import numpy as np
        from fastembed import TextEmbedding
        from playwright.sync_api import sync_playwright
        from hdusign.audio import StreamingASR
        from hdusign.qt_app import check_desktop_runtime

        report["desktop"] = check_desktop_runtime()

        configure_browser_runtime()
        ffmpeg = check_ffmpeg_runtime()
        report.update(ffmpeg=True, ffmpeg_version=ffmpeg["version"], ffmpeg_audio=ffmpeg)
        with tempfile.TemporaryDirectory(prefix="hdusign-check-") as temporary:
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
                    page.set_content("<title>HDUSign</title><p>课堂辅助</p>")
                    if page.title() != "HDUSign":
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
