"""Download one SDK archive and verify its manifest before storing it with Git LFS."""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from urllib.parse import urlparse


def download(component):
    manifest_path = Path("components") / component / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    target = Path(manifest["archive_path"])
    if target.parent != manifest_path.parent / "archives":
        raise ValueError("Archive path must belong to this component")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        with target.open("rb") as stream:
            pointer = stream.read(80).startswith(b"version https://git-lfs.github.com/spec/v1\n")
        if pointer:
            subprocess.run(["git", "lfs", "pull", "--include=" + str(target)], check=True)
        verify(target, manifest)
        return
    endpoint = manifest["source"]["download_endpoint"]
    if urlparse(endpoint).hostname != "www.swisstransfer.com":
        raise ValueError("Unexpected transfer host")
    response = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--location",
         "--retry", "3", "--connect-timeout", "30", "--max-time", "120", endpoint],
        check=True, capture_output=True, text=True,
    )
    result = json.loads(response.stdout)
    if result.get("result") != "success":
        raise ValueError("Transfer no longer provides this file")
    url = result["data"]["url"]
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname.endswith(".infomaniak.cloud"):
        raise ValueError("Unexpected download host")
    temporary = target.with_name(target.name + ".partial")
    print(f"Downloading {manifest['name']} ({manifest['size_bytes']} bytes)", flush=True)
    subprocess.run(
        ["curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
         "--connect-timeout", "30", "--max-time", "1200", "--output", str(temporary), url],
        check=True,
    )
    verify(temporary, manifest)
    temporary.replace(target)
    print(f"Verified {target}: sha256 {manifest['sha256']}", flush=True)


def verify(path, manifest):
    if path.stat().st_size != manifest["size_bytes"]:
        raise ValueError("Archive byte count differs from the source manifest")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Archive SHA-256 differs from the source manifest")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--component", choices=["flutter", "renpy", "renpy-rapt"], required=True)
    arguments = parser.parse_args()
    download(arguments.component)
