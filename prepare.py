#!/usr/bin/env python3
"""Prepare pinned component inputs for an Android application built on Linux."""

import argparse
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent
LOCK = ROOT / "sdk-lock.json"


def verify_archive(path, spec):
    if path.stat().st_size != spec["size_bytes"]:
        raise ValueError(f"Wrong archive size: {path.name}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != spec["sha256"]:
        raise ValueError(f"Archive checksum mismatch: {path.name}")


def extract_archive(path, destination, archive_format):
    if archive_format != "zip":
        with tarfile.open(path, "r|*") as archive:
            archive.extractall(destination, filter="data")
        return
    with zipfile.ZipFile(path) as archive:
        for entry in archive.infolist():
            target = (destination / entry.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError(f"Archive path leaves its component: {entry.filename}")
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError("ZIP symlinks are not supported")
            archive.extract(entry, destination)
            if mode & 0o777 and not entry.is_dir():
                target.chmod(mode & 0o777)


class BuildInputs:
    def __init__(self, cache, archives=None, lock=LOCK):
        self.cache = Path(cache).resolve()
        self.archives = Path(archives).resolve() if archives else None
        self.lock = json.loads(Path(lock).read_text())
        self.components = self.lock["components"]

    def sdk_directory(self, component):
        spec = self.components[component]
        return self.cache / "sdks" / (component + "-" + spec["sha256"][:12])

    def sdk_root(self, component):
        return self.sdk_directory(component) / self.components[component]["unpacked_root"]

    def ready(self, component):
        marker = self.sdk_directory(component) / ".installed.json"
        if not marker.is_file() or not self.sdk_root(component).is_dir():
            return False
        installed = json.loads(marker.read_text())
        required_paths = self.components[component].get("required_paths", [])
        return (
            installed.get("sha256") == self.components[component]["sha256"]
            and all((self.sdk_root(component) / path).is_file() for path in required_paths)
        )

    def archive(self, component):
        spec = self.components[component]
        if self.archives:
            path = self.archives / spec["original_filename"]
            if not path.is_file():
                raise FileNotFoundError(f"Missing local archive: {path}")
            verify_archive(path, spec)
            return path
        if not shutil.which("git"):
            raise RuntimeError("Git is required to fetch SDK branches.")
        if subprocess.run(["git", "lfs", "version"], capture_output=True).returncode:
            raise RuntimeError("Git LFS is required. See docs/build-environment.md.")
        source = self.cache / "source.git"
        object_path = source / "lfs" / "objects" / spec["sha256"][:2] / spec["sha256"][2:4] / spec["sha256"]
        if not object_path.is_file():
            command = self.source_command(component)
            pointer = subprocess.check_output(command + ["show", spec["commit"] + ":" + spec["archive_path"]], text=True)
            expected = f"version https://git-lfs.github.com/spec/v1\noid sha256:{spec['sha256']}\nsize {spec['size_bytes']}\n"
            if pointer != expected:
                raise ValueError(f"The locked archive differs from {spec['branch']}")
            subprocess.run(command + ["lfs", "fetch", "--include=" + spec["archive_path"], "--exclude=", "origin", spec["commit"]], check=True)
        verify_archive(object_path, spec)
        return object_path

    def source_command(self, component):
        source = self.cache / "source.git"
        source.parent.mkdir(parents=True, exist_ok=True)
        if not source.exists():
            subprocess.run(["git", "init", "--bare", "--quiet", str(source)], check=True)
            subprocess.run(["git", "--git-dir", str(source), "remote", "add", "origin", self.lock["repository"]], check=True)
        command = ["git", "--git-dir", str(source)]
        commit = self.components[component]["commit"]
        if subprocess.run(command + ["cat-file", "-e", commit + "^{commit}"], capture_output=True).returncode:
            subprocess.run(command + ["fetch", "--depth=1", "--no-tags", "origin", commit], check=True)
        return command

    def branch_file(self, component, path, sha256):
        if not path.startswith("components/" + component + "/"):
            raise ValueError("Build patch must belong to its component branch")
        command = self.source_command(component)
        data = subprocess.check_output(command + ["show", self.components[component]["commit"] + ":" + path])
        if hashlib.sha256(data).hexdigest() != sha256:
            raise ValueError("Component patch differs from its locked checksum")
        return data

    def setup(self, component):
        if component == "renpy-rapt":
            self.setup("renpy")
        spec = self.components[component]
        destination = self.sdk_directory(component)
        if not self.ready(component):
            if destination.exists():
                raise RuntimeError(f"Incomplete SDK folder: {destination}. Use a fresh --cache-dir.")
            archive = self.archive(component)
            destination.parent.mkdir(parents=True, exist_ok=True)
            stage = Path(tempfile.mkdtemp(prefix=component + "-", dir=destination.parent))
            try:
                print(f"Preparing {component} {spec['version']}...", flush=True)
                extract_archive(archive, stage, spec["archive_format"])
                root = stage / spec["unpacked_root"]
                if not root.is_dir():
                    raise ValueError(f"Missing SDK root: {spec['unpacked_root']}")
                for required in spec.get("required_paths", []):
                    if not (root / required).is_file():
                        raise ValueError(f"Missing {component} build input: {required}")
                (stage / ".installed.json").write_text(json.dumps({"component": component, "sha256": spec["sha256"]}) + "\n")
                stage.rename(destination)
            finally:
                if stage.exists():
                    shutil.rmtree(stage)
        if component == "renpy-rapt":
            target = self.sdk_root("renpy") / "rapt"
            source = self.sdk_root(component)
            if target.is_symlink():
                if target.resolve() != source.resolve():
                    raise RuntimeError("The Ren'Py SDK already has a different RAPT link.")
            elif target.exists():
                raise RuntimeError("The Ren'Py SDK already contains a RAPT folder; it was preserved.")
            else:
                target.symlink_to(source, target_is_directory=True)
        print(f"Ready: {component} at {self.sdk_root(component)}", flush=True)
        return self.sdk_root(component)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".android-build")
    parser.add_argument("--archives", type=Path, help="Use previously downloaded SDK archives instead of fetching Git LFS.")
    commands = parser.add_subparsers(dest="action", required=True)
    setup = commands.add_parser("setup", help="Download, verify, and prepare SDKs.")
    setup.add_argument("component", nargs="?", default="all", choices=["all", "flutter", "renpy", "renpy-rapt", "flet"])
    commands.add_parser("status", help="Show SDK installation state without downloading.")
    args = parser.parse_args(argv)
    if sys.version_info < (3, 12):
        parser.error("Python 3.12 or later is required.")
    if sys.platform != "linux":
        parser.error("Build input preparation requires Linux, matching the supplied Flutter SDK.")
    inputs = BuildInputs(args.cache_dir, args.archives)
    if args.action == "status":
        for component, spec in inputs.components.items():
            state = "ready" if inputs.ready(component) else "not installed"
            print(f"{component} {spec['version']}: {state} ({spec['branch']})")
        return 0
    if args.action == "setup":
        for component in inputs.components if args.component == "all" else [args.component]:
            inputs.setup(component)
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError, tarfile.TarError, zipfile.BadZipFile) as error:
        print(f"Error: {error}", file=sys.stderr)
        raise SystemExit(1)
