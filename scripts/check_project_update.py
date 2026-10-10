"""Verify a signed release update retains Records and a real story checkpoint."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_apk import inspect_apk
from scripts.check_project_device import (
    ACTIVITY, FORBIDDEN_PERMISSIONS, LOCATION_SERVICE, ProjectDevice,
    check_project_device, command, native_dialogue_pixels, release_identity,
)
from scripts.device_smoke import framebuffer_shape


APK_PREFIX = "runner-org-renfletpy-update35-release"
BUILD_RECEIPT = "apk-builds-org-renfletpy-update35-release.json"


def inspect_update_pair(pair, *, source_sha, aapt, apksigner, abis=("x86_64",), run=command):
    """Reject incompatible packages, signatures or versions before touching Android."""
    pair = Path(pair)
    versions = {}
    suffix = "-x86_64" if tuple(abis) == ("x86_64",) else ""
    for stage in ("baseline", "update"):
        directory = pair / stage
        metadata = json.loads((directory / BUILD_RECEIPT).read_text())
        if metadata.get("signing") != "signed" or metadata.get("build_type") != "release":
            raise RuntimeError("The update pair must contain signed release builds")
        apk = directory / (APK_PREFIX + suffix + ".apk")
        inspection = inspect_apk(apk, abis, "app", build_type="release", project=metadata["project"])
        if inspection["source_sha"] != source_sha or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
            raise RuntimeError("Update APK source differs from the expected source")
        signature = run(apksigner, "verify", "--verbose", "--print-certs", apk)
        certificates = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})", signature)
        if not certificates:
            raise RuntimeError("Update APK has no verified signing certificate")
        identity = release_identity(run(aapt, "dump", "badging", apk),
                                    run(aapt, "dump", "permissions", apk),
                                    run(aapt, "dump", "xmltree", apk, "AndroidManifest.xml"),
                                    inspection["project"], apk=apk)
        versions[stage] = {"apk": str(apk), "inspection": inspection, "identity": identity,
                           "certificate_sha256": [value.lower() for value in certificates]}
    before, after = versions["baseline"], versions["update"]
    if before["certificate_sha256"] != after["certificate_sha256"]:
        raise RuntimeError("Update APKs do not share the same signing certificate")
    if before["identity"]["package"] != after["identity"]["package"]:
        raise RuntimeError("Update APKs do not share the same package")
    if after["identity"]["version_code"] <= before["identity"]["version_code"]:
        raise RuntimeError("Update version_code must increase")
    old_project, new_project = before["inspection"]["project"], after["inspection"]["project"]
    if any(old_project[key] != new_project[key] for key in
           ("game_files", "asset_files", "icon_sha256", "app_home")):
        raise RuntimeError("The update fixture must retain its native story and assets")
    return versions


def installed_update(device, version, output, stage):
    """Bind the installed version and bytes to the inspected APK and retain its UID."""
    identity = version["identity"]
    installed = device.adb("shell", "dumpsys", "package", device.package)
    (output / (stage + "-installed-package.txt")).write_text(installed)
    uid = re.search(r"\buserId=(\d+)\b", installed)
    if (not uid or int(uid.group(1)) < 10000
            or "Package [" + device.package + "]" not in installed
            or not re.search(r"\bversionCode=" + str(identity["version_code"]) + r"\b", installed)
            or not re.search(r"^\s*versionName=" + re.escape(identity["version_name"]) + r"\s*$", installed, re.M)
            or "pkgFlags=[" not in installed or "DEBUGGABLE" in installed
            or any(permission in installed for permission in FORBIDDEN_PERMISSIONS)
            or LOCATION_SERVICE in installed):
        raise RuntimeError("Installed update identity or permissions differ")
    paths = device.adb("shell", "pm", "path", device.package).splitlines()
    if len(paths) != 1 or not re.fullmatch(r"package:/data/app/[A-Za-z0-9_./~=+\-]+/base\.apk", paths[0]):
        raise RuntimeError("Expected one installed update APK")
    digest = device.adb("shell", "sha256sum", paths[0][8:]).split()[0]
    if digest != version["inspection"]["sha256"]:
        raise RuntimeError("Installed update bytes differ from the inspected APK")
    return {"uid": uid.group(1), "sha256": digest, "version_code": identity["version_code"],
            "version_name": identity["version_name"]}


def wait_action(device, marker, action, pid):
    return device.wait(lambda: re.search(re.escape(marker) + " action=" + action
                                        + r" [^\n]*pid=" + re.escape(pid) + r"\b", device.logs()),
                       "native " + action + " in process " + pid)


def check_project_update(pair, output, *, source_sha, aapt, apksigner, run=command):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / "project-update.json"
    receipt_path.unlink(missing_ok=True)
    versions = inspect_update_pair(pair, source_sha=source_sha, aapt=aapt, apksigner=apksigner, run=run)
    before, after = versions["baseline"], versions["update"]
    package = before["identity"]["package"]
    baseline = check_project_device(
        before["apk"], package, "Update test - version 1", output / "baseline",
        source_sha=source_sha, project_input_sha256=before["inspection"]["project"]["input_sha256"],
        story_marker="SDK_RUNNER_PROJECT_STORY", aapt=aapt, apksigner=apksigner, expected_api=35, run=run)
    device = ProjectDevice(package, output, run)
    try:
        old_pid = baseline["restarted_pid"]
        old_install = installed_update(device, before, output, "baseline")
        device.tap(device.control("Back", scroll="up"))
        device.control("Update test - version 1")
        device.tap(device.control("Start story", scroll="up"))
        wait_action(device, "SDK_RUNNER_APP_STORY", "started", old_pid)
        device.wait(lambda: native_dialogue_pixels(
            device.adb("exec-out", "screencap", binary=True), device.viewport()), "baseline native dialogue")
        frame = device.adb("exec-out", "screencap", binary=True)
        width, height, _ = framebuffer_shape(frame)
        device.adb("shell", "input", "tap", width // 2, height * 7 // 8)
        for choice in ("Keep a copy", "Share it with Mira"):
            if device.control(choice).get("enabled") != "true":
                raise RuntimeError("The baseline story choice is already answered")
        device.screenshot("baseline-unanswered-choice")
        device.adb("shell", "input", "keyevent", "4")
        device.tap(device.control("Quick save"))
        wait_action(device, "SDK_RUNNER_SAVE", "saved", old_pid)
        device.control("Saved. You can return here")
        device.tap(device.control("Resume"))
        device.tap(device.control("Share it with Mira"))
        device.wait(lambda: native_dialogue_pixels(
            device.adb("exec-out", "screencap", binary=True), device.viewport()), "completed native dialogue")
        device.adb("shell", "input", "tap", width // 2, height * 7 // 8)
        wait_action(device, "SDK_RUNNER_APP_STORY", "completed", old_pid)
        device.control("You shared the lighthouse note.")
        device.screenshot("baseline-completed-story")
        (output / "baseline-logcat.txt").write_text(device.logs())
        device.adb("shell", "am", "force-stop", package)
        device.wait(lambda: device.pid() is None, "baseline process stopped")
        # Same package/key and a higher version: no uninstall or data clearing.
        device.adb("install", "-r", after["apk"], timeout=180)
        new_install = installed_update(device, after, output, "update")
        if new_install["uid"] != old_install["uid"]:
            raise RuntimeError("The update replaced the application's Android UID")
        device.adb("logcat", "-c")
        device.adb("shell", "am", "start", "-W", "-n", package + "/" + ACTIVITY)
        new_pid = device.wait(device.pid, "updated app process")
        if new_pid in (baseline["source_pid"], old_pid):
            raise RuntimeError("The updated app did not launch in a fresh process")
        device.home("Update test - version 2", "updated-home")
        device.wait(lambda: device.started(new_pid), "updated same-process runtime startup")
        title = baseline["checks"]["records_after_reopening"]["title"]
        device.tap(device.control("Application records", scroll="up"))
        device.control("Records loaded", scroll="down")
        device.control("Title: " + title, scroll="down")
        device.screenshot("updated-record")
        device.tap(device.control("Back", scroll="up"))
        device.tap(device.control("Resume story", scroll="up"))
        wait_action(device, "SDK_RUNNER_APP_STORY", "restored phase=active", new_pid)
        for choice in ("Keep a copy", "Share it with Mira"):
            if device.control(choice).get("enabled") != "true":
                raise RuntimeError("The update did not restore the unanswered story choice")
        if device.pid() != new_pid:
            raise RuntimeError("Restoring the story restarted the updated app")
        device.screenshot("updated-restored-choice")
        receipt = {"source_sha": source_sha, "baseline": before, "update": after,
                   "device": baseline["device"], "baseline_pid": old_pid, "updated_pid": new_pid,
                   "baseline_install": old_install, "updated_install": new_install,
                   "baseline_checks": baseline["checks"],
                   "checks": {"same_key_in_place_update": True, "records_after_update": {"title": title},
                              "story_after_update": {"quick_saved_unanswered_choice": True,
                                                     "completed_before_update": True,
                                                     "restored_unanswered_choice": True}},
                   "skips": 0, "success": True}
    finally:
        primary_error = sys.exc_info()[1]
        try:
            if primary_error is not None:
                device.screenshot("update-failed")
            (output / "update-logcat.txt").write_text(device.logs())
        except Exception as error:
            if primary_error is None:
                raise
            print("Update diagnostic collection also failed: " + str(error), flush=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Passed: same-key release update retains Records and a native story checkpoint", flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pair", type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--aapt", type=Path, required=True)
    parser.add_argument("--apksigner", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(".android-build/project-update-check"))
    args = parser.parse_args()
    check_project_update(args.pair, args.output, source_sha=args.source_sha,
                         aapt=args.aapt, apksigner=args.apksigner)


if __name__ == "__main__":
    main()
