"""Build a self-contained Windows ZIP from public files and pinned dependencies."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from echosign import __version__
from echosign.runtime import (ASR_FILES, ASR_FOLDER, SEMANTIC_FILES,
                              SEMANTIC_FOLDER, SEMANTIC_MODEL)

BUILD = ROOT / "build"
RUNTIME = BUILD / "portable-runtime"
DIST = BUILD / "release-dist"
VERSION = f"v{__version__}"
OUTPUT = ROOT / "dist" / "releases" / VERSION


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def clear_generated(directory: Path) -> None:
    """Only remove tool-owned output below this checkout's build directory."""
    target = directory.resolve()
    boundary = BUILD.resolve()
    if target == boundary or not target.is_relative_to(boundary):
        raise ValueError(f"Refusing to clear a directory outside build/: {target}")
    if directory.exists():
        shutil.rmtree(directory)


def require_files(directory: Path, names) -> None:
    missing = [name for name in names if not (directory / name).is_file()]
    if missing:
        raise RuntimeError(f"Missing files in {directory}: {', '.join(missing)}")


def copy_files(source: Path, destination: Path, names) -> None:
    require_files(source, names)
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(source / name, destination / name)


def prepare_browsers() -> None:
    import playwright
    from playwright.sync_api import sync_playwright

    package = Path(playwright.__file__).resolve().parent / "driver" / "package"
    registry = json.loads((package / "browsers.json").read_text(encoding="utf-8"))
    components = [entry for entry in registry["browsers"]
                  if entry["name"] in {"chromium", "ffmpeg", "winldd"}]
    browsers = RUNTIME / "browsers"
    clear_generated(browsers)
    browsers.mkdir(parents=True)
    with sync_playwright() as driver:
        # Resolve the cache with this exact Playwright version, not another install.
        cache = Path(driver.chromium.executable_path).parents[2]
    for component in components:
        name = f"{component['name']}-{component['revision']}"
        if (cache / name).is_dir():
            shutil.copytree(cache / name, browsers / name)
    if any(not (browsers / f"{c['name']}-{c['revision']}").is_dir() for c in components):
        env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(browsers))
        subprocess.run([sys.executable, "-m", "playwright", "install", "--no-shell", "chromium"],
                       cwd=ROOT, env=env, check=True)
    # Playwright's cache bookkeeping is unrelated to the portable application.
    for extra in browsers.iterdir():
        if extra.name.startswith("."):
            if extra.is_dir():
                clear_generated(extra)
            else:
                extra.unlink()
    chromium = next(c for c in components if c["name"] == "chromium")
    require_files(browsers / f"chromium-{chromium['revision']}" / "chrome-win64", ["chrome.exe"])
    print(f"Bundled Chromium {chromium['browserVersion']}", flush=True)


def prepare_semantic_model() -> None:
    from fastembed import TextEmbedding

    source = ROOT / "models" / SEMANTIC_FOLDER
    if not all((source / name).is_file() for name in SEMANTIC_FILES):
        try:
            model = TextEmbedding(model_name=SEMANTIC_MODEL, local_files_only=True, lazy_load=True)
        except (ValueError, OSError):
            model = TextEmbedding(model_name=SEMANTIC_MODEL,
                                  cache_dir=str(RUNTIME / "model-cache"), lazy_load=True)
        source = Path(model.model._model_dir)
    copy_files(source, RUNTIME / "models" / SEMANTIC_FOLDER, SEMANTIC_FILES)
    print("Prepared local semantic model", flush=True)


def source_hashes() -> dict[str, str]:
    paths = [ROOT / name for name in ("requirements.txt", "config.example.yaml", "README.md", "LICENSE")]
    for folder in ("echosign", "packaging", "assets", "docs", "tools"):
        paths.extend(p for p in (ROOT / folder).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    return {p.relative_to(ROOT).as_posix(): sha256(p) for p in sorted(paths)}


def copy_dependency_licenses(destination: Path) -> None:
    from packaging.requirements import Requirement

    pending = [line.strip() for line in (ROOT / "requirements.txt").read_text().splitlines()
               if line.strip() and not line.startswith("#")] + ["pyinstaller"]
    visited = set()
    while pending:
        requirement = Requirement(pending.pop())
        if requirement.marker and not requirement.marker.evaluate({"extra": ""}):
            continue
        distribution = importlib.metadata.distribution(requirement.name)
        name = distribution.metadata["Name"]
        if name in visited:
            continue
        visited.add(name)
        pending.extend(distribution.requires or [])
        for path in distribution.files or []:
            if ".." in path.parts or not path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")):
                continue
            source = Path(distribution.locate_file(path))
            if source.is_file():
                target = destination / name / path
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
    python_root = Path(sys._base_executable).resolve().parent
    for name in ("LICENSE.txt", "LICENSE"):
        if (python_root / name).is_file():
            shutil.copy2(python_root / name, destination / "Python-LICENSE.txt")
            break


def verify_archive(archive: Path) -> dict:
    """Exercise the extracted exe with empty caches, a minimal PATH and no downloads."""
    with tempfile.TemporaryDirectory(prefix="解压 验证 ", dir=BUILD) as temporary:
        workspace = Path(temporary)
        with zipfile.ZipFile(archive) as package:
            if bad := package.testzip():
                raise RuntimeError(f"ZIP checksum failed: {bad}")
            package.extractall(workspace)
        profile = workspace / "empty-user"
        local = profile / "AppData" / "Local"
        roaming = profile / "AppData" / "Roaming"
        temp = local / "Temp"
        temp.mkdir(parents=True)
        roaming.mkdir(parents=True)
        env = dict(os.environ)
        for name in ("PYTHONHOME", "PYTHONPATH", "VIRTUAL_ENV"):
            env.pop(name, None)
        system_root = Path(os.environ["SystemRoot"])
        env.update(USERPROFILE=str(profile), LOCALAPPDATA=str(local), APPDATA=str(roaming),
                   TEMP=str(temp), TMP=str(temp), HF_HOME=str(profile / "huggingface"),
                   FASTEMBED_CACHE_PATH=str(profile / "fastembed"), HF_HUB_OFFLINE="1",
                   PLAYWRIGHT_BROWSERS_PATH=str(profile / "absent-browser-cache"),
                   PATH=os.pathsep.join([str(system_root / "System32"), str(system_root)]))
        report = workspace / "runtime.json"
        result = subprocess.run([str(workspace / "EchoSign" / "EchoSign.exe"),
                                 "--check-runtime", str(report)],
                                cwd=workspace, env=env, capture_output=True, timeout=240,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        if not report.is_file():
            raise RuntimeError(f"Runtime check exited with {result.returncode} without a report")
        content = json.loads(report.read_text(encoding="utf-8"))
        (BUILD / f"runtime-{VERSION}.json").write_text(
            json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        if result.returncode or not content["ok"]:
            raise RuntimeError(content.get("error", "Runtime check failed"))
        if content["version"] != __version__:
            raise RuntimeError("Packaged version does not match the source")
        return content


def main() -> None:
    if sys.platform != "win32" or struct.calcsize("P") != 8:
        raise SystemExit("Build with 64-bit Python on Windows.")
    BUILD.mkdir(exist_ok=True)
    require_files(ROOT / "models" / ASR_FOLDER, ASR_FILES)
    sources = source_hashes()
    prepare_browsers()
    prepare_semantic_model()
    clear_generated(DIST)
    log = BUILD / f"build-{VERSION}.log"
    print(f"Building {VERSION}; PyInstaller output: {log}", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        subprocess.run([sys.executable, "-X", "utf8", "-m", "PyInstaller", "--noconfirm", "--clean",
                        "--distpath", str(DIST), "--workpath", str(BUILD / "pyinstaller"),
                        str(ROOT / "packaging" / "EchoSign.spec")],
                       cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=True)
    app = DIST / "EchoSign"
    copy_files(ROOT, app, ["README.md", "LICENSE", "config.example.yaml"])
    shutil.copytree(ROOT / "docs", app / "docs")
    shutil.copytree(ROOT / "assets" / "screenshots", app / "assets" / "screenshots")
    copy_files(ROOT / "packaging", app, ["THIRD_PARTY_NOTICES.md"])
    shutil.copytree(ROOT / "packaging" / "licenses", app / "licenses")
    copy_dependency_licenses(app / "licenses")
    copy_files(ROOT / "models" / ASR_FOLDER, app / "models" / ASR_FOLDER, ASR_FILES)
    copy_files(RUNTIME / "models" / SEMANTIC_FOLDER, app / "models" / SEMANTIC_FOLDER, SEMANTIC_FILES)
    if source_hashes() != sources:
        raise RuntimeError("Source files changed during the build; rebuild before publishing")

    OUTPUT.mkdir(parents=True, exist_ok=True)
    archive = OUTPUT / f"EchoSign-{VERSION}-win64.zip"
    print(f"Creating {archive.name}", flush=True)
    forbidden = {"config.yaml", "secrets_local.json", "session_local.json", "browser_profile"}
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as package:
        for path in sorted(app.rglob("*")):
            relative = path.relative_to(DIST)
            if any(part in forbidden for part in relative.parts) or path.suffix == ".jsonl":
                raise RuntimeError(f"Private runtime data must not be packaged: {relative}")
            if path.is_file():
                package.write(path, relative.as_posix())
    print("Checking the extracted application with empty user caches", flush=True)
    runtime = verify_archive(archive)
    checksum = sha256(archive)
    (OUTPUT / "SHA256SUMS.txt").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    manifest = {"version": VERSION, "archive": str(archive.relative_to(ROOT)), "sha256": checksum,
                "bytes": archive.stat().st_size, "source_hashes": sources, "runtime": runtime,
                "dependencies": {name: importlib.metadata.version(name)
                                 for name in ("pyinstaller", "playwright", "fastembed", "sherpa-onnx")}}
    (BUILD / f"release-{VERSION}-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: manifest[key] for key in ("version", "archive", "bytes", "sha256")},
                     ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
