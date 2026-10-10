"""Probe a signed custom release app on an Android 35 or 36 emulator."""

import argparse
import hashlib
import json
import re
import subprocess
import sys
import time
import uuid
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_apk import inspect_apk
from scripts.device_smoke import framebuffer_shape, pixel_counts


FORBIDDEN_PERMISSIONS = {
    "android.permission." + name for name in (
        "CAMERA", "RECORD_AUDIO", "CAPTURE_AUDIO_OUTPUT", "ACCESS_COARSE_LOCATION",
        "ACCESS_FINE_LOCATION", "ACCESS_BACKGROUND_LOCATION", "FOREGROUND_SERVICE_LOCATION",
        "FOREGROUND_SERVICE_MICROPHONE",
    )
}
LOCATION_SERVICE = "com.baseflow.geolocator.GeolocatorLocationService"
ACTIVITY = "org.sdk.runner.RunnerActivity"


def command(*args, timeout=60, binary=False):
    return subprocess.check_output(list(map(str, args)), timeout=timeout,
                                   stderr=subprocess.STDOUT, text=not binary)


def release_identity(badging, permissions, manifest, project, *, apk=None):
    """Bind compiled manifest identity to the retained project, not its filename."""
    match = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='(.*?)'"
                      r"(?:\s+(?:platformBuildVersion|compileSdkVersion)|$)", badging, re.M)
    label = re.search(r"^application-label:'(.*)'$", badging, re.M)
    activity = re.search(r"^launchable-activity: name='([^']+)'", badging, re.M)
    if (not match or not label or not activity
            or match.groups() != (project["application_id"], str(project["version_code"]), project["version_name"])
            or label.group(1) != project["display_name"] or activity.group(1) != ACTIVITY):
        raise RuntimeError("Release package, version, label or activity differs from supplied project")
    if "application-debuggable" in badging or re.search(
            r"android:debuggable[^\n]*(?:0xffffffff|=\"true\")", manifest):
        raise RuntimeError("Project release APK is debuggable")
    granted = set(re.findall(r"uses-permission(?:-sdk-\d+)?: name='([^']+)'", permissions))
    if granted & FORBIDDEN_PERMISSIONS or LOCATION_SERVICE in manifest:
        raise RuntimeError("Project release requests disabled camera, microphone or location access")
    icons = re.findall(r"^application-icon(?:-\d+)?:'([^']+)'\s*$", badging, re.M)
    icon_hashes = {}
    if project.get("icon_sha256") is not None:
        if not icons or apk is None:
            raise RuntimeError("Missing compiled application icon evidence")
        # AAPT can shorten resource paths (runner_icon.png became res/NN.png).
        # Bind the actual manifest-resolved icon bytes to the retained source hash.
        try:
            with zipfile.ZipFile(apk) as packaged:
                for name in dict.fromkeys(icons):
                    digest = hashlib.sha256(packaged.read(name)).hexdigest()
                    if digest != project["icon_sha256"]:
                        raise RuntimeError("Compiled application icon differs from the supplied icon")
                    icon_hashes[name] = digest
        except (KeyError, OSError, zipfile.BadZipFile) as error:
            raise RuntimeError("Missing compiled application icon bytes") from error
    identity = {"package": match.group(1), "version_code": int(match.group(2)),
            "version_name": match.group(3), "display_name": label.group(1),
            "activity": activity.group(1), "permissions": sorted(granted), "debuggable": False,
            "application_icons": icons}
    if icon_hashes:
        identity["application_icon_sha256"] = icon_hashes
    return identity


def native_dialogue_pixels(frame, viewport):
    """Require the sample story's painted background and native dialogue, with Flet hidden."""
    if (viewport.get("presentation") != "scene" or viewport.get("flet_height") != 0
            or viewport.get("ime_overlap") != 0 or viewport.get("scene_height") != viewport.get("height")):
        return None
    width, height, _ = framebuffer_shape(frame)
    if viewport.get("height") != height:
        return None
    background = pixel_counts(frame, [width // 20, height // 10, width // 5, height // 5],
                              {"native_background": (24, 60, 70)})
    dialogue = pixel_counts(frame, [width // 20, height * 3 // 4, width * 19 // 20, height * 49 // 50],
                            {"dialogue": (244, 240, 232)})
    if background["colors"]["native_background"] < 50 or dialogue["colors"]["dialogue"] < 32:
        return None
    return {"viewport": viewport, "background": background, "dialogue": dialogue}


class ProjectDevice:
    def __init__(self, package, output, run):
        self.package, self.output, self.run = package, output, run

    def adb(self, *args, **options):
        return self.run("adb", *args, **options)

    def wait(self, callback, description, seconds=60):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = callback()
            if result is not None and result is not False:
                return result
            time.sleep(0.25)
        raise RuntimeError("Timed out waiting for " + description)

    def pid(self):
        try:
            values = self.adb("shell", "pidof", self.package).split()
        except subprocess.CalledProcessError as error:
            if error.returncode == 1 and not (error.output or "").strip():
                return None
            raise
        if not values:
            return None
        if len(values) > 1:
            rows = self.adb("shell", "ps", "-A", "-o", "PID,PPID").splitlines()
            parents = dict(row.split() for row in rows if len(row.split()) == 2
                           and all(value.isdigit() for value in row.split()))
            values = [pid for pid in values if pid in parents and parents[pid] not in values]
        if len(values) != 1 or not values[0].isdigit():
            raise RuntimeError("Expected one custom app process")
        return values[0]

    def logs(self):
        return self.adb("logcat", "-d", "-v", "brief")

    def nodes(self, name="project-ui"):
        remote = "/sdcard/renfletpy-project-ui.xml"
        self.adb("shell", "rm", "-f", remote)
        try:
            report = self.adb("shell", "uiautomator", "dump", "--compressed", remote)
        except subprocess.CalledProcessError as error:
            if "could not get idle state" in (error.output or ""):
                return []
            raise
        if "dumped to:" not in report:
            return []
        xml = self.adb("shell", "cat", remote)
        (self.output / (name + ".xml")).write_text(xml)
        return list(ET.fromstring(xml).iter("node"))

    @staticmethod
    def bounds(node):
        value = node.get("bounds", "")
        if not re.fullmatch(r"\[\d+,\d+\]\[\d+,\d+\]", value):
            raise RuntimeError("Missing custom app control bounds")
        left, top, right, bottom = map(int, re.findall(r"\d+", value))
        if left >= right or top >= bottom:
            raise RuntimeError("Custom app control is not visible")
        return [left, top, right, bottom]

    def control(self, text, *, control_class=None, scroll=None):
        def find():
            nodes = [node for node in self.nodes()
                     if node.get("package", self.package) == self.package]
            matches = [node for node in nodes
                       if text in (node.get("text", "") + node.get("content-desc", ""))
                       and node.get("visible-to-user", "true") != "false"
                       and (control_class is None or node.get("class") == control_class)]
            visible = []
            for node in matches:
                try:
                    self.bounds(node)
                    visible.append(node)
                except RuntimeError:
                    continue
            if visible:
                return next((node for node in visible if node.get("class") == "android.widget.Button"),
                            visible[0])
            if scroll:
                view = next((node for node in nodes if node.get("class") == "android.widget.ScrollView"), None)
                if view is not None:
                    left, top, right, bottom = self.bounds(view)
                    x = left + (right - left) * 4 // 5
                    upper, lower = top + (bottom - top) // 4, bottom - (bottom - top) // 4
                    self.adb("shell", "input", "swipe", x, lower if scroll == "down" else upper,
                             x, upper if scroll == "down" else lower, "400")
            return None
        node = self.wait(find, "custom app control " + text)
        self.bounds(node)
        return node

    def tap(self, node):
        if node.get("enabled") == "false":
            raise RuntimeError("Custom app action is disabled")
        left, top, right, bottom = self.bounds(node)
        self.adb("shell", "input", "tap", (left + right) // 2, (top + bottom) // 2)

    def screenshot(self, name):
        png = self.adb("exec-out", "screencap", "-p", binary=True)
        if not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("Missing actual custom app screenshot")
        (self.output / (name + ".png")).write_bytes(png)

    def home(self, heading, name):
        self.control(heading)
        nodes = self.nodes(name)
        matches = [node for node in nodes if node.get("resource-id") in
                   ("project-home-asset", self.package + ":id/project-home-asset")]
        if len(matches) != 1:
            raise RuntimeError("Missing or ambiguous supplied home asset")
        frame = self.adb("exec-out", "screencap", binary=True)
        painted = pixel_counts(frame, self.bounds(matches[0]), {"blue": (21, 101, 192)})
        if painted["colors"]["blue"] < 16:
            raise RuntimeError("Supplied home asset did not paint")
        self.screenshot(name)
        return {"heading": heading, "asset_pixels": painted}

    def viewport(self):
        values = [json.loads(line.split("SDK_RUNNER_VIEWPORT ", 1)[1])
                  for line in self.logs().splitlines() if "SDK_RUNNER_VIEWPORT " in line]
        return values[-1] if values else {}

    def started(self, pid):
        logs = self.logs()
        return all(re.search("SDK_RUNNER_" + name + r" pid=" + pid + r"\b", logs)
                   for name in ("FLUTTER_ATTACHED", "RENPY_READY", "FLET_READY"))


def check_project_device(apk, package, heading, output, *, source_sha, aapt, apksigner,
                         project_input_sha256, story_marker=None, expected_display=(1080, 1920, 420),
                         expected_api=36, run=command):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / "project-device.json"
    receipt_path.unlink(missing_ok=True)
    if type(expected_api) is not int or expected_api not in (35, 36):
        raise ValueError("The project emulator probe supports API 35 and 36")
    if not isinstance(project_input_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", project_input_sha256):
        raise ValueError("Invalid expected project input digest")
    if story_marker is not None and (not isinstance(story_marker, str)
                                    or not re.fullmatch(r"SDK_RUNNER_[A-Z_0-9]+", story_marker)):
        raise ValueError("Invalid native project story marker")
    expected_project = {"application_id": package, "input_sha256": project_input_sha256}
    inspection = inspect_apk(apk, ("x86_64",), "app", build_type="release", project=expected_project)
    if inspection["source_sha"] != source_sha or not re.fullmatch(r"[0-9a-f]{40}", source_sha):
        raise RuntimeError("Custom app APK source does not match expected source")
    if not heading.strip():
        raise ValueError("Custom home heading is required")
    signing = run(apksigner, "verify", "--verbose", "--print-certs", apk)
    certificates = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})", signing)
    if not certificates:
        raise RuntimeError("Custom release APK has no verified signing certificate")
    (output / "project-apk-signature.txt").write_text(signing)
    badging = run(aapt, "dump", "badging", apk)
    permissions = run(aapt, "dump", "permissions", apk)
    manifest = run(aapt, "dump", "xmltree", apk, "AndroidManifest.xml")
    (output / "apk-inspection.json").write_text(json.dumps(inspection, indent=2) + "\n")
    (output / "project-apk-manifest.txt").write_text(badging + "\n" + permissions + "\n" + manifest)
    identity = release_identity(badging, permissions, manifest, inspection["project"], apk=apk)
    device = ProjectDevice(package, output, run)
    try:
        device.adb("wait-for-device", timeout=180)
        device.wait(lambda: device.adb("shell", "getprop", "sys.boot_completed").strip() == "1", "Android boot")
        api = int(device.adb("shell", "getprop", "ro.build.version.sdk").strip())
        abi = device.adb("shell", "getprop", "ro.product.cpu.abi").strip()
        emulator = device.adb("shell", "getprop", "ro.kernel.qemu").strip()
        if (api, abi, emulator) != (expected_api, "x86_64", "1"):
            raise RuntimeError(f"Project probe requires the Android {expected_api} x86_64 emulator")
        densities = re.findall(r"(?:Physical|Override) density: (\d+)", device.adb("shell", "wm", "density"))
        if not densities:
            raise RuntimeError("Missing actual project device display density")
        density = int(densities[-1])
        device.adb("install", "-r", apk, timeout=180)
        installed = device.adb("shell", "dumpsys", "package", package)
        (output / "project-installed-package.txt").write_text(installed)
        if ("Package [" + package + "]" not in installed
                or not re.search(r"\bversionCode=" + str(identity["version_code"]) + r"\b", installed)
                or not re.search(r"^\s*versionName=" + re.escape(identity["version_name"]) + r"\s*$", installed, re.M)
                or "pkgFlags=[" not in installed or "DEBUGGABLE" in installed
                or any(permission in installed for permission in FORBIDDEN_PERMISSIONS)
                or LOCATION_SERVICE in installed):
            raise RuntimeError("Installed custom release identity or permissions differ")
        paths = device.adb("shell", "pm", "path", package).splitlines()
        if len(paths) != 1 or not re.fullmatch(r"package:/data/app/[A-Za-z0-9_./~=+\-]+/base\.apk", paths[0]):
            raise RuntimeError("Expected one installed custom APK")
        installed_digest = device.adb("shell", "sha256sum", paths[0][8:]).split()[0]
        if installed_digest != inspection["sha256"]:
            raise RuntimeError("Installed APK bytes differ from inspected custom release")
        device.adb("logcat", "-c")
        device.adb("shell", "am", "start", "-W", "-n", package + "/" + ACTIVITY)
        pid = device.wait(device.pid, "custom app process")
        first_home = device.home(heading, "project-home")
        device.wait(lambda: device.started(pid), "same-process RenPy/Flet/Flutter startup")
        device.tap(device.control("Start story"))
        device.wait(lambda: re.search(r"SDK_RUNNER_APP_STORY action=started [^\n]*pid=" + pid + r"\b", device.logs()),
                    "native story start")
        native = device.wait(lambda: native_dialogue_pixels(
            device.adb("exec-out", "screencap", binary=True), device.viewport()), "painted native first dialogue")
        if story_marker is not None:
            device.wait(lambda: re.search(re.escape(story_marker) + r" pid=" + pid + r"\b", device.logs()),
                        "supplied native story marker in the app process")
            native["story_marker"] = story_marker
            native["story_marker_pid"] = pid
        device.screenshot("project-native-story")
        device.adb("shell", "input", "keyevent", "4")
        device.tap(device.control("Return to app"))
        device.wait(lambda: re.search(r"SDK_RUNNER_APP_STORY action=return [^\n]*pid=" + pid + r"\b", device.logs()),
                    "native story return")
        returned = device.home(heading, "project-returned")
        if device.pid() != pid:
            raise RuntimeError("Custom home/native story round trip restarted the app")
        title = "ReleaseRecord" + uuid.uuid4().hex[:12]
        device.tap(device.control("Application records", scroll="up"))
        device.control("Records loaded", scroll="down")
        device.tap(device.control("Title", control_class="android.widget.EditText", scroll="up"))
        device.adb("shell", "input", "text", title)
        device.adb("shell", "input", "keyevent", "4")
        device.tap(device.control("Add record", scroll="down"))
        device.control("Record saved", scroll="down")
        device.control("Title: " + title, scroll="down")
        device.screenshot("project-record-saved")
        (output / "project-first-logcat.txt").write_text(device.logs())
        device.adb("shell", "am", "force-stop", package)
        device.wait(lambda: device.pid() is None, "custom app stopped")
        device.adb("shell", "am", "start", "-W", "-n", package + "/" + ACTIVITY)
        restarted_pid = device.wait(device.pid, "restarted custom app process")
        restarted = device.home(heading, "project-restarted")
        if restarted_pid == pid:
            raise RuntimeError("Custom app restart did not create a fresh process")
        device.wait(lambda: device.started(restarted_pid), "fresh same-process runtime startup")
        device.tap(device.control("Application records", scroll="up"))
        device.control("Records loaded", scroll="down")
        device.control("Title: " + title, scroll="down")
        device.screenshot("project-record-reopened")
        if device.pid() != restarted_pid:
            raise RuntimeError("Records reopening restarted the custom app")
        frame = device.adb("exec-out", "screencap", binary=True)
        width, height, _ = framebuffer_shape(frame)
        if (width, height, density) != tuple(expected_display):
            raise RuntimeError("Actual project device display differs from expected profile")
        receipt = {"source_sha": inspection["source_sha"], "sha256": inspection["sha256"],
                   "abis": inspection["abis"], "startup_template": "app", "build_type": "release",
                   "project_input_sha256": inspection["project"]["input_sha256"],
                   "identity": identity, "installed_sha256": installed_digest,
                   "certificate_sha256": [value.lower() for value in certificates],
                   "source_pid": pid, "restarted_pid": restarted_pid,
                   "device": {"api": api, "abi": abi, "emulator": True, "display_pixels": [width, height],
                              "density_dpi": density},
                   "checks": {"custom_home": first_home, "native_story": native,
                              "return_to_custom_home": returned, "fresh_process_home": restarted,
                              "records_after_reopening": {"title": title, "fresh_process": True}},
                   "skips": 0, "success": True}
    finally:
        # Retain diagnostics even on failure; never turn a failed operation into a receipt.
        primary_error = sys.exc_info()[1]
        try:
            if primary_error is not None:
                device.screenshot("project-failed")
            (output / "project-logcat.txt").write_text(device.logs())
        except Exception as error:
            if primary_error is None:
                raise
            print("Project diagnostic collection also failed: " + str(error), flush=True)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Passed: signed custom release project: " + json.dumps(receipt), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--package", required=True)
    parser.add_argument("--heading", required=True)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--project-input-sha256", required=True)
    parser.add_argument("--story-marker")
    parser.add_argument("--expected-api", type=int, choices=(35, 36), default=36)
    parser.add_argument("--aapt", type=Path, required=True)
    parser.add_argument("--apksigner", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=Path(".android-build/project-device"))
    parser.add_argument("--expected-display", nargs=3, type=int, default=(1080, 1920, 420),
                        metavar=("WIDTH", "HEIGHT", "DENSITY"))
    args = parser.parse_args()
    check_project_device(args.apk, args.package, args.heading, args.output, source_sha=args.source_sha,
                         aapt=args.aapt, apksigner=args.apksigner, expected_display=args.expected_display,
                         expected_api=args.expected_api,
                         project_input_sha256=args.project_input_sha256, story_marker=args.story_marker)


if __name__ == "__main__":
    main()
