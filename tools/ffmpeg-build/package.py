"""Create a matched portable binary/source pair; never upload or publish it."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import tarfile
import zipfile

from fetch_sources import main as verify_downloads
from verify import build_path


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parent.parent
EPOCH = 1781664539
STEM = "ffmpeg-8.1.2-echosign-audio"
RECIPE_FILES = ("README.md", "source-lock.json", "fetch_sources.py", "build.sh", "verify.py", "package.py")


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def source_archive(output: Path, record: Path | None) -> None:
    inputs = [(ROOT / name, "recipe/tools/ffmpeg-build/" + name) for name in RECIPE_FILES]
    inputs.append((REPOSITORY / ".github/workflows/ffmpeg-audio-windows.yml",
                   "recipe/.github/workflows/ffmpeg-audio-windows.yml"))
    lock = json.loads((ROOT / "source-lock.json").read_text())
    inputs.extend((ROOT / "downloads" / entry["name"], "upstream/" + entry["name"]) for entry in lock["files"])
    if record:
        inputs.extend((path, "build-record/" + path.relative_to(record).as_posix())
                      for path in sorted(record.rglob("*")) if path.is_file())
    with tarfile.open(output, "w:xz") as archive:
        for path, name in inputs:
            data = path.read_bytes()
            item = tarfile.TarInfo(STEM + "/" + name)
            item.size, item.mtime = len(data), EPOCH
            item.mode = 0o755 if path.name == "build.sh" else 0o644
            archive.addfile(item, io.BytesIO(data))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-only", action="store_true", help="Package verified inputs before a binary has been built")
    args = parser.parse_args()
    verify_downloads()
    dist = ROOT / "dist"
    dist.mkdir(exist_ok=True)
    if args.source_only:
        archive = dist / (STEM + "-source-inputs.tar.xz")
        source_archive(archive, None)
        (dist / "SOURCE-INPUTS.SHA256SUMS").write_text(f"{sha256(archive)}  {archive.name}\n", encoding="ascii")
        print(archive)
        return

    build = build_path()
    record, executable = build / "record", build / "out/ffmpeg.exe"
    verification = json.loads((record / "verification.json").read_text())
    if not (verification["ok"] and verification["tls_ci"] and verification.get("https")
            and verification["binary_sha256"] == sha256(executable)):
        raise RuntimeError("A matching successful audio and hosted-runner TLS check is required")
    archive = dist / (STEM + "-source.tar.xz")
    source_archive(archive, record)
    package = build / "package/ffmpeg"
    package.mkdir(parents=True, exist_ok=True)
    shutil.copy2(executable, package / "ffmpeg.exe")
    for name in ("version.txt", "buildconf.txt"):
        shutil.copy2(record / name, package / name)
    shutil.copy2(build / "ffmpeg-8.1.2/COPYING.LGPLv2.1", package / "LICENSE")
    shutil.copytree(record / "toolchain-licenses", package / "licenses/toolchain", dirs_exist_ok=True)
    lock = json.loads((ROOT / "source-lock.json").read_text())
    metadata = {
        "component": "FFmpeg", "version": lock["version"] + "-echosign-audio",
        "build_name": "echosign-audio", "license": "LGPL-2.1-or-later",
        "tls_backend": "schannel", "tls_verify_required": True, "ca_store": "Windows",
        "binary_sha256": sha256(executable),
        "source_archive": {"name": archive.name, "sha256": sha256(archive)},
        "corresponding_source_included": True, "upstream_source": lock,
        "configure_flags": (record / "configure-args.txt").read_text().splitlines(),
        "verification": verification,
    }
    (package / "SOURCE.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    (package / "README.txt").write_text(
        "EchoSign portable audio FFmpeg 8.1.2\n"
        "Built from the official FFmpeg source with internal audio codecs and Windows Schannel.\n"
        "No external codec libraries, OpenSSL, GPL or nonfree FFmpeg options are enabled.\n"
        "Use -tls_verify 1 for HTTPS. Trust comes from the Windows certificate store.\n"
        "FFmpeg's Schannel backend does not use -ca_file.\n"
        "SOURCE.json identifies the binary, exact source archive, build configuration and checks.\n"
        "The source archive is a separate release asset and must be distributed alongside this ZIP.\n",
        encoding="utf-8")
    shutil.copy2(record / "license-notice.txt", package / "license-notice.txt")
    binary_zip = dist / (STEM + "-win64.zip")
    with zipfile.ZipFile(binary_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as output:
        for file in sorted(package.rglob("*")):
            if file.is_file():
                output.write(file, "ffmpeg/" + file.relative_to(package).as_posix())
    shutil.copy2(package / "SOURCE.json", dist / "SOURCE.json")
    (dist / "SHA256SUMS").write_text(
        "".join(f"{sha256(file)}  {file.name}\n" for file in (binary_zip, archive, dist / "SOURCE.json")),
        encoding="ascii")
    print(json.dumps({"binary": str(binary_zip), "source": str(archive), "metadata": str(dist / "SOURCE.json")}, indent=2))


if __name__ == "__main__":
    main()
