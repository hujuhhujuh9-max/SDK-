"""Verify optional app UI and native save isolation on the actual Android host."""

import json
import re
import struct
import subprocess
from pathlib import PurePosixPath

PACKAGE = "org.sdk.runner"


def save_directory(logs, marker, pid):
    values = re.findall(re.escape(marker) + r" path=(\S+) pid=" + re.escape(pid) + r"\b", logs)
    if not values:
        return None
    path = values[-1]
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or ".." in PurePosixPath(path).parts:
        raise AssertionError("Unexpected native save-directory marker")
    return path


def native_save_hashes(device, directory):
    names = device.adb("shell", "run-as", PACKAGE, "ls", directory).splitlines()
    result = {}
    for name in names:
        if not name.endswith(".save"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise AssertionError("Unexpected native save filename")
        content = device.adb("shell", "run-as", PACKAGE, "sha256sum", directory + "/" + name)
        match = re.match(r"([0-9a-f]{64})\s", content)
        assert match, "Native save digest was not returned"
        result[name] = match.group(1)
    return result


def assert_native_saves_retained(before, after):
    assert before and "_reload-1-LT1.save" in before and "renfletpy-quick-LT1.save" in before, (
        "The default baseline lacks real quick/mobile saves")
    assert after == before, "App mode changed or consumed the default story's native saves"


class AppDeviceScenario:
    def __init__(self, output, device):
        self.output, self.device = output, device
        self.checks = []

    def control(self, label, *, up=False, down=False):
        return self.device.wait_for(lambda: self.device.find_control(
            label, self.output / "app-ui.xml", scroll_up=up, scroll_down=down), 45)

    def click(self, label, **options):
        self.device.tap(self.control(label, **options))

    def link(self, route):
        self.device.adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
                        "-d", "sdk-runner://" + route)

    def title(self, value, previous=""):
        field = self.device.wait_for(lambda: self.device.find_control(
            "", self.output / "app-record-input.xml", scroll_up=True,
            control_class="android.widget.EditText"), 45)
        self.device.tap(field)
        if previous:
            self.device.adb("shell", "input", "keyevent", "123")
            self.device.adb("shell", "input", "keyevent", *(["67"] * len(previous)))
        self.device.adb("shell", "input", "text", value)
        self.device.adb("shell", "input", "keyevent", "4")

    def wait_app_action(self, action, pid, after=0):
        marker = "SDK_RUNNER_APP_STORY action=" + action + " "
        return self.device.wait_for(lambda: self.device.markers().count(marker) > after
                                    and re.search(re.escape(marker) + r"[^\n]*pid="
                                                  + re.escape(pid) + r"\b", self.device.markers()), 45)

    def advance_native(self):
        frame = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
        width, height = struct.unpack_from("<II", frame)
        self.device.adb("shell", "input", "tap", width // 2, height * 7 // 8)

    def wait_native_scene(self):
        self.device.wait_for(lambda: (self.device.json_markers(
            self.device.markers(), "SDK_RUNNER_VIEWPORT ") or [{}])[-1]
            .get("presentation") == "scene", 45)

    def background(self):
        count = self.device.markers().count("Entered background. --------------------------------------------")
        self.device.adb("shell", "input", "keyevent", "3")
        self.device.wait_for(lambda: self.device.markers().count(
            "Entered background. --------------------------------------------") > count, 45)

    def stop(self):
        self.device.adb("shell", "am", "force-stop", PACKAGE)
        self.device.wait_for(lambda: not self.device.runner_pid(), 30)

    def seed_default(self, apk):
        self.device.adb("install", "-r", apk)
        self.device.adb("logcat", "-c")
        self.device.adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.RunnerActivity")
        self.device.wait_for_startup()
        pid = self.device.runner_pid()
        self.device.wait_for(lambda: "SDK_RUNNER_SCENE stage=opening pid=" + pid
                             in self.device.markers(), 45)
        directory = self.device.wait_for(lambda: save_directory(
            self.device.markers(), "SDK_RUNNER_NATIVE_SAVE_DIR", pid), 30)
        self.link("/menu")
        count = self.device.markers().count("SDK_RUNNER_SAVE action=saved ")
        self.click("Quick save")
        self.device.wait_for(lambda: self.device.markers().count(
            "SDK_RUNNER_SAVE action=saved ") > count, 45)
        self.control("Saved. You can return here")
        self.background()
        hashes = self.device.wait_for(lambda: self.default_hashes_if_ready(directory), 45)
        self.stop()
        return {"pid": pid, "directory": directory, "save_hashes": hashes}

    def default_hashes_if_ready(self, directory):
        hashes = native_save_hashes(self.device, directory)
        return hashes if "_reload-1-LT1.save" in hashes and "renfletpy-quick-LT1.save" in hashes else None

    def run(self, baseline, baseline_apk):
        device = self.device
        source_pid = device.runner_pid()
        self.control("App home", up=True)
        self.wait_app_action("ready", source_pid)
        app_directory = device.wait_for(lambda: save_directory(
            device.markers(), "SDK_RUNNER_APP_SAVE_DIR", source_pid), 30)
        assert app_directory == baseline["directory"].rstrip("/") + "/app-starter"
        assert_native_saves_retained(baseline["save_hashes"], native_save_hashes(device, baseline["directory"]))
        self.checks.append("explicit app startup leaves real default quick/mobile saves untouched")
        device.story_screenshot(self.output, "app-home")

        title = "AppRecord" + source_pid
        edited = title + "Updated"
        self.click("Application records")
        self.control("Records loaded")
        self.click("Add record")
        self.control("Title is required")
        self.title(title)
        self.click("Add record")
        self.control("Record saved")
        self.control("Title: " + title, down=True)
        self.click("Back", up=True)
        self.control("App home", up=True)
        self.checks.append("app records use native preferences and contextual Back returns home")

        started = device.markers().count("SDK_RUNNER_APP_STORY action=started ")
        self.click("Start story")
        self.wait_app_action("started", source_pid, started)
        self.wait_native_scene()
        device.adb("shell", "input", "keyevent", "4")
        returned = device.markers().count("SDK_RUNNER_APP_STORY action=return ")
        self.click("Return to app")
        self.wait_app_action("return", source_pid, returned)
        self.control("App home", up=True)
        resumed = device.markers().count("SDK_RUNNER_APP_STORY action=resume ")
        self.click("Resume story")
        self.wait_app_action("resume", source_pid, resumed)
        self.wait_native_scene()
        self.advance_native()
        self.control("Keep a copy")
        assert device.runner_pid() == source_pid
        self.checks.append("Start Return and live Resume keep one native interaction in one process")

        device.adb("shell", "input", "keyevent", "4")
        saved = device.markers().count("SDK_RUNNER_SAVE action=saved ")
        self.click("Quick save")
        device.wait_for(lambda: device.markers().count("SDK_RUNNER_SAVE action=saved ") > saved, 45)
        self.link("/app/records?probe=edit-after-save")
        self.control("Title: " + title, down=True)
        self.click("Edit", down=True)
        self.title(edited, title)
        self.click("Save changes")
        self.control("Record saved")
        self.link("/menu")
        loaded = device.markers().count("SDK_RUNNER_SAVE action=loaded ")
        self.click("Quick load")
        device.wait_for(lambda: device.markers().count("SDK_RUNNER_SAVE action=loaded ") > loaded, 45)
        self.link("/app/records?probe=after-native-load")
        self.control("Title: " + edited, down=True)
        self.checks.append("loading an older real native checkpoint preserves newer application records")
        self.click("Back", up=True)
        self.click("Resume story")
        self.control("Keep a copy")
        completed = device.markers().count("SDK_RUNNER_APP_STORY action=completed ")
        self.click("Keep a copy")
        self.wait_native_scene()
        self.advance_native()
        self.wait_app_action("completed", source_pid, completed)
        self.control("Story complete", up=True)
        self.control("You kept a note from the lighthouse.")
        assert device.runner_pid() == source_pid
        self.checks.append("native completion returns one visible plain result without quitting")

        for query in ("one", "two"):
            self.link("/app/records?probe=" + query)
            self.control("Title: " + edited, down=True)
            device.adb("shell", "input", "keyevent", "4")
            self.control("App home", up=True)
        device.background_and_resume()
        self.control("App home", up=True)
        assert device.runner_pid() == source_pid
        self.checks.append("warm links Back and background resume preserve the app session")
        self.link("/app/records?probe=before-cold")
        self.control("Title: " + edited, down=True)
        self.background()
        self.stop()
        self.link("/app/records?probe=cold")
        device.wait_for_startup()
        restored_pid = device.runner_pid()
        assert restored_pid != source_pid
        self.control("Title: " + edited, down=True)
        self.wait_app_action("restored", restored_pid)
        self.checks.append("cold explicit records link and completed native recovery retain current data")
        assert_native_saves_retained(baseline["save_hashes"], native_save_hashes(device, baseline["directory"]))
        self.checks.append("app manual and mobile recovery never consume default native saves")

        self.stop()
        device.adb("install", "-r", baseline_apk)
        device.adb("logcat", "-c")
        device.adb("shell", "am", "start", "-W", "-n", PACKAGE + "/.RunnerActivity")
        device.wait_for_startup()
        default_pid = device.runner_pid()
        assert default_pid not in (baseline["pid"], source_pid, restored_pid)
        device.wait_for(lambda: re.search(r"SDK_RUNNER_SAVE action=loaded kind=scene progress=0 pid="
                                         + re.escape(default_pid) + r"\b", device.markers()), 45)
        self.link("/records?probe=default-after-app")
        self.control("Title: " + edited, down=True)
        self.checks.append("reinstalling default loads its original recovery and retains shared app records")
        receipt = {"startup_template": "app", "success": True,
                   "scope": "actual Android UI native story saves and same-source APK mode switching",
                   "baseline_pid": baseline["pid"], "source_pid": source_pid,
                   "restored_pid": restored_pid, "default_restored_pid": default_pid,
                   "default_save_hashes": baseline["save_hashes"], "checks": self.checks}
        (self.output / "app-starter.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("Passed: optional app starter: " + json.dumps(receipt), flush=True)


def seed_default_story(apk, output, device):
    return AppDeviceScenario(output, device).seed_default(apk)


def check_app_starter(output, device, baseline, baseline_apk):
    (output / "app-starter.json").unlink(missing_ok=True)
    AppDeviceScenario(output, device).run(baseline, baseline_apk)
