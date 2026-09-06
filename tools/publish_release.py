"""Publish a verified build to the GitHub origin using in-memory Git credentials."""
from __future__ import annotations

import argparse
import io
import json
import os
from pathlib import Path
import re
import subprocess
import time

import requests

from build_release import BUILD, OUTPUT, ROOT, VERSION, sha256, source_hashes


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def github_session() -> requests.Session:
    token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
        result = subprocess.run(["git", "credential", "fill"],
                                input="protocol=https\nhost=github.com\n\n",
                                capture_output=True, text=True, env=env, timeout=30)
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        token = fields.get("password")
    if not token:
        raise RuntimeError("No GitHub credential is available")
    client = requests.Session()
    client.headers.update({"Authorization": "Bearer " + token,
                           "Accept": "application/vnd.github+json",
                           "X-GitHub-Api-Version": "2022-11-28"})
    return client


def checked(response):
    if not response.ok:
        try:
            message = response.json().get("message", "GitHub API request failed")
        except ValueError:
            message = "GitHub API request failed"
        raise RuntimeError(f"HTTP {response.status_code}: {message}")
    return response.json()


def verify_asset(asset: dict, path: Path) -> None:
    if (asset["state"] != "uploaded" or asset["size"] != path.stat().st_size
            or asset.get("digest") != "sha256:" + sha256(path)):
        raise RuntimeError(f"Uploaded asset does not match the local file: {path.name}")


def find_release(client, api: str, tag: str):
    # Looking up a tag can return 404 for an existing draft. The authenticated
    # release list includes drafts, so a retry must search it before creating one.
    matches = []
    page = 1
    while True:
        releases = checked(client.get(api + "/releases",
                                      params={"per_page": 100, "page": page}, timeout=30))
        matches.extend(release for release in releases if release["tag_name"] == tag)
        if len(releases) < 100:
            break
        page += 1
    if len(matches) > 1:
        raise RuntimeError(f"Multiple releases exist for {tag}; inspect the drafts before continuing")
    return matches[0] if matches else None


def upload_asset(client, api: str, release: dict, path: Path) -> dict:
    try:
        with ProgressFile(path) as stream:
            response = client.post(release["upload_url"].split("{", 1)[0],
                params={"name": path.name}, data=stream, timeout=(30, 600),
                headers={"Content-Type": "application/zip" if path.suffix == ".zip" else "text/plain"})
    except requests.RequestException as exc:
        # The server may have accepted every byte even if its response was lost.
        # Confirm the existing asset before doing any further write operation.
        print("Upload connection interrupted; checking the remote asset", flush=True)
        for attempt in range(3):
            current = checked(client.get(api + f"/releases/{release['id']}", timeout=30))
            uploaded = next((asset for asset in current["assets"]
                             if asset["name"] == path.name and asset["state"] == "uploaded"), None)
            if uploaded:
                verify_asset(uploaded, path)
                return uploaded
            if attempt < 2:
                time.sleep(2)
        raise RuntimeError("Upload could not be confirmed; the release remains a draft") from exc
    uploaded = checked(response)
    verify_asset(uploaded, path)
    return uploaded


class ProgressFile(io.BufferedReader):
    def __init__(self, path: Path):
        super().__init__(io.FileIO(path, "rb"))
        self.label = path.name
        self.total = path.stat().st_size
        self.last_report = time.monotonic()

    def read(self, size=-1):
        data = super().read(size)
        now = time.monotonic()
        if now - self.last_report >= 20:
            print(f"Uploading {self.label}: {self.tell() / self.total:.0%}", flush=True)
            self.last_report = now
        return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--notes", type=Path, required=True, help="UTF-8 release notes")
    args = parser.parse_args()
    notes = args.notes.read_text(encoding="utf-8").strip()
    if not notes:
        raise RuntimeError("Release notes must not be empty")
    if git("status", "--porcelain"):
        raise RuntimeError("Commit all release source changes before publishing")
    commit = git("rev-parse", "HEAD")
    if git("rev-parse", f"{VERSION}^{{commit}}") != commit:
        raise RuntimeError("The version tag must point to the release commit")
    origin = git("remote", "get-url", "origin")
    match = re.fullmatch(r"(?:https://github\.com/|git@github\.com:)([^/]+/[^/]+?)(?:\.git)?", origin)
    if not match:
        raise RuntimeError("The origin remote must be a GitHub repository")
    api = "https://api.github.com/repos/" + match[1]

    manifest = json.loads((BUILD / f"release-{VERSION}-manifest.json").read_text(encoding="utf-8"))
    archive = OUTPUT / f"EchoSign-{VERSION}-win64.zip"
    assets = (archive, OUTPUT / "SHA256SUMS.txt")
    if (manifest["version"] != VERSION or manifest["source_hashes"] != source_hashes()
            or manifest["sha256"] != sha256(archive) or not manifest["runtime"]["ok"]):
        raise RuntimeError("Rebuild the release: source or archive differs from the verified build")
    if assets[1].read_text(encoding="ascii") != f"{manifest['sha256']}  {archive.name}\n":
        raise RuntimeError("The checksum file does not match the archive")

    with github_session() as client:
        branch = git("branch", "--show-current")
        ref = checked(client.get(api + f"/git/ref/heads/{branch}", timeout=30))
        if ref["object"]["sha"] != commit:
            raise RuntimeError("Push the release commit before publishing")
        tag = checked(client.get(api + f"/git/ref/tags/{VERSION}", timeout=30))["object"]
        while tag["type"] == "tag":
            tag = checked(client.get(tag["url"], timeout=30))["object"]
        if tag["sha"] != commit:
            raise RuntimeError("The remote tag does not match the release commit")

        release = find_release(client, api, VERSION)
        if release is None:
            release = checked(client.post(api + "/releases", timeout=30, json={
                "tag_name": VERSION, "target_commitish": commit, "name": f"EchoSign {VERSION}",
                "draft": True, "prerelease": False, "body": notes}))
        print(f"Release {release['id']}: {VERSION}, draft={release['draft']}", flush=True)
        existing = {asset["name"]: asset for asset in release["assets"]}
        if set(existing) - {p.name for p in assets}:
            raise RuntimeError("The release has unexpected assets; inspect it before continuing")
        for path in assets:
            if path.name in existing:
                verify_asset(existing[path.name], path)
                continue
            if not release["draft"]:
                raise RuntimeError("Refusing to modify assets in a published release")
            print(f"Uploading {path.name} ({path.stat().st_size / 1024 ** 2:.1f} MiB)", flush=True)
            upload_asset(client, api, release, path)
        release = checked(client.get(api + f"/releases/{release['id']}", timeout=30))
        remote_assets = {asset["name"]: asset for asset in release["assets"]}
        for path in assets:
            verify_asset(remote_assets[path.name], path)
        if release["draft"]:
            release = checked(client.patch(api + f"/releases/{release['id']}", timeout=30,
                json={"body": notes, "draft": False, "make_latest": "true"}))
        elif release["body"].strip() != notes:
            raise RuntimeError("The published release notes differ; no changes were made")
        print(json.dumps({"url": release["html_url"], "tag": release["tag_name"],
                          "draft": release["draft"], "assets": [
                              {k: asset.get(k) for k in ("name", "size", "digest", "browser_download_url")}
                              for asset in release["assets"]]}, ensure_ascii=False, indent=2), flush=True)


if __name__ == "__main__":
    main()
