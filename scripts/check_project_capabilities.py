"""Exercise the project capabilities example on an API 35 Android emulator.

This is a functionality check. Its screenshots and short pixel comparisons do
not measure phone frame times, responsiveness, startup or memory. The debug
fixture is installed and its own application data is cleared before the run.
"""

import argparse
import gzip
import hashlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.check_apk import inspect_apk
from scripts.check_project_device import (
    ACTIVITY, FORBIDDEN_PERMISSIONS, LOCATION_SERVICE, ProjectDevice, command,
)
from scripts.device_smoke import framebuffer_shape


PACKAGE = "org.renfletpy.capabilities"
RECEIPT = "capabilities-device.json"
JSON_MARKERS = frozenset((
    "SDK_CAP_OBSERVER", "SDK_CAP_ACTIVITY_STATE", "SDK_CAP_ACTIVITY_RESULT",
    "SDK_CAP_APP_STATE", "SDK_CAP_PULSE_EVENT", "SDK_CAP_RIVE_READY",
    "SDK_CAP_RIVE_INPUT", "SDK_CAP_RIVE_EVENT", "SDK_CAP_RIVE_LIFECYCLE",
    "SDK_2D_READY", "SDK_2D_INPUT", "SDK_2D_WORKER", "SDK_2D_APP_STATE",
    "SDK_2D_ACTIVITY_STATE", "SDK_2D_ACTIVITY_RESULT",
))
LOG_LINE = re.compile(r"^[VDIWEFA]/[^\n(]+\(\s*(\d+)\):\s?(.*)$")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def strict_json(value):
    def pairs(items):
        result = {}
        for key, item in items:
            if key in result:
                raise ValueError("Duplicate JSON key: " + key)
            result[key] = item
        return result

    def constant(value):
        raise ValueError("Nonfinite JSON value: " + value)

    def floating(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("Nonfinite JSON number")
        return result

    return json.loads(value, object_pairs_hook=pairs, parse_constant=constant, parse_float=floating)


def marker_records(logs, pid=None):
    """Bind markers to Android's logging PID, not just a claimed JSON field."""
    records = []
    for number, line in enumerate(logs.splitlines()):
        match = LOG_LINE.fullmatch(line)
        if not match or (pid is not None and match.group(1) != str(pid)):
            continue
        actual_pid, message = int(match.group(1)), match.group(2)
        marker, _, serialized = message.partition(" ")
        if marker not in JSON_MARKERS:
            continue
        try:
            payload = strict_json(serialized)
        except (TypeError, ValueError) as error:
            raise RuntimeError("Malformed " + marker + " in process " + str(actual_pid)) from error
        if not isinstance(payload, dict):
            raise RuntimeError("Expected an object for " + marker)
        if "pid" in payload and (type(payload["pid"]) is not int or payload["pid"] != actual_pid):
            raise RuntimeError("Marker PID differs from Android log PID")
        records.append({"marker": marker, "pid": actual_pid, "line": number, "data": payload})
    return records


def check_log_errors(logs, pids):
    """A mounted control or a receipt cannot hide a runtime exception."""
    wanted = {str(pid) for pid in pids}
    for line in logs.splitlines():
        match = LOG_LINE.fullmatch(line)
        if not match or match.group(1) not in wanted:
            continue
        message = match.group(2)
        if any(value in message for value in (
            "Traceback (most recent call last):", "Full traceback:", "While running game code:",
            "SDK_RIVE_ERROR", "Unhandled Exception", "FATAL EXCEPTION", "ActivityRenderError",
        )):
            raise RuntimeError("Capabilities runtime failed: " + message)


def check_ui_errors(nodes):
    for node in nodes:
        text = node.get("text", "") + node.get("content-desc", "")
        if "Palette could not be loaded" in text or "Rive failed:" in text:
            raise RuntimeError("Project component reported a visible error: " + text)


def owner_proof(records, pid):
    observers = [record["data"] for record in records
                 if record["pid"] == int(pid) and record["marker"] == "SDK_CAP_OBSERVER"]
    if len(observers) != 1:
        raise RuntimeError("Expected one native project observer in each process")
    observer = observers[0]
    if (observer.get("schema") != 1 or observer.get("observer") != "project_capabilities"
            or type(observer.get("owner_thread")) is not int or observer["owner_thread"] <= 0
            or not re.fullmatch(r"[0-9a-f]{64}", observer.get("source_sha256", ""))):
        raise RuntimeError("Missing native owner/source evidence")
    for record in records:
        if (record["pid"] == int(pid) and record["marker"] in {
                "SDK_CAP_ACTIVITY_STATE", "SDK_CAP_ACTIVITY_RESULT", "SDK_CAP_APP_STATE"}
                and record["data"].get("owner_thread") != observer["owner_thread"]):
            raise RuntimeError("Game state was observed outside its native owning thread")
    return observer


def restored_model(before, after, *, fresh_process):
    for model in (before, after):
        if (type(model.get("pid")) is not int or type(model.get("revision")) is not int
                or type(model.get("version")) is not int or not isinstance(model.get("state"), dict)
                or model.get("result") is not None):
            raise RuntimeError("Halfway state is missing plain model/version/revision evidence")
    if after.get("phase") != "restored":
        raise RuntimeError("The SDK after-load observer did not report a restored activity")
    if fresh_process and before["pid"] == after["pid"]:
        raise RuntimeError("Reopening reused the old process")
    if not fresh_process and before["pid"] != after["pid"]:
        raise RuntimeError("Quick load unexpectedly restarted the application")
    if before["pid"] == after["pid"] and before["revision"] == after["revision"]:
        raise RuntimeError("Quick load retained stale controls/revision")
    if any(before.get(key) != after.get(key) for key in ("kind", "version", "state", "result")):
        raise RuntimeError("Restored game values differ from the exact halfway model")
    return {"before": before, "after": after, "fresh_process": fresh_process,
            "exact_model": True, "saved_controls": False}


def single_result(records, pid, kind, expected):
    native = [record["data"] for record in records if record["pid"] == int(pid)
              and record["marker"] == "SDK_CAP_ACTIVITY_RESULT" and record["data"].get("kind") == kind]
    script = [record["data"] for record in records if record["pid"] == int(pid)
              and record["marker"] == "SDK_2D_ACTIVITY_RESULT" and record["data"].get("kind") == kind]
    if len(native) != 1 or len(script) != 1:
        raise RuntimeError("Expected exactly one native and one project story return for " + kind)
    if native[0].get("result") != expected or script[0].get("result") != expected:
        raise RuntimeError("The returned activity result is missing meaningful game values")
    return {"native": native[0], "project_story": script[0], "return_count": 1}


def rive_ready(record, state, role):
    if record.get("role") != role or not isinstance(record.get("data"), dict):
        raise RuntimeError("Missing actual Rive readiness callback")
    manifest = record["data"]
    if any(type(manifest.get(key)) not in (int, float) or not math.isfinite(manifest[key])
           or manifest[key] <= 0 for key in ("width", "height")):
        raise RuntimeError("Rive artboard has no actual bounds")
    if role == "forest":
        if (manifest.get("inputs", {}).get("Progress") != "number"
                or manifest.get("inputs", {}).get("Downloading") != "boolean"
                or "Loading" not in manifest.get("machines", [])
                or manifest.get("numbers", {}).get("Progress") != min(state["progress"], 99.0)
                or manifest.get("booleans", {}).get("Downloading") is not state["downloading"]):
            raise RuntimeError("Rive controller did not reconstruct number/boolean game inputs")
    elif role == "signal":
        if (manifest.get("artboard") != "New Artboard"
                or manifest.get("inputs", {}).get("FireGeneralEvent") != "trigger"
                or "State Machine 1" not in manifest.get("machines", [])):
            raise RuntimeError("Missing the real Rive trigger state machine")
    elif role == "loop":
        if (manifest.get("artboard") != "New Artboard" or manifest.get("animations") != ["bouncing"]
                or manifest.get("machines") != [] or manifest.get("inputs") != {}
                or manifest.get("numbers") != {} or manifest.get("booleans") != {}
                or manifest.get("active") is not state["downloading"]
                or type(manifest.get("speed_multiplier")) not in (int, float)
                or manifest["speed_multiplier"] != (1.0 if state["downloading"] else 0.0)):
            raise RuntimeError("The looping Rive component did not select its actual bouncing animation")
    else:
        raise ValueError("Unknown Rive fixture role")
    return record


def meaningful_rive_event(record):
    value = record.get("data", {})
    expected = {"SomeNumber": 11.0, "SomeBoolean": True, "SomeString": "Something"}
    if (record.get("role") != "signal" or value.get("name") != "SomeGeneralEvent"
            or value.get("type") != "general" or value.get("properties") != expected
            or type(value.get("properties", {}).get("SomeBoolean")) is not bool):
        raise RuntimeError("The trigger did not return the meaningful Rive event payload")
    return value


def rive_lifecycle(record, *, active, reasons):
    data = record.get("data", {})
    if (record.get("role") != "loop" or data.get("active") is not active
            or data.get("reason") not in reasons):
        raise RuntimeError("The looping Rive component did not report its actual playback transition")
    return record


def rive_cleanup(logs, pid):
    ready, disposed, messages = set(), set(), []
    for line in logs.splitlines():
        parsed = LOG_LINE.fullmatch(line)
        if not parsed or parsed.group(1) != str(pid):
            continue
        message = parsed.group(2)
        mounted = re.match(r"SDK_RIVE_READY id=(\S+) artboard=", message)
        removed = re.fullmatch(r"SDK_RIVE_DISPOSED id=(\S+)", message)
        if mounted:
            ready.add(mounted.group(1))
        if removed:
            disposed.add(removed.group(1))
            messages.append(message)
    if len(ready) < 3 or not ready <= disposed:
        return None
    return {"ready_ids": sorted(ready), "disposed_ids": sorted(disposed), "messages": messages,
            "all_controllers_disposed": True, "pid": int(pid)}


def pixel_comparison(first, second, bounds, *, moving):
    """Compare retained actual RGBA captures in a visible component region."""
    w1, h1, start1 = framebuffer_shape(first)
    w2, h2, start2 = framebuffer_shape(second)
    if (w1, h1) != (w2, h2):
        raise RuntimeError("Framebuffer dimensions changed during playback comparison")
    left, top, right, bottom = bounds
    if not (0 <= left < right <= w1 and 0 <= top < bottom <= h1):
        raise RuntimeError("Playback region is outside the actual framebuffer")
    changed, samples, colors = 0, 0, set()
    for y in range(top, bottom, 4):
        for x in range(left, right, 4):
            a = first[start1 + (y * w1 + x) * 4:start1 + (y * w1 + x) * 4 + 3]
            b = second[start2 + (y * w1 + x) * 4:start2 + (y * w1 + x) * 4 + 3]
            changed += any(abs(one - two) > 12 for one, two in zip(a, b))
            samples += 1
            colors.add(tuple(channel // 16 for channel in b))
    fraction = changed / samples
    if samples < 64 or len(colors) < 4:
        raise RuntimeError("Component capture is blank or too small to prove rendering")
    if moving and fraction < 0.002:
        raise RuntimeError("Actual component pixels did not animate")
    if not moving and fraction > 0.005:
        raise RuntimeError("Paused component pixels continued changing")
    return {"bounds": bounds, "sampled_pixels": samples, "changed_pixels": changed,
            "changed_fraction": fraction, "color_bins": len(colors), "moving": moving,
            "first_sha256": digest(first), "second_sha256": digest(second),
            "limits": {"playing_min_fraction": 0.002, "paused_max_fraction": 0.005,
                       "channel_difference": 12, "sample_step": 4}}


def native_button_bounds(frame):
    """Locate the project SDL button's painted rectangle, without guessed taps."""
    width, height, start = framebuffer_shape(frame)
    target = (38, 62, 80)  # Project-owned sdk_scale_continue background #263e50.
    bands, band = [], []
    for y in range(height // 2, height * 9 // 10, 2):
        xs = []
        # The native frame's padding can place its button inside either 5% edge.
        for x in range(0, width, 2):
            pos = start + (y * width + x) * 4
            if all(abs(actual - expected) <= 5 for actual, expected in zip(frame[pos:pos + 3], target)):
                xs.append(x)
        # xs contains every second pixel; compare its painted width in pixels.
        if len(xs) * 2 >= width // 5:
            band.append((y, min(xs), max(xs) + 2))
        elif band:
            bands.append(band)
            band = []
    if band:
        bands.append(band)
    candidates = [[min(row[1] for row in rows), rows[0][0], max(row[2] for row in rows), rows[-1][0] + 2]
                  for rows in bands if len(rows) * 2 >= height // 40]
    if len(candidates) != 1:
        raise RuntimeError("Could not uniquely locate the painted native Continue 2D journey button")
    return candidates[0]


def save_archive(data):
    """Read metadata/signatures, never execute the saved Python pickle."""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as saved:
            required = {"json", "log", "signatures", "renpy_version"}
            if not required <= set(saved.namelist()) or len(saved.namelist()) != len(set(saved.namelist())):
                raise RuntimeError("Missing native Ren'Py save members")
            if any(item.file_size > 64 * 1024 * 1024 for item in saved.infolist()):
                raise RuntimeError("Unexpectedly large native save member")
            metadata = strict_json(saved.read("json"))
            if not isinstance(metadata, dict) or metadata.get("app_story") != {
                    "version": 1, "story_id": "app-recipe", "phase": "active", "value": None}:
                raise RuntimeError("Native save does not contain an active project story")
            if not saved.read("log") or not saved.read("signatures"):
                raise RuntimeError("Native save has no game data/signature")
            return {"sha256": digest(data), "size": len(data), "metadata": metadata,
                    "members": sorted(saved.namelist()), "game_data_sha256": digest(saved.read("log")),
                    "unpickled": False}
    except (OSError, ValueError, zipfile.BadZipFile, KeyError) as error:
        raise RuntimeError("Invalid native Ren'Py save archive") from error


def artifact_manifest(output):
    result = {}
    for path in sorted(Path(output).rglob("*")):
        if path.is_symlink():
            raise RuntimeError("Evidence artifacts must be regular files")
        if path.is_file() and path.name != RECEIPT:
            content = path.read_bytes()
            result[path.relative_to(output).as_posix()] = {"sha256": digest(content), "size": len(content)}
    if not any(name.endswith(".xml") for name in result) or not any(name.endswith(".png") for name in result):
        raise RuntimeError("Missing raw semantic UI or screenshots")
    return result


def debug_identity(badging, permissions, manifest, project):
    package = re.search(r"^package: name='([^']+)' versionCode='(\d+)' versionName='([^']*)'", badging, re.M)
    label = re.search(r"^application-label:'([^']*)'", badging, re.M)
    activity = re.search(r"^launchable-activity: name='([^']+)'", badging, re.M)
    if (not package or not label or not activity
            or package.groups() != (project["application_id"], str(project["version_code"]), project["version_name"])
            or label.group(1) != project["display_name"] or activity.group(1) != ACTIVITY
            or "application-debuggable" not in badging):
        raise RuntimeError("Compiled capabilities debug APK identity differs from its project")
    granted = set(re.findall(r"uses-permission(?:-sdk-\d+)?: name='([^']+)'", permissions))
    if granted & FORBIDDEN_PERMISSIONS or LOCATION_SERVICE in manifest:
        raise RuntimeError("Capabilities project requests disabled permissions")
    return {"package": package.group(1), "version_code": int(package.group(2)),
            "version_name": package.group(3), "display_name": label.group(1),
            "activity": activity.group(1), "debuggable": True, "permissions": sorted(granted)}


class CapabilitiesProbe:
    def __init__(self, device):
        self.device, self.output = device, device.output
        self.pids = []
        self.pinch_jar = None

    def logs(self):
        logs = self.device.logs()
        check_log_errors(logs, self.pids)
        return logs

    def records(self, pid=None):
        return marker_records(self.logs(), pid)

    def cursor(self):
        return len(self.logs().splitlines()) - 1

    def wait_record(self, marker, *, pid, predicate=lambda value: True, after=-1, description=None):
        def observed():
            values = [record for record in self.records(pid) if record["marker"] == marker
                      and record["line"] > after and predicate(record["data"])]
            return values[-1]["data"] if values else None
        return self.device.wait(observed, description or marker)

    def wait_native(self, marker, action, pid, *, after=-1):
        def observed():
            for number, line in enumerate(self.logs().splitlines()):
                parsed = LOG_LINE.fullmatch(line)
                if (number > after and parsed and parsed.group(1) == str(pid)
                        and re.search(re.escape(marker) + r" action=" + re.escape(action)
                                      + r"(?:\s|$)", parsed.group(2))
                        and re.search(r"\bpid=" + re.escape(str(pid)) + r"\b", parsed.group(2))):
                    return parsed.group(2)
            return None
        return self.device.wait(observed, "native " + action)

    def start(self):
        self.device.adb("shell", "am", "start", "-W", "-n", self.device.package + "/" + ACTIVITY)
        pid = self.device.wait(self.device.pid, "capabilities application process")
        if pid in self.pids:
            raise RuntimeError("Application reopening did not create a new process")
        self.pids.append(pid)
        self.device.wait(lambda: self.device.started(pid), "RenPy/Flet/Flutter startup in one process")
        self.wait_record("SDK_CAP_OBSERVER", pid=pid)
        return pid

    def screen(self, heading, name):
        self.device.control(heading, scroll="up")
        check_ui_errors(self.device.nodes(name))
        self.device.screenshot(name)

    def tap(self, label, *, scroll="down"):
        self.device.tap(self.device.control(label, scroll=scroll))

    def semantic(self, identifier, *, name="capabilities-ui", scroll=None):
        def observed():
            nodes = self.device.nodes(name)
            check_ui_errors(nodes)
            matches = [node for node in nodes if node.get("resource-id") in
                       (identifier, self.device.package + ":id/" + identifier)
                       and node.get("visible-to-user", "true") != "false"]
            for node in matches:
                try:
                    self.device.bounds(node)
                    return node
                except RuntimeError:
                    pass
            if scroll:
                view = next((node for node in nodes if node.get("class") == "android.widget.ScrollView"), None)
                if view is not None:
                    left, top, right, bottom = self.device.bounds(view)
                    x, upper, lower = (left + right) // 2, top + 80, bottom - 80
                    self.device.adb("shell", "input", "swipe", x, lower if scroll == "down" else upper,
                                    x, upper if scroll == "down" else lower, 400)
            return None
        return self.device.wait(observed, "semantic control " + identifier)

    def edit(self, value, *, identifier=None, index=0):
        if identifier:
            parent = self.semantic(identifier, scroll="up")
            inputs = list(parent.iter("node"))
        else:
            inputs = self.device.nodes()
        inputs = [node for node in inputs if node.get("class") == "android.widget.EditText"]
        if len(inputs) <= index:
            raise RuntimeError("Missing project text input")
        self.device.tap(inputs[index])
        self.device.adb("shell", "input", "keyevent", "KEYCODE_MOVE_END")
        self.device.adb("shell", "input", "keycombination", "113", "29")  # Control+A.
        self.device.adb("shell", "input", "text", value)
        self.device.adb("shell", "input", "keyevent", "4")

    def motion(self, identifier, name, *, moving=True, bounds=None):
        if bounds is None:
            bounds = self.device.bounds(self.semantic(identifier, name=name + "-ui", scroll="up"))
        first = self.device.adb("exec-out", "screencap", binary=True)
        time.sleep(0.37)
        second = self.device.adb("exec-out", "screencap", binary=True)
        (self.output / (name + "-1.rgba.gz")).write_bytes(gzip.compress(first))
        (self.output / (name + "-2.rgba.gz")).write_bytes(gzip.compress(second))
        self.device.screenshot(name)
        comparison = pixel_comparison(first, second, bounds, moving=moving)
        comparison["captures"] = [name + "-1.rgba.gz", name + "-2.rgba.gz"]
        comparison["semantic_identifier"] = identifier
        return comparison

    def app_lab(self):
        self.tap("Capabilities lab", scroll="up")
        self.device.control("Project capabilities")

    def open_link(self, route):
        scheme = self.device.package.replace(".", "-").replace("_", "-")
        # Quote the URI for adb's remote shell; query separators must not become shell commands.
        uri = scheme + "://" + route
        if not re.fullmatch(r"[A-Za-z0-9_./:?=\-]+", uri):
            raise ValueError("Unsupported fixture URI")
        report = self.device.adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
                                 "-d", "'" + uri + "'", "-p", self.device.package)
        (self.output / "capabilities-direct-link.txt").write_text(report)

    def activity(self, kind, pid, *, after=-1, predicate=lambda value: True, phase=None):
        return self.wait_record("SDK_CAP_ACTIVITY_STATE", pid=pid, after=after, predicate=lambda value: (
            value.get("kind") == kind and (phase is None or value.get("phase") == phase) and predicate(value)))

    def show_restored(self, heading):
        nodes = self.device.nodes()
        if not any(heading in (node.get("text", "") + node.get("content-desc", "")) for node in nodes):
            self.tap("Resume story", scroll="up")
        self.device.control(heading)

    def save_bytes(self, pid, slot, name, *, previous_sha=None):
        paths = re.findall(r"SDK_RUNNER_APP_SAVE_DIR path=([^\n]+?) pid=" + re.escape(str(pid)) + r"\b", self.logs())
        if not paths or not re.fullmatch(r"/(?:data|storage|sdcard)/[A-Za-z0-9_./\-]+", paths[-1]):
            raise RuntimeError("Missing safe native save directory")
        path = paths[-1] + "/" + slot + ".save"

        def observed():
            try:
                data = self.device.adb("exec-out", "run-as", self.device.package, "cat", path, binary=True)
                proof = save_archive(data)
                if proof["sha256"] == previous_sha:
                    return None
                (self.output / (name + ".save")).write_bytes(data)
                return {**proof, "path": path, "artifact": name + ".save"}
            except subprocess.CalledProcessError:
                return None
            except RuntimeError:
                # Android's writer replaces the save only when its zip is complete.
                return None
        return self.device.wait(observed, "completed native " + slot + " save", seconds=45)

    def quick_save(self, pid, name):
        self.device.adb("shell", "input", "keyevent", "4")
        self.device.control("Paused")
        cursor = self.cursor()
        self.tap("Quick save", scroll="up")
        marker = self.wait_native("SDK_RUNNER_SAVE", "saved", pid, after=cursor)
        self.device.control("Saved. You can return here")
        self.device.nodes(name + "-menu")
        self.device.screenshot(name + "-menu")
        archive = self.save_bytes(pid, "app-recipe-quick", name + "-quick")
        self.tap("Resume", scroll="up")
        return {"marker": marker, **archive}

    def quick_load(self, before, name):
        pid = str(before["pid"])
        self.device.adb("shell", "input", "keyevent", "4")
        cursor = self.cursor()
        self.tap("Quick load", scroll="up")
        self.wait_native("SDK_RUNNER_SAVE", "loaded", pid, after=cursor)
        after = self.activity(before["kind"], pid, after=cursor, phase="restored")
        proof = restored_model(before, after, fresh_process=False)
        self.device.nodes(name + "-quick-loaded")
        self.device.screenshot(name + "-quick-loaded")
        return proof

    def background_reopen(self, before, name):
        pid = str(before["pid"])
        # A previous HOME/resume cycle may leave a valid recovery file. Wait
        # for this pause's writer to replace it before stopping the process.
        paths = re.findall(r"SDK_RUNNER_APP_SAVE_DIR path=([^\n]+?) pid=" + re.escape(pid) + r"\b", self.logs())
        if not paths or not re.fullmatch(r"/(?:data|storage|sdcard)/[A-Za-z0-9_./\-]+", paths[-1]):
            raise RuntimeError("Missing safe native save directory")
        previous_sha = None
        try:
            previous_sha = digest(self.device.adb("exec-out", "run-as", self.device.package,
                "cat", paths[-1] + "/_reload-1.save", binary=True))
        except subprocess.CalledProcessError:
            pass
        self.device.adb("shell", "input", "keyevent", "3")
        archive = self.save_bytes(pid, "_reload-1", name + "-mobile", previous_sha=previous_sha)
        (self.output / (name + "-source-logcat.txt")).write_text(self.logs())
        self.device.adb("shell", "am", "force-stop", self.device.package)
        self.device.wait(lambda: self.device.pid() is None, "old capabilities process to stop")
        new_pid = self.start()
        self.wait_native("SDK_RUNNER_SAVE", "loaded", new_pid)
        after = self.activity(before["kind"], new_pid, phase="restored")
        proof = restored_model(before, after, fresh_process=True)
        return new_pid, {**proof, "mobile_save": archive}

    def pinch(self, bounds, name):
        if self.pinch_jar is None:
            raise RuntimeError("The two-pointer acceptance driver was not prepared")
        remote = "/data/local/tmp/renfletpy-capabilities-pinch.jar"
        self.device.adb("push", self.pinch_jar, remote)
        left, top, right, bottom = bounds
        radius = max(24, (right - left) // 8)
        report = self.device.adb("shell", "CLASSPATH=" + remote, "app_process", "/system/bin",
            "capabilities_pinch", (left + right) // 2, (top + bottom) // 2, radius, radius * 2)
        (self.output / (name + "-pinch.txt")).write_text(report)
        values = [strict_json(line.split("SDK_CAP_PINCH ", 1)[1]) for line in report.splitlines()
                  if line.startswith("SDK_CAP_PINCH ")]
        if len(values) != 1 or values[0].get("accepted_events") != 24 or values[0].get("pointers") != 2:
            raise RuntimeError("Android did not acknowledge the complete two-pointer gesture")
        return values[0]


def compile_pinch(output, aapt, run):
    """Build an isolated shell driver using public MotionEvent types from Android."""
    sdk = Path(aapt).resolve().parents[2]
    jars = [path for path in (sdk / "platforms").glob("android-*/android.jar")
            if re.fullmatch(r"android-\d+", path.parent.name) and int(path.parent.name[8:]) >= 35]
    if not jars:
        raise RuntimeError("Pinch driver requires an installed Android 35+ platform android.jar")
    android = max(jars, key=lambda path: int(path.parent.name[8:]))
    d8 = Path(aapt).resolve().parent / "d8"
    if not d8.is_file():
        raise RuntimeError("Pinch driver requires the Android build-tools d8 compiler")
    work = Path(output) / "pinch-driver"
    classes, dex = work / "classes", work / "dex"
    classes.mkdir(parents=True, exist_ok=True)
    dex.mkdir(parents=True, exist_ok=True)
    source = Path(__file__).with_name("capabilities_pinch.java")
    (work / source.name).write_bytes(source.read_bytes())
    javac = Path(os.environ["JAVA_HOME"]) / "bin/javac" if os.environ.get("JAVA_HOME") else "javac"
    compilation = run(javac, "-source", "8", "-target", "8", "-cp", android, "-d", classes, source)
    conversion = run(d8, "--lib", android, "--min-api", "35", "--output", dex, classes / "capabilities_pinch.class")
    (work / "compilation.txt").write_text(compilation + "\n" + conversion)
    jar = work / "capabilities-pinch.jar"
    with zipfile.ZipFile(jar, "w", zipfile.ZIP_STORED) as packaged:
        packaged.write(dex / "classes.dex", "classes.dex")
    return jar


def check_navigation(probe, pid):
    device = probe.device
    probe.app_lab()
    probe.tap("Project notebook", scroll="up")
    draft = "CapabilityDraft" + uuid.uuid4().hex[:10]
    probe.edit(draft)
    probe.tap("Select Rowan", scroll="up")
    probe.tap("Open lighthouse entry", scroll="down")
    device.control("Entry: lighthouse")
    device.control("Draft: " + draft)
    device.control("Selected: rowan")
    probe.screen("Entry: lighthouse", "navigation-detail")
    device.adb("shell", "input", "keyevent", "4")
    device.control("Project notebook")
    device.control(draft)
    probe.open_link("/app/entries/lighthouse?source=capabilities")
    device.control("Entry: lighthouse")
    device.control("Draft: " + draft)
    probe.screen("Entry: lighthouse", "navigation-direct-link")
    device.adb("shell", "input", "keyevent", "4")
    device.control("Project notebook")
    cursor = probe.cursor()
    probe.tap("Start notebook story")
    probe.wait_native("SDK_RUNNER_APP_STORY", "started", pid, after=cursor)
    device.wait(lambda: device.viewport().get("presentation") == "scene", "native story surface")
    device.screenshot("navigation-native-story")
    device.adb("shell", "input", "keyevent", "4")
    probe.tap("Return to app")
    probe.wait_native("SDK_RUNNER_APP_STORY", "return", pid, after=cursor)
    device.control("Project notebook")
    device.control(draft)
    device.control("Selected: rowan")
    probe.screen("Project notebook", "navigation-returned-draft")
    start_count = len(re.findall(r"SDK_RUNNER_APP_STORY action=started [^\n]*pid=" + pid + r"\b", probe.logs()))
    probe.tap("Start notebook story")
    device.control("Start a new story?")
    device.nodes("navigation-dialog")
    device.screenshot("navigation-dialog")
    device.adb("shell", "input", "keyevent", "4")
    device.control("Project notebook")
    probe.tap("Start notebook story")
    device.control("Start a new story?")
    probe.tap("Cancel", scroll=None)
    device.control("Project notebook")
    device.control(draft)
    if len(re.findall(r"SDK_RUNNER_APP_STORY action=started [^\n]*pid=" + pid + r"\b", probe.logs())) != start_count:
        raise RuntimeError("Dismissing/cancelling the replacement dialog started another story")
    if device.pid() != pid:
        raise RuntimeError("Project navigation/Start/Return restarted the application")
    probe.tap("Back", scroll="down")
    device.control("Project capabilities")
    # Existing SDK screens are normal registered app screens too.
    probe.tap("Application records", scroll="up")
    device.control("Records loaded", scroll="down")
    probe.screen("Application records", "navigation-records")
    device.adb("shell", "input", "keyevent", "4")
    device.control("Project capabilities")
    probe.tap("Saved games", scroll="down")
    probe.screen("Saved games", "navigation-saved-games")
    device.adb("shell", "input", "keyevent", "4")
    device.control("Project capabilities")
    return {"draft": draft, "selected": "rowan", "detail_route": "/app/entries/lighthouse",
            "direct_link": True, "android_back": True, "dialog_back": True, "dialog_cancel": True,
            "start_return_same_process": True, "records_and_saved_games": True}


def check_pulse(probe, pid):
    device = probe.device
    probe.tap("Project pulse dial", scroll="up")
    device.control("Project pulse dial")
    mounted = probe.wait_record("SDK_CAP_PULSE_EVENT", pid=pid,
                               predicate=lambda value: value.get("phase") == "mounted" and value.get("running") is True)
    draft = "PulseDraft" + uuid.uuid4().hex[:10]
    probe.edit(draft, identifier="cap-pulse-draft")
    playing = probe.motion("cap-pulse-dial", "pulse-playing")
    dial = probe.semantic("cap-pulse-dial")
    left, top, right, bottom = device.bounds(dial)
    cursor = probe.cursor()
    device.adb("shell", "input", "tap", left + (right - left) // 5, (top + bottom) // 2)
    selected = probe.wait_record("SDK_CAP_PULSE_EVENT", pid=pid, after=cursor,
                                predicate=lambda value: value.get("phase") == "selection" and value.get("changes", 0) >= 1)
    if not 70 <= selected.get("value", -1) <= 80:
        raise RuntimeError("PulseDial did not return its actual tap selection")
    cursor = probe.cursor()
    probe.tap("Pause / resume pulse")
    paused = probe.wait_record("SDK_CAP_PULSE_EVENT", pid=pid, after=cursor,
                              predicate=lambda value: value.get("phase") == "playback" and value.get("running") is False)
    time.sleep(0.3)
    static = probe.motion("cap-pulse-dial", "pulse-paused", moving=False)
    cursor = probe.cursor()
    probe.tap("Change intensity")
    intensity = probe.wait_record("SDK_CAP_PULSE_EVENT", pid=pid, after=cursor,
                                 predicate=lambda value: value.get("phase") == "intensity" and value.get("intensity") == 0.3)
    probe.tap("Remove component")
    device.control("Recreate component")
    if any(node.get("resource-id", "").endswith("cap-pulse-dial") for node in device.nodes("pulse-removed")):
        raise RuntimeError("Removed project Flutter component remains mounted")
    device.screenshot("pulse-removed")
    cursor = probe.cursor()
    probe.tap("Recreate component")
    rebuilt = probe.wait_record("SDK_CAP_PULSE_EVENT", pid=pid, after=cursor,
                                predicate=lambda value: value.get("phase") == "mounted" and value.get("running") is False)
    if any(rebuilt.get(key) != intensity.get(key) for key in ("value", "intensity", "changes")):
        raise RuntimeError("Project component recreation lost its applied properties")
    device.control(draft, scroll="up")
    cursor = probe.cursor()
    probe.tap("Pause / resume pulse")
    probe.wait_record("SDK_CAP_PULSE_EVENT", pid=pid, after=cursor,
                      predicate=lambda value: value.get("phase") == "playback" and value.get("running") is True)
    cursor = probe.cursor()
    device.adb("shell", "input", "keyevent", "3")
    background = probe.wait_record("SDK_CAP_PULSE_EVENT", pid=pid, after=cursor,
        predicate=lambda value: value.get("phase") in ("inactive", "hidden", "paused") and value.get("running") is False)
    device.adb("shell", "am", "start", "-W", "-n", device.package + "/" + ACTIVITY)
    foreground = probe.wait_record("SDK_CAP_PULSE_EVENT", pid=pid, after=cursor,
                                   predicate=lambda value: value.get("phase") == "resumed" and value.get("running") is True)
    resumed = probe.motion("cap-pulse-dial", "pulse-resumed")
    device.control(draft, scroll="up")
    if device.pid() != pid:
        raise RuntimeError("Flutter background/resume restarted the app")
    probe.tap("Back", scroll="down")
    device.control("Project capabilities")
    return {"mounted": mounted, "selection": selected, "paused": paused, "intensity": intensity,
            "recreated": rebuilt, "background": background, "foreground": foreground, "draft": draft,
            "pixels": {"playing": playing, "paused": static, "resumed": resumed}}


def exercise_canvas(probe, pid, name, *, story=False):
    device = probe.device
    node = probe.semantic("cap-scale-canvas", name=name + "-ui", scroll="up")
    left, top, right, bottom = device.bounds(node)
    cursor = probe.cursor()
    # Initial visible node (0) is at logical (12, 12); select a visible grid
    # node near the upper left using the actual semantic canvas dimensions.
    device.adb("shell", "input", "tap", left + (right - left) // 12, top + (bottom - top) // 10)
    selected = probe.wait_record("SDK_2D_INPUT", pid=pid, after=cursor,
                                predicate=lambda value: value.get("workload") == "canvas" and value.get("command") == "select"
                                and value.get("selected") is not None)
    cursor = probe.cursor()
    device.adb("shell", "input", "swipe", (left + right) // 2, (top + bottom) // 2,
               (left + right) // 2 + (right - left) // 8, (top + bottom) // 2 + (bottom - top) // 10, 450)
    panned = probe.wait_record("SDK_2D_INPUT", pid=pid, after=cursor,
        predicate=lambda value: value.get("command") == "camera" and value.get("camera") != selected.get("camera"))
    cursor = probe.cursor()
    gesture = probe.pinch(device.bounds(node), name)
    zoomed = probe.wait_record("SDK_2D_INPUT", pid=pid, after=cursor,
        predicate=lambda value: value.get("command") == "camera" and value.get("camera", {}).get("scale", 0)
        > panned["camera"]["scale"] * 1.2)
    probe.tap("Probe input", scroll="down")
    clicked = probe.wait_record("SDK_2D_INPUT", pid=pid, after=cursor,
                               predicate=lambda value: value.get("command") == "probe" and value.get("receipt", 0) >= 1)
    device.nodes(name + "-selected")
    device.screenshot(name + "-selected")
    result = {"selection": selected, "pan": panned, "zoom": zoomed, "pinch_driver": gesture, "probe": clicked}
    if story:
        result["model"] = probe.activity("scale_canvas", pid, after=cursor, predicate=lambda value: (
            value["state"].get("selected") == clicked["selected"]
            and value["state"].get("camera") == clicked["camera"]
            and value["state"].get("input_receipts") == clicked["receipt"]
            and value["state"].get("revision") == clicked["revision"]))
    return result


def check_app_2d(probe, pid):
    device = probe.device
    probe.tap("2D Lab")
    device.control("2D Lab")
    probe.tap("Canvas", scroll="up")
    ready = probe.wait_record("SDK_2D_READY", pid=pid,
        predicate=lambda value: value.get("workload") == "canvas" and value.get("primitives") == 2000
        and value.get("selectable_nodes") == 500)
    canvas = {"workload": ready, **exercise_canvas(probe, pid, "app-canvas")}
    probe.tap("Back", scroll="up")
    device.control("2D Lab")
    probe.tap("Tables", scroll="up")
    device.control("2D Tables")
    device.control("10000 data rows")
    title = "CapabilityRow" + uuid.uuid4().hex[:10]
    # The table screen has two inputs: query first, selected-row draft second.
    probe.edit(title, index=1)
    probe.tap("Save row edit", scroll="down")
    device.control("2D Tables", scroll="up")
    probe.edit(title, index=0)
    cursor = probe.cursor()
    probe.tap("Filter / sort", scroll="up")
    worker = probe.wait_record("SDK_2D_WORKER", pid=pid, after=cursor,
        predicate=lambda value: value.get("workload") == "table" and value.get("phase") == "completed"
        and value.get("matches") == 1)
    device.control("1 matches")
    device.control(title, scroll="down")
    probe.semantic("cap-scale-list", name="table-edited-list", scroll="down")
    device.screenshot("table-edited-list")
    probe.semantic("cap-scale-table", name="table-edited-table", scroll="down")
    device.screenshot("table-edited-table")
    probe.tap("Back", scroll="up")
    device.control("2D Lab")
    probe.tap("Back", scroll="down")
    device.control("Project capabilities")
    return canvas, {"rows": 10000, "list_controls": 1000, "page_rows": 100, "columns": 4,
                    "edited_title": title, "worker": worker, "filtered_matches": 1}


def check_native(probe, pid):
    device = probe.device
    probe.tap("Project notebook", scroll="up")
    probe.tap("Resume notebook story", scroll="down")
    native = None
    for _ in range(8):
        values = [record["data"] for record in probe.records(pid) if record["marker"] == "SDK_2D_READY"
                  and record["data"].get("workload") == "renpy"]
        if values:
            native = values[-1]
            break
        width, height, _ = framebuffer_shape(device.adb("exec-out", "screencap", binary=True))
        device.adb("shell", "input", "tap", width // 2, height * 7 // 8)
        time.sleep(0.4)
    if native is None or any(native.get(key) != value for key, value in
                              (("sprites", 128), ("composite_layers", 8), ("shader_passes", 2))):
        raise RuntimeError("The actual native ATL/compositing/shader workload did not start")
    frame = device.adb("exec-out", "screencap", binary=True)
    width, height, _ = framebuffer_shape(frame)
    pixels = probe.motion(None, "native-atl-compositing-shaders", bounds=[width // 20, height // 4,
                                                                         width * 19 // 20, height * 7 // 10])
    button = native_button_bounds(device.adb("exec-out", "screencap", binary=True))
    device.adb("shell", "input", "tap", (button[0] + button[2]) // 2, (button[1] + button[3]) // 2)
    advance_to_activity(probe, "scale_canvas", "Story Canvas", pid)
    return {"workload": native, "pixels": pixels, "continue_button_pixels": button}


def advance_to_activity(probe, kind, heading, pid):
    for _ in range(10):
        values = [record["data"] for record in probe.records(pid) if record["marker"] == "SDK_CAP_ACTIVITY_STATE"
                  and record["data"].get("kind") == kind]
        if values:
            probe.device.control(heading)
            return values[-1]
        width, height, _ = framebuffer_shape(probe.device.adb("exec-out", "screencap", binary=True))
        probe.device.adb("shell", "input", "tap", width // 2, height * 7 // 8)
        time.sleep(0.4)
    raise RuntimeError("Native story did not start registered activity " + kind)


def check_story_canvas(probe, pid):
    device = probe.device
    interaction = exercise_canvas(probe, pid, "story-canvas", story=True)
    before = interaction["model"]
    quick = probe.quick_save(pid, "canvas")
    cursor = probe.cursor()
    probe.tap("Probe input")
    changed = probe.activity("scale_canvas", pid, after=cursor, predicate=lambda value: (
        value["state"]["input_receipts"] != before["state"]["input_receipts"]))
    if changed["state"] == before["state"]:
        raise RuntimeError("Quick-load proof did not change game values after saving")
    loaded = probe.quick_load(before, "canvas")
    probe.show_restored("Story Canvas")
    # The reopened process must load a newer background snapshot, not merely
    # the quick bookmark. A distinct input makes that distinction observable.
    cursor = probe.cursor()
    probe.tap("Probe input")
    newer = probe.activity("scale_canvas", pid, after=cursor, predicate=lambda value: (
        value["state"]["input_receipts"] == before["state"]["input_receipts"] + 1))
    new_pid, mobile = probe.background_reopen(newer, "canvas")
    probe.show_restored("Story Canvas")
    device.nodes("canvas-fresh-restored")
    device.screenshot("canvas-fresh-restored")
    expected = {"status": "completed", "value": {key: newer["state"][key]
                                                for key in ("selected", "camera", "input_receipts")}}
    probe.tap("Return selection")
    probe.wait_record("SDK_CAP_ACTIVITY_RESULT", pid=new_pid,
                      predicate=lambda value: value.get("kind") == "scale_canvas")
    returned = single_result(probe.records(new_pid), new_pid, "scale_canvas", expected)
    return new_pid, {"interaction": interaction, "result": returned}, {
        "quick_save": quick, "quick_load": loaded, **mobile,
        "newer_than_quick_save": True, "result": returned}


def set_rive_progress(probe, pid, value):
    device = probe.device
    slider = device.control("", control_class="android.widget.SeekBar", scroll="up")
    left, top, right, bottom = device.bounds(slider)
    cursor = probe.cursor()
    device.adb("shell", "input", "tap", (left + right) // 2 if value == 50 else right - 2,
               (top + bottom) // 2)
    return probe.activity("rive_console", pid, after=cursor, predicate=lambda model: model["state"]["progress"] == value)


def ready_components(probe, pid, model, *, after=-1):
    return {role: rive_ready(probe.wait_record("SDK_CAP_RIVE_READY", pid=pid, after=after,
             predicate=lambda value, role=role: value.get("role") == role and value.get("revision") == model["revision"]),
             model["state"], role) for role in ("forest", "signal", "loop")}


def check_story_rive(probe, pid):
    device = probe.device
    initial = advance_to_activity(probe, "rive_console", "Rive transmission console", pid)
    ready = ready_components(probe, pid, initial)
    pixels = probe.motion("cap-rive-loop", "rive-loop-playing")
    cursor = probe.cursor()
    probe.tap("Play the forest and looping rover", scroll="down")
    pause = probe.wait_record("SDK_CAP_RIVE_LIFECYCLE", pid=pid, after=cursor,
        predicate=lambda value: value.get("role") == "loop" and value.get("revision") == initial["revision"]
        and value.get("data", {}).get("active") is False and value.get("data", {}).get("reason") == "properties")
    rive_lifecycle(pause, active=False, reasons=("properties",))
    paused_model = probe.activity("rive_console", pid, after=cursor,
        predicate=lambda value: value["state"]["progress"] == 25 and value["state"]["downloading"] is False)
    time.sleep(0.3)
    paused_pixels = probe.motion("cap-rive-loop", "rive-loop-paused", moving=False)
    cursor = probe.cursor()
    probe.tap("Play the forest and looping rover", scroll="down")
    resume = probe.wait_record("SDK_CAP_RIVE_LIFECYCLE", pid=pid, after=cursor,
        predicate=lambda value: value.get("role") == "loop" and value.get("revision") == initial["revision"]
        and value.get("data", {}).get("active") is True and value.get("data", {}).get("reason") == "properties")
    rive_lifecycle(resume, active=True, reasons=("properties",))
    resumed_model = probe.activity("rive_console", pid, after=cursor,
        predicate=lambda value: value["state"]["progress"] == 25 and value["state"]["downloading"] is True)
    resumed_pixels = probe.motion("cap-rive-loop", "rive-loop-resumed")
    set_rive_progress(probe, pid, 50)
    cursor = probe.cursor()
    probe.tap("Play the forest and looping rover", scroll="down")
    before = probe.activity("rive_console", pid, after=cursor,
                            predicate=lambda value: value["state"]["downloading"] is False)
    applied = probe.wait_record("SDK_CAP_RIVE_INPUT", pid=pid, after=cursor,
        predicate=lambda value: value.get("role") == "forest" and value.get("revision") == before["revision"]
        and value.get("data", {}).get("numbers", {}).get("Progress") == 50
        and value.get("data", {}).get("booleans", {}).get("Downloading") is False)
    quick = probe.quick_save(pid, "rive")
    set_rive_progress(probe, pid, 100)
    loaded = probe.quick_load(before, "rive")
    probe.show_restored("Rive transmission console")
    rebuilt = ready_components(probe, pid, loaded["after"])
    quick_loaded_paused_pixels = probe.motion("cap-rive-loop", "rive-loop-quick-loaded-paused", moving=False)
    # Resume the saved playback boolean before backgrounding. A paused
    # controller cannot report a second effective pause during Android HOME.
    cursor = probe.cursor()
    probe.tap("Play the forest and looping rover", scroll="down")
    newer = probe.activity("rive_console", pid, after=cursor,
                            predicate=lambda value: value["state"]["downloading"] is True)
    # A real lifecycle pause and resume, in the same process, precedes the
    # process-loss check. The background save is inspected before force-stop.
    cursor = probe.cursor()
    device.adb("shell", "input", "keyevent", "3")
    paused = probe.wait_record("SDK_CAP_RIVE_LIFECYCLE", pid=pid, after=cursor,
        predicate=lambda value: value.get("role") == "loop" and value.get("data", {}).get("active") is False
        and value.get("data", {}).get("reason") in ("inactive", "hidden", "paused"))
    rive_lifecycle(paused, active=False, reasons=("inactive", "hidden", "paused"))
    first_mobile = probe.save_bytes(pid, "_reload-1", "rive-background")
    device.adb("shell", "am", "start", "-W", "-n", device.package + "/" + ACTIVITY)
    resumed = probe.wait_record("SDK_CAP_RIVE_LIFECYCLE", pid=pid, after=cursor,
        predicate=lambda value: value.get("role") == "loop" and value.get("data", {}).get("active") is True
        and value.get("data", {}).get("reason") == "resumed")
    rive_lifecycle(resumed, active=True, reasons=("resumed",))
    new_pid, mobile = probe.background_reopen(newer, "rive")
    probe.show_restored("Rive transmission console")
    fresh = ready_components(probe, new_pid, mobile["after"])
    restored_pixels = probe.motion("cap-rive-loop", "rive-loop-fresh-restored-playing")
    device.nodes("rive-fresh-restored")
    completed_model = set_rive_progress(probe, new_pid, 100)
    # This specific forest asset's state machine loops at its terminal 100
    # input. Preserve the game result at 100 and verify the declared visual
    # projection rather than passing that problematic input to the asset.
    completed_inputs = probe.wait_record("SDK_CAP_RIVE_INPUT", pid=new_pid,
        predicate=lambda value: value.get("role") == "forest"
        and value.get("revision") == completed_model["revision"]
        and value.get("data", {}).get("numbers", {}).get("Progress") == 99
        and value.get("data", {}).get("booleans", {}).get("Downloading") is True)
    cursor = probe.cursor()
    probe.tap("Send signal", scroll="down")
    event_record = probe.wait_record("SDK_CAP_RIVE_EVENT", pid=new_pid, after=cursor,
                                    predicate=lambda value: value.get("role") == "signal")
    event = meaningful_rive_event(event_record)
    expected = {"status": "completed", "value": {
        "progress": 100.0, "downloading": True, "signal": event["properties"]}}
    probe.wait_record("SDK_CAP_ACTIVITY_RESULT", pid=new_pid,
                      predicate=lambda value: value.get("kind") == "rive_console")
    returned = single_result(probe.records(new_pid), new_pid, "rive_console", expected)
    probe.wait_native("SDK_RUNNER_APP_STORY", "completed", new_pid)
    completed = probe.wait_record("SDK_CAP_APP_STATE", pid=new_pid,
                                  predicate=lambda value: value.get("phase") == "completed")
    if completed.get("result") != {"story_id": "app-recipe", "outcome": "completed",
                                  "value": "2D journey complete. Canvas: completed; Rive: completed."}:
        raise RuntimeError("The actual cross-boundary story did not return its coherent result")
    cleanup = device.wait(lambda: rive_cleanup(probe.logs(), new_pid), "all three native Rive controller disposals")
    device.nodes("journey-completed")
    device.screenshot("journey-completed")
    return new_pid, {"ready": ready, "applied_inputs": applied, "completed_inputs": completed_inputs,
                    "quick_load_ready": rebuilt, "restored_ready": fresh, "pause": pause, "resume": resume,
                    "pause_model": paused_model, "resume_model": resumed_model,
                    "background": paused, "foreground": resumed, "event": event_record,
                    "pixels": {"initial": pixels, "paused": paused_pixels, "resumed": resumed_pixels,
                               "quick_loaded_paused": quick_loaded_paused_pixels,
                               "restored": restored_pixels}, "result": returned,
                    "cleanup": cleanup}, {
        "quick_save": quick, "quick_load": loaded, **mobile, "background_save": first_mobile,
        "newer_than_quick_save": True, "result": returned, "app_result": completed}


def check_project_capabilities(apk, output, *, source_sha, project_input_sha256, aapt,
                               expected_api=35, package=PACKAGE, run=command):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    receipt_path = output / RECEIPT
    receipt_path.unlink(missing_ok=True)
    if expected_api != 35 or type(expected_api) is not int:
        raise ValueError("Capabilities functionality requires API 35")
    if not re.fullmatch(r"[0-9a-f]{40}", source_sha) or not re.fullmatch(r"[0-9a-f]{64}", project_input_sha256):
        raise ValueError("Expected source/project digests must be complete lowercase hashes")
    if not re.fullmatch(r"org\.renfletpy\.capabilities(?:\.[a-z][a-z0-9_]*)*", package):
        raise ValueError("Data clearing is confined to the capabilities fixture package")
    inspection = inspect_apk(apk, ("x86_64",), "app", build_type="debug", project={
        "application_id": package, "input_sha256": project_input_sha256})
    if inspection["source_sha"] != source_sha:
        raise RuntimeError("Capabilities APK source differs from the expected source")
    expected_observer = inspection["project"]["python_files"].get("capabilities_observer.py")
    if (inspection["project"].get("project_setup") != "capabilities_app:register"
            or not isinstance(expected_observer, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_observer)):
        raise RuntimeError("APK is missing the registered capabilities project/native observer")
    badging, permissions, manifest = (run(aapt, "dump", "badging", apk), run(aapt, "dump", "permissions", apk),
                                      run(aapt, "dump", "xmltree", apk, "AndroidManifest.xml"))
    identity = debug_identity(badging, permissions, manifest, inspection["project"])
    (output / "apk-inspection.json").write_text(json.dumps(inspection, indent=2) + "\n")
    (output / "capabilities-apk-manifest.txt").write_text(badging + "\n" + permissions + "\n" + manifest)
    device, receipt = ProjectDevice(package, output, run), None
    probe = CapabilitiesProbe(device)
    try:
        device.adb("wait-for-device", timeout=180)
        device.wait(lambda: device.adb("shell", "getprop", "sys.boot_completed").strip() == "1", "Android boot")
        api, abi, qemu = (device.adb("shell", "getprop", name).strip() for name in
                          ("ro.build.version.sdk", "ro.product.cpu.abi", "ro.kernel.qemu"))
        if (api, abi, qemu) != ("35", "x86_64", "1"):
            raise RuntimeError("Capabilities functionality requires the API 35 x86_64 emulator")
        serial = device.adb("get-serialno").strip()
        properties = device.adb("shell", "getprop")
        (output / "capabilities-device-getprop.txt").write_text(properties)
        (output / "capabilities-device-serial.txt").write_text(serial + "\n")
        model = device.adb("shell", "getprop", "ro.product.model").strip()
        fingerprint = device.adb("shell", "getprop", "ro.build.fingerprint").strip()
        (output / "capabilities-device-display.txt").write_text(device.adb("shell", "dumpsys", "display"))
        densities = re.findall(r"(?:Physical|Override) density: (\d+)", device.adb("shell", "wm", "density"))
        if not serial or not densities or not model or not fingerprint:
            raise RuntimeError("Missing actual emulator identity/display evidence")
        device.adb("install", "-r", apk, timeout=180)
        installed = device.adb("shell", "dumpsys", "package", package)
        (output / "capabilities-installed-package.txt").write_text(installed)
        if ("Package [" + package + "]" not in installed or "DEBUGGABLE" not in installed
                or not re.search(r"\bversionCode=" + str(identity["version_code"]) + r"\b", installed)
                or not re.search(r"^\s*versionName=" + re.escape(identity["version_name"]) + r"\s*$", installed, re.M)
                or any(permission in installed for permission in FORBIDDEN_PERMISSIONS) or LOCATION_SERVICE in installed):
            raise RuntimeError("Installed capabilities package identity differs")
        paths = device.adb("shell", "pm", "path", package).splitlines()
        if len(paths) != 1 or not re.fullmatch(r"package:/data/app/[A-Za-z0-9_./~=+\-]+/base\.apk", paths[0]):
            raise RuntimeError("Expected one installed capabilities APK")
        installed_digest = device.adb("shell", "sha256sum", paths[0][8:]).split()[0]
        if installed_digest != inspection["sha256"]:
            raise RuntimeError("Installed capabilities APK bytes differ from inspection")
        if device.adb("shell", "pm", "clear", package).strip() != "Success":
            raise RuntimeError("Could not initialize the isolated capabilities fixture")
        device.adb("logcat", "-c")
        initial_pid = probe.start()
        probe.pinch_jar = compile_pinch(output, aapt, run)
        navigation = check_navigation(probe, initial_pid)
        pulse = check_pulse(probe, initial_pid)
        app_canvas, table = check_app_2d(probe, initial_pid)
        native = check_native(probe, initial_pid)
        canvas_pid, canvas, canvas_save = check_story_canvas(probe, initial_pid)
        rive_pid, rive, rive_save = check_story_rive(probe, canvas_pid)
        frame = device.adb("exec-out", "screencap", binary=True)
        width, height, _ = framebuffer_shape(frame)
        all_logs = probe.logs()
        records = marker_records(all_logs)
        owners = {}
        for pid, filename in ((initial_pid, "canvas-source-logcat.txt"), (canvas_pid, "rive-source-logcat.txt"),
                              (rive_pid, "capabilities-logcat.txt")):
            retained = all_logs if filename == "capabilities-logcat.txt" else (output / filename).read_text()
            check_log_errors(retained, probe.pids)
            owners[pid] = owner_proof(marker_records(retained), pid)
            if owners[pid]["source_sha256"] != expected_observer:
                raise RuntimeError("Native observer source differs from the inspected project APK")
        (output / "capabilities-markers.json").write_text(json.dumps(records, indent=2) + "\n")
        receipt = {"schema": 1, "success": True, "source_sha": source_sha, "sha256": inspection["sha256"],
            "project_input_sha256": project_input_sha256, "startup_template": "app", "build_type": "debug",
            "installed_sha256": installed_digest, "identity": identity,
            "device": {"api": 35, "abi": abi, "emulator": True, "serial": serial,
                       "model": model, "build_fingerprint": fingerprint,
                       "display_pixels": [width, height], "density_dpi": int(densities[-1])},
            "pids": {"initial": initial_pid, "canvas_restored": canvas_pid, "rive_restored": rive_pid},
            "native_owners": owners,
            "observer_source_sha256": expected_observer,
            "checks": {"navigation": navigation, "pulse": pulse, "native": native,
                       "canvas": {"app": app_canvas, "story": canvas}, "table": table, "rive": rive,
                       "story_save": {"canvas": canvas_save, "rive": rive_save}},
            "scope": "emulator_functionality", "phone_performance_proven": False, "skips": 0}
    finally:
        primary_error = sys.exc_info()[1]
        try:
            if primary_error is not None:
                device.nodes("capabilities-failed-ui")
                device.screenshot("capabilities-failed")
            logs = device.logs()
            (output / "capabilities-logcat.txt").write_text(logs)
            check_log_errors(logs, probe.pids)
        except Exception as error:
            if primary_error is None:
                raise
            print("Capabilities diagnostic collection also failed: " + str(error), flush=True)
    receipt["artifacts"] = artifact_manifest(output)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Passed: API 35 project capabilities functionality; receipt " + str(receipt_path), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--source-sha", required=True)
    parser.add_argument("--project-input-sha256", required=True)
    parser.add_argument("--aapt", type=Path, required=True)
    parser.add_argument("--expected-api", type=int, choices=(35,), default=35)
    parser.add_argument("--package", default=PACKAGE)
    parser.add_argument("--output", type=Path, default=Path(".android-build/project-capabilities-device"))
    args = parser.parse_args()
    check_project_capabilities(args.apk, args.output, source_sha=args.source_sha,
        project_input_sha256=args.project_input_sha256, aapt=args.aapt,
        expected_api=args.expected_api, package=args.package)


if __name__ == "__main__":
    main()
