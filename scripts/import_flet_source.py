"""Import the pinned official Flet source into this component branch."""

import hashlib
import json
import subprocess
from pathlib import Path


def verify(path, manifest):
    if path.stat().st_size != manifest["size_bytes"]:
        raise ValueError("Flet source byte count differs from the manifest")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != manifest["sha256"]:
        raise ValueError("Flet source SHA-256 differs from the manifest")


def main():
    manifest = json.loads(Path("components/flet/manifest.json").read_text())
    target = Path(manifest["archive_path"])
    if target.parent != Path("components/flet/archives"):
        raise ValueError("Archive must stay inside the Flet component")
    commit = manifest["source"]["commit"]
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("A full upstream commit is required")
    expected_url = "https://codeload.github.com/flet-dev/flet/tar.gz/" + commit
    if manifest["source"]["download_url"] != expected_url:
        raise ValueError("Only the pinned official Flet source URL is supported")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        with target.open("rb") as stream:
            is_pointer = stream.read(80).startswith(b"version https://git-lfs.github.com/spec/v1\n")
        if is_pointer:
            subprocess.run(["git", "lfs", "pull", "--include=" + str(target)], check=True)
        verify(target, manifest)
        return
    temporary = target.with_name(target.name + ".partial")
    try:
        subprocess.run([
            "curl", "--fail", "--location", "--silent", "--show-error", "--retry", "3",
            "--connect-timeout", "30", "--max-time", "1200", "--output", str(temporary),
            expected_url,
        ], check=True)
        verify(temporary, manifest)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    print(f"Verified Flet {manifest['version']}: sha256 {manifest['sha256']}")


if __name__ == "__main__":
    main()
