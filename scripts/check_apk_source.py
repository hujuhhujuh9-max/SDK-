"""Reject reuse of an APK when its build inputs differ from the harness source."""

import argparse
import fnmatch
import json
from pathlib import Path

INPUTS = (
    ".github/workflows/build-android.yml", "build_android.py", "prepare.py",
    "sdk-lock.json", "requirements-build.txt", "android/*", "assets/*",
    "flutter/*", "game/*", "runtime/*", "scripts/check_flet_bridge.py",
    "scripts/check_apk.py", "scripts/flet_protocol.py",
    "scripts/startup_config.py",
)


def apk_inputs_changed(comparison):
    if not isinstance(comparison, dict):
        return True
    if comparison.get("status") not in ("ahead", "identical"):
        return True
    files = comparison.get("files")
    # GitHub caps compare file lists at 300. Treat truncation as incompatible.
    if not isinstance(files, list) or len(files) >= 300:
        return True
    if any(not isinstance(item, dict) or not isinstance(item.get("filename"), str)
           or not isinstance(item.get("previous_filename", ""), str) for item in files):
        return True
    return any(fnmatch.fnmatch(path, pattern)
               for item in files
               for path in (item["filename"], item.get("previous_filename", ""))
               for pattern in INPUTS)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("comparison", type=Path)
    args = parser.parse_args()
    changed = apk_inputs_changed(json.loads(args.comparison.read_text()))
    if changed:
        print("APK inputs changed or source identity is unverified; a compatible build is required.")
    else:
        print("APK inputs unchanged; the latest successful APK is compatible with this harness.")
    raise SystemExit(1 if changed else 0)


if __name__ == "__main__":
    main()
