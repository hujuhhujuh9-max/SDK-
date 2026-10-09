"""Identify verified CI cache state without changing the build's reuse checks."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_android as build


def verified_receipt(cache):
    try:
        marker = cache / "manifest.json"
        if cache.is_symlink() or marker.is_symlink():
            return ""
        receipt = json.loads(marker.read_text())
        fingerprint = receipt.get("fingerprint") if isinstance(receipt, dict) else None
        if (not isinstance(fingerprint, str) or not re.fullmatch(r"[0-9a-f]{64}", fingerprint)
                or not build.reusable_flutter_repo(cache, fingerprint)):
            return ""
        return build.flutter_cache_fingerprint(receipt)
    except (OSError, ValueError):
        return ""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("toolchain", "candidate", "publish"))
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".android-build")
    args = parser.parse_args()
    if args.phase == "toolchain":
        print("fingerprint=" + build.flutter_cache_fingerprint(build.flutter_toolchain()))
    else:
        receipt = verified_receipt(args.cache_dir / "flutter-aar")
        if args.phase == "publish" and not receipt:
            parser.error("Refusing to publish an invalid Flutter AAR repository")
        print("receipt=" + receipt)


if __name__ == "__main__":
    main()
