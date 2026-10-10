"""Run the first signed example-app acceptance pass on an API 35 ARM phone."""

import argparse
from datetime import datetime, timezone
import json
import re
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_apk import inspect_apk
from scripts.check_project_device import (
    ACTIVITY, FORBIDDEN_PERMISSIONS, LOCATION_SERVICE, ProjectDevice, command,
    native_dialogue_pixels, release_identity,
)
from scripts.device_smoke import framebuffer_shape


class PhoneDevice(ProjectDevice):
    def __init__(self, package, output, serial, adb, run):
        super().__init__(package, output, run)
        self.serial, self.adb_path, self.log_pid = serial, adb, None

    def adb(self, *args, **options):
        return self.run(self.adb_path, "-s", self.serial, *args, **options)

    def logs(self):
        if self.log_pid is None:
            return ""
        return self.adb("logcat", "-d", "--pid", self.log_pid, "-v", "threadtime")

    def nodes(self, name="phone-ui"):
        remote = "/sdcard/renfletpy-api35-ui.xml"
        # A successful dump command can still leave yesterday's snapshot behind.
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

    def control(self, label, *, control_class=None, scroll=None):
        def find():
            nodes = [node for node in self.nodes()
                     if node.get("package", self.package) == self.package]
            matches = [node for node in nodes
                       if label in (node.get("text", "") + node.get("content-desc", ""))
                       and node.get("visible-to-user", "true") != "false"
                       and (control_class is None or node.get("class") == control_class)]
            visible = []
            for node in matches:
                try:
                    self.bounds(node)
                    visible.append(node)
                except RuntimeError:
                    continue
            matches = visible
            if matches:
                node = next((node for node in matches if node.get("class") == "android.widget.Button"), matches[0])
                return node
            if scroll:
                view = next((node for node in nodes if node.get("class") == "android.widget.ScrollView"), None)
                if view is not None:
                    left, top, right, bottom = self.bounds(view)
                    x = left + (right - left) * 4 // 5
                    upper, lower = top + (bottom - top) // 4, bottom - (bottom - top) // 4
                    self.adb("shell", "input", "swipe", x, lower if scroll == "down" else upper,
                             x, upper if scroll == "down" else lower, "400")
            return None
        return self.wait(find, "visible control " + (label or control_class))

    def profile(self):
        try:
            state = self.adb("get-state").strip()
        except subprocess.CalledProcessError as error:
            raise RuntimeError("Selected ADB phone is unavailable: " + (error.output or "").strip()) from error
        if state != "device":
            raise RuntimeError("The selected phone is not connected and authorized")
        values = {name: self.adb("shell", "getprop", prop).strip() for name, prop in (
            ("api", "ro.build.version.sdk"), ("android_version", "ro.build.version.release"),
            ("abi", "ro.product.cpu.abi"), ("model", "ro.product.model"),
            ("fingerprint", "ro.build.fingerprint"), ("qemu", "ro.kernel.qemu"),
        )}
        if (values["api"] != "35" or values["abi"] not in ("arm64-v8a", "armeabi-v7a")
                or values.pop("qemu") not in ("", "0")):
            raise RuntimeError("This pass requires a physical Android 15 / API 35 ARM phone")
        if self.adb("shell", "getprop", "sys.boot_completed").strip() != "1":
            raise RuntimeError("The selected phone has not finished booting")
        values.update(api=35, emulator=False, serial=self.serial)
        return values

    def launch(self):
        self.adb("shell", "am", "start", "-W", "-n", self.package + "/" + ACTIVITY)
        pid = self.wait(self.pid, "phone app process")
        self.log_pid = pid
        self.wait(lambda: self.started(pid), "RenPy/Flet/Flutter startup in one process")
        return pid

    def story_action(self, action, pid):
        return self.wait(lambda: re.search(r"SDK_RUNNER_APP_STORY action=" + action
                         + r" [^\n]*pid=" + pid + r"\b", self.logs()), "native story " + action)


def check_phone(apk, output, *, serial, sha256, source_sha, aapt, apksigner,
                heading="My RenFletPy App", adb="adb", run=command):
    if (not serial or serial.startswith("-") or any(char.isspace() for char in serial)
            or not re.fullmatch(r"[0-9a-f]{64}", sha256)
            or not re.fullmatch(r"[0-9a-f]{40}", source_sha) or not heading.strip()):
        raise ValueError("Supply an ADB serial, APK SHA-256, source revision and home heading")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    result = {"success": False, "stage": "apk preflight", "checks": {},
              "started_at": datetime.now(timezone.utc).isoformat()}
    device = None
    try:
        inspection = inspect_apk(apk, startup_template="app", build_type="release")
        if inspection["sha256"] != sha256 or inspection["source_sha"] != source_sha:
            raise RuntimeError("APK hash or build source differs from the selected artifact")
        project = inspection.get("project")
        if project is None:
            raise RuntimeError("The first phone pass requires a supplied app project")
        signing = run(apksigner, "verify", "--verbose", "--print-certs", apk)
        certificates = re.findall(r"Signer #\d+ certificate SHA-256 digest: ([0-9a-fA-F]{64})", signing)
        if not certificates:
            raise RuntimeError("Release APK has no verified signing certificate")
        (output / "apk-signature.txt").write_text(signing)
        badging = run(aapt, "dump", "badging", apk)
        permissions = run(aapt, "dump", "permissions", apk)
        manifest = run(aapt, "dump", "xmltree", apk, "AndroidManifest.xml")
        (output / "apk-manifest.txt").write_text(badging + "\n" + permissions + "\n" + manifest)
        identity = release_identity(badging, permissions, manifest, project, apk=apk)
        result.update(source_sha=source_sha, sha256=sha256, abis=inspection["abis"],
                      project_input_sha256=project["input_sha256"], identity=identity,
                      certificate_sha256=[value.lower() for value in certificates])
        (output / "apk-inspection.json").write_text(json.dumps(inspection, indent=2) + "\n")

        result["stage"] = "phone preflight"
        device = PhoneDevice(identity["package"], output, serial, adb, run)
        result["device"] = device.profile()
        result["stage"] = "install"
        installed = device.adb("install", "-r", apk, timeout=180)
        (output / "install.txt").write_text(installed)
        if "Success" not in installed.splitlines():
            raise RuntimeError("Android did not report a successful installation")
        package = device.adb("shell", "dumpsys", "package", device.package)
        (output / "installed-package.txt").write_text(package)
        if ("Package [" + device.package + "]" not in package
                or not re.search(r"\bversionCode=" + str(identity["version_code"]) + r"\b", package)
                or not re.search(r"^\s*versionName=" + re.escape(identity["version_name"]) + r"\s*$", package, re.M)
                or "pkgFlags=[" not in package or "DEBUGGABLE" in package
                or any(value in package for value in FORBIDDEN_PERMISSIONS)
                or LOCATION_SERVICE in package):
            raise RuntimeError("Installed package identity or disabled permissions differ")
        paths = device.adb("shell", "pm", "path", device.package).splitlines()
        if len(paths) != 1 or not re.fullmatch(r"package:/data/app/[A-Za-z0-9_./~=+\-]+/base\.apk", paths[0]):
            raise RuntimeError("Expected one installed release APK")
        installed_hash = device.adb("shell", "sha256sum", paths[0][8:]).split()[0]
        if installed_hash != sha256:
            raise RuntimeError("Installed APK bytes differ from the verified release")
        result["installed_sha256"] = installed_hash
        result["checks"]["install"] = True

        result["stage"] = "launch"
        device.adb("shell", "am", "force-stop", device.package)
        device.wait(lambda: device.pid() is None, "app stopped before launch")
        pid = device.launch()
        result["source_pid"] = pid
        result["checks"]["launch"] = device.home(heading, "home")

        result["stage"] = "story Start/Return"
        device.tap(device.control("Start story", scroll="down"))
        # A repeat run may already have a story bookmark. The example's explicit
        # confirmation starts a new test story without clearing any Records.
        def started_or_confirmation():
            if re.search(r"SDK_RUNNER_APP_STORY action=started [^\n]*pid=" + pid + r"\b", device.logs()):
                return True
            return next((node for node in device.nodes() if "Start new story" in
                         (node.get("text", "") + node.get("content-desc", ""))), None)
        confirmation = device.wait(started_or_confirmation, "story start or existing-progress confirmation")
        if isinstance(confirmation, ET.Element):
            device.tap(confirmation)
        device.story_action("started", pid)
        native = device.wait(lambda: native_dialogue_pixels(
            device.adb("exec-out", "screencap", binary=True), device.viewport()), "painted native dialogue")
        device.screenshot("native-story")
        device.adb("shell", "input", "keyevent", "4")
        device.tap(device.control("Return to app", scroll="up"))
        device.story_action("return", pid)
        returned = device.home(heading, "returned-home")
        if device.pid() != pid:
            raise RuntimeError("Start/Return restarted the app process")
        result["checks"]["story_start_return"] = {"native": native, "returned_home": returned}

        result["stage"] = "save Record"
        title = "API35Record" + uuid.uuid4().hex[:12]
        device.tap(device.control("Application records", scroll="up"))
        device.control("Records loaded", scroll="down")
        device.tap(device.control("Title", control_class="android.widget.EditText", scroll="up"))
        device.adb("shell", "input", "text", title)
        device.adb("shell", "input", "keyevent", "4")
        device.tap(device.control("Add record", scroll="down"))
        device.control("Record saved", scroll="down")
        device.control("Title: " + title, scroll="down")
        device.screenshot("record-saved")
        result["record_title"] = title
        (output / "first-process-logcat.txt").write_text(device.logs())

        result["stage"] = "Records after reopening"
        device.adb("shell", "am", "force-stop", device.package)
        device.wait(lambda: device.pid() is None, "app fully stopped with the Record saved")
        restarted = device.launch()
        result["restarted_pid"] = restarted
        if restarted == pid:
            raise RuntimeError("Reopening reused the original app process")
        device.home(heading, "reopened-home")
        device.tap(device.control("Application records", scroll="up"))
        device.control("Records loaded", scroll="down")
        device.control("Title: " + title, scroll="down")
        device.screenshot("record-reopened")
        if device.pid() != restarted:
            raise RuntimeError("The app process changed during the Records reopening check")
        result["checks"]["records_after_reopening"] = {"title": title, "fresh_process": True}
        width, height, _ = framebuffer_shape(device.adb("exec-out", "screencap", binary=True))
        result["device"].update(display_pixels=[width, height],
                                density=device.adb("shell", "wm", "density").strip())
        result.update(success=True, stage="complete", skips=0)
    except Exception as error:
        result["error"] = str(error)
        if isinstance(getattr(error, "output", None), str):
            result["command_output"] = error.output
        raise
    finally:
        if device is not None and device.log_pid is not None:
            try:
                (output / "phone-logcat.txt").write_text(device.logs())
            except Exception as error:
                result["diagnostic_error"] = str(error)
        result["finished_at"] = datetime.now(timezone.utc).isoformat()
        (output / "api35-phone.json").write_text(json.dumps(result, indent=2) + "\n")
    print("Passed: API 35 phone install, launch, story Start/Return and Records reopening: " + str(output))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--serial", required=True, help="The authorized phone serial from adb devices -l")
    parser.add_argument("--sha256", required=True, help="Expected SHA-256 of this exact signed APK")
    parser.add_argument("--source-sha", required=True, help="The APK build revision, not the test checkout revision")
    parser.add_argument("--aapt", required=True)
    parser.add_argument("--apksigner", required=True)
    parser.add_argument("--adb", default="adb")
    parser.add_argument("--heading", default="My RenFletPy App")
    parser.add_argument("--output", type=Path, default=Path(".android-build/phone-api35-"
                        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")))
    args = parser.parse_args()
    check_phone(args.apk, args.output, serial=args.serial, sha256=args.sha256,
                source_sha=args.source_sha, aapt=args.aapt, apksigner=args.apksigner,
                heading=args.heading, adb=args.adb)


if __name__ == "__main__":
    main()
