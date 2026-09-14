"""Download exactly the FFmpeg source authenticated by the pinned release key.

The build repeats detached-signature verification with an isolated GPG home.
This fetch step uses the already authenticated file hashes and never extracts
or runs downloaded source. Only the three fixed HTTPS URLs are accepted.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import urllib.request


ROOT = Path(__file__).resolve().parent


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main() -> None:
    lock = json.loads((ROOT / "source-lock.json").read_text(encoding="utf-8"))
    downloads = ROOT / "downloads"
    downloads.mkdir(exist_ok=True)
    sums = []
    for entry in lock["files"]:
        name, url, expected = entry["name"], entry["url"], entry["sha256"]
        if Path(name).name != name or not url.startswith("https://ffmpeg.org/"):
            raise ValueError("Unexpected source location")
        path = downloads / name
        if not path.is_file() or sha256(path) != expected:
            partial = path.with_suffix(path.suffix + ".part")
            print(f"Downloading {name}", flush=True)
            try:
                with urllib.request.urlopen(url, timeout=60) as response, partial.open("wb") as stream:
                    if not response.url.startswith("https://ffmpeg.org/"):
                        raise ValueError("Source redirected outside the pinned HTTPS origin")
                    while chunk := response.read(1024 * 1024):
                        stream.write(chunk)
                if sha256(partial) != expected:
                    raise ValueError(f"SHA256 mismatch: {name}")
                partial.replace(path)
            finally:
                partial.unlink(missing_ok=True)
        sums.append(f"{expected}  {name}\n")
        print(f"Verified SHA256: {name}", flush=True)
    (downloads / "SHA256SUMS").write_text("".join(sums), encoding="ascii", newline="\n")


if __name__ == "__main__":
    main()
