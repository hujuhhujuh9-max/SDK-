"""Validate the build run and bind an APK to its source and mode receipt."""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if not __package__:
    sys.path.insert(0, str(ROOT))

from scripts.check_apk import SUPPORTED_ABIS, inspect_apk
from scripts.startup_config import STARTUP_MODES

BUILD_WORKFLOWS = {
    ".github/workflows/build-android.yml",
    ".github/workflows/integration-abc.yml",
    ".github/workflows/integration-startup.yml",
}


def validate_build_run(run, repository, current_run_id=None):
    if not isinstance(run, dict):
        raise RuntimeError("APK artifacts require a completed successful build run")
    successful = (run.get("status"), run.get("conclusion")) == ("completed", "success")
    # A reusable build and its dependent device gate share one workflow run.
    # Its build jobs have passed through `needs`; the parent cannot complete
    # until this device job finishes. GitHub can briefly report the parent as
    # pending while a reusable job acquires its concurrency slot.
    current_integration = (current_run_id is not None
                           and str(run.get("id")) == str(current_run_id)
                           and run.get("path") in BUILD_WORKFLOWS - {".github/workflows/build-android.yml"}
                           and run.get("status") in ("in_progress", "pending")
                           and run.get("conclusion") is None)
    if not (successful or current_integration):
        raise RuntimeError("APK artifacts require a completed successful build run")
    if run.get("repository", {}).get("full_name") != repository:
        raise RuntimeError("APK build run belongs to another repository")
    if run.get("path") not in BUILD_WORKFLOWS:
        raise RuntimeError("APK build run is not an approved build workflow")
    if not re.fullmatch(r"[0-9a-f]{40}", run.get("head_sha", "")):
        raise RuntimeError("APK build run is missing its source revision")
    return run["head_sha"]


def verify_apk_receipt(apk, receipt, source_sha, startup_mode, abis):
    if not isinstance(receipt, dict) or receipt.get("source_sha") != source_sha:
        raise RuntimeError("APK receipt does not identify the selected build source")
    if receipt.get("source_dirty") is not False:
        raise RuntimeError("APK receipt must identify an unmodified source checkout")
    if receipt.get("startup_mode") != startup_mode:
        raise RuntimeError("APK receipt has the wrong startup mode")
    if type(receipt.get("identical_shared_entries")) is not int or receipt["identical_shared_entries"] <= 0:
        raise RuntimeError("APK receipt is missing the shared payload verification")
    reports = receipt.get("apks")
    if not isinstance(reports, list):
        raise RuntimeError("APK receipt is missing its package inventory")
    selected = [report for report in reports
                if isinstance(report, dict) and report.get("file") == Path(apk).name]
    if len(selected) != 1:
        raise RuntimeError("APK receipt must identify the downloaded package exactly once")
    actual = inspect_apk(apk, abis, expected_startup_mode=startup_mode)
    if selected[0] != actual:
        raise RuntimeError("Downloaded APK differs from its build receipt")
    return actual


def verify_host_acceptance(receipt, source_sha):
    if (not isinstance(receipt, dict) or receipt.get("source_sha") != source_sha
            or receipt.get("status") != "passed" or type(receipt.get("tests_run")) is not int
            or receipt["tests_run"] <= 0 or receipt.get("skipped") != 0
            or receipt.get("failures") != 0 or receipt.get("errors") != 0):
        raise RuntimeError("APK acceptance requires all host checks to pass without skips on its source")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-metadata", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--current-run-id")
    parser.add_argument("--apk", type=Path)
    parser.add_argument("--receipt", type=Path)
    parser.add_argument("--host-receipt", type=Path)
    parser.add_argument("--startup-mode", choices=STARTUP_MODES, default="story")
    parser.add_argument("--abi", choices=("universal", *SUPPORTED_ABIS), default="x86_64")
    args = parser.parse_args()
    source = validate_build_run(json.loads(args.run_metadata.read_text()), args.repository, args.current_run_id)
    if args.apk is not None or args.receipt is not None:
        if args.apk is None or args.receipt is None or args.host_receipt is None:
            parser.error("--apk, --receipt and --host-receipt must be supplied together")
        verify_host_acceptance(json.loads(args.host_receipt.read_text()), source)
        abis = SUPPORTED_ABIS if args.abi == "universal" else (args.abi,)
        report = verify_apk_receipt(args.apk, json.loads(args.receipt.read_text()),
                                    source, args.startup_mode, abis)
        print("Verified build artifact: " + json.dumps(report, sort_keys=True))
    else:
        print("Verified successful build source: " + source)


if __name__ == "__main__":
    main()
