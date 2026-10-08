"""Reject missing, stale, or incomplete Android acceptance evidence."""

import argparse
import hashlib
import json
import sys
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.startup_config import STARTUP_MODES

REQUIRED_CHECKS = (
    "startup", "media-output", "story-save-recovery", "renderers-background-resume",
    "capabilities", "fresh-process-storage", "keyboard-frame-profile",
    "deep-links-back", "force-stop-storage", "application-records", "diagnostics",
)
REQUIRED_RECEIPTS = (
    "apk-inspection.json", "startup.json", "device-environment.json", "media-output.json",
    "audio-output.json", "native-animation.json", "story-experience.json",
    "tactics-experience.json", "storage-persistence.json", "keyboard-viewport.json",
    "flutter-frame-profile.json", "records-persistence.json", "diagnostics.json",
)


def evidence_hashes(output):
    hashes = {}
    for name in REQUIRED_RECEIPTS:
        data = (output / name).read_bytes()
        if not json.loads(data):
            raise RuntimeError("Empty acceptance receipt: " + name)
        hashes[name] = hashlib.sha256(data).hexdigest()
    return hashes


def verify_acceptance(output, startup_mode, source_sha=None):
    receipt = json.loads((output / "acceptance.json").read_text())
    if (receipt.get("status") != "passed" or receipt.get("skipped") != []
            or receipt.get("checks") != list(REQUIRED_CHECKS)):
        raise RuntimeError("Android acceptance checks must all run and pass without skips")
    if receipt.get("startup_mode") != startup_mode:
        raise RuntimeError("Android acceptance used the wrong startup mode")
    if source_sha is not None and receipt.get("source_sha") != source_sha:
        raise RuntimeError("Android acceptance used the wrong build source")
    if receipt.get("receipts") != evidence_hashes(output):
        raise RuntimeError("Android acceptance evidence changed or is incomplete")
    apk = json.loads((output / "apk-inspection.json").read_text())
    startup = json.loads((output / "startup.json").read_text())
    if (receipt.get("apk_sha256") != apk.get("sha256")
            or apk.get("startup_mode") != startup_mode or startup.get("mode") != startup_mode):
        raise RuntimeError("Android acceptance does not identify the inspected APK and startup")
    if json.loads((output / "diagnostics.json").read_text()).get("errors") != {}:
        raise RuntimeError("Android acceptance is missing required diagnostics")
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--startup-mode", choices=STARTUP_MODES, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    verify_acceptance(args.output, args.startup_mode, args.source_sha)
    print("Verified complete Android acceptance: mode=" + args.startup_mode)


if __name__ == "__main__":
    main()
