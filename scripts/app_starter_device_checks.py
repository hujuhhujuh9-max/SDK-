"""Verify optional app UI and native save isolation on the actual Android host."""

from contextlib import contextmanager
import hashlib
import io
import json
import re
import struct
import subprocess
import uuid
import zipfile
from pathlib import PurePosixPath

PACKAGE = "org.sdk.runner"
APP_BOOKMARK = "app-recipe-quick-LT1.save"


def app_bookmark_path(directory):
    """Allow fixture writes only to the starter's existing manual bookmark."""
    external = "/storage/emulated/0/Android/data/" + PACKAGE + "/files/saves/app-starter"
    if directory == external:
        directory = "/data/media/0/Android/data/" + PACKAGE + "/files/saves/app-starter"
    else:
        assert directory in {
            "/data/data/" + PACKAGE + "/files/saves/app-starter",
            "/data/user/0/" + PACKAGE + "/files/saves/app-starter",
            "/data/user_de/0/" + PACKAGE + "/files/saves/app-starter",
        }, "Unsigned fixture requires the exact app-starter save directory"
    return directory + "/" + APP_BOOKMARK


def unsigned_bookmark(data):
    """Remove the signature from a real active checkpoint, retaining its payload."""
    with zipfile.ZipFile(io.BytesIO(data)) as source:
        names = source.namelist()
        assert len(names) == len(set(names)), "Ambiguous native bookmark members"
        assert {"log", "json", "signatures"}.issubset(names), "Incomplete native bookmark"
        assert source.read("log") and source.read("signatures"), "The source bookmark must be signed"
        state = json.loads(source.read("json")).get("app_story", {})
        assert (isinstance(state, dict) and state.get("version") == 1 and state.get("story_id") == "app-recipe"
                and state.get("phase") == "active"), "The bookmark must contain the active app recipe"
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as target:
            target.comment = source.comment
            for member in source.infolist():
                if member.filename != "signatures":
                    target.writestr(member, source.read(member))
    return output.getvalue()


@contextmanager
def _rooted_emulator(device):
    assert device.adb("shell", "getprop", "ro.kernel.qemu").strip() == "1", (
        "Unsigned save fixture requires the acceptance emulator")
    assert device.adb("shell", "id", "-u").strip() == "2000", "Fixture must start with ordinary ADB privileges"
    pid = device.runner_pid()
    assert pid.isdigit(), "Fixture requires the existing app process"
    uid = device.adb("shell", "ps", "-p", pid, "-o", "UID").splitlines()[-1].strip()
    assert uid.isdigit() and int(uid) >= 10000, "The app must retain its ordinary Android UID"
    try:
        device.adb("root")
        device.adb("wait-for-device")
        assert device.adb("shell", "id", "-u").strip() == "0", "Fixture requires emulator root"
        yield
    finally:
        device.adb("unroot")
        device.adb("wait-for-device")
        assert device.adb("shell", "id", "-u").strip() == "2000", "Fixture left ADB privileged"
        assert device.runner_pid() == pid, "Fixture restarted the app"
        assert device.adb("shell", "ps", "-p", pid, "-o", "UID").splitlines()[-1].strip() == uid, (
            "Fixture changed the app UID")


def _bookmark_stat(device, path):
    device.adb("shell", "test", "!", "-L", path)
    value = device.adb("shell", "stat", "-c", "%u:%g:%a:%i:%F", path).strip()
    assert re.fullmatch(r"\d+:\d+:[0-7]{3,4}:\d+:regular file", value), "Invalid native bookmark inode"
    return value


def _bookmark_digest(device, path):
    value = device.adb("shell", "sha256sum", path)
    match = re.match(r"([0-9a-f]{64})\s", value)
    assert match, "Missing native bookmark digest"
    return match.group(1)


def _write_bookmark(device, path, local, metadata):
    assert _bookmark_stat(device, path) == metadata, "The bookmark inode or permissions changed"
    staged = "/data/local/tmp/sdk-app-trust-" + uuid.uuid4().hex
    try:
        subprocess.run(["adb", "push", str(local), staged], check=True, capture_output=True, timeout=30)
        # Copy into the existing inode rather than creating an app save as root.
        device.adb("shell", "cp", staged, path)
        assert _bookmark_stat(device, path) == metadata, "Fixture changed bookmark ownership or permissions"
        assert _bookmark_digest(device, path) == hashlib.sha256(local.read_bytes()).hexdigest(), (
            "Native bookmark write did not preserve the exact fixture bytes")
    finally:
        device.adb("shell", "rm", "-f", staged)


@contextmanager
def unsigned_app_bookmark(device, directory, output):
    path = app_bookmark_path(directory)
    signed = output / "app-trust-signed.save"
    unsigned = output / "app-trust-unsigned.save"
    with _rooted_emulator(device):
        metadata = _bookmark_stat(device, path)
        # exec-out has no PTY and must not pass through adb's text decoder.
        data = subprocess.check_output(["adb", "exec-out", "cat", path], timeout=30)
        original_digest = hashlib.sha256(data).hexdigest()
        assert _bookmark_digest(device, path) == original_digest, "Native bookmark changed while being copied"
        signed.write_bytes(data)
        unsigned.write_bytes(unsigned_bookmark(data))
    receipt = {"bookmark": APP_BOOKMARK, "inode_uid_gid_mode": metadata,
               "signed_sha256": original_digest,
               "unsigned_sha256": hashlib.sha256(unsigned.read_bytes()).hexdigest()}
    try:
        with _rooted_emulator(device):
            _write_bookmark(device, path, unsigned, metadata)
        yield receipt
    finally:
        with _rooted_emulator(device):
            _write_bookmark(device, path, signed, metadata)
        receipt["restored_signed_sha256"] = original_digest


def native_prompt_pixels(frame, viewport):
    """Verify B's actual native confirmation before mapping a touch to it."""
    width, height, pixel_format = struct.unpack_from("<III", frame)
    header = len(frame) - width * height * 4
    assert pixel_format == 1 and header in (12, 16), "Expected RGBA_8888 screencap"
    if (viewport.get("presentation") != "scene" or viewport.get("flet_height") != 0
            or viewport.get("ime_overlap") != 0 or viewport.get("scene_height") != viewport.get("height")):
        return None
    scene_height = viewport["scene_height"]
    scale = min(width / 720, scene_height / 1280)
    left = (width - 720 * scale) / 2
    top = viewport["flet_top"] - scene_height + (scene_height - 1280 * scale) / 2

    def point(x, y):
        return round(left + x * scale), round(top + y * scale)

    def pixel(x, y):
        x, y = point(x, y)
        assert 0 <= x < width and 0 <= y < height, "Prompt extends beyond the framebuffer"
        offset = header + (y * width + x) * 4
        return list(frame[offset:offset + 3])

    probes = [(20, 300, (16, 27, 43)), (700, 1000, (16, 27, 43)),
              (115, 835, (66, 104, 94)), (305, 895, (66, 104, 94)),
              (415, 835, (41, 69, 89)), (605, 895, (41, 69, 89))]
    samples = [pixel(x, y) for x, y, _ in probes]
    if not all(all(abs(actual - expected) <= 8 for actual, expected in zip(sample, color))
               for sample, (_, _, color) in zip(samples, probes)):
        return None
    # Require the SDK warning text, not just two colored rectangles.
    message_pixels = sum(all(abs(actual - expected) <= 12
                             for actual, expected in zip(pixel(x, y), (185, 197, 208)))
                         for y in range(410, 700, 2) for x in range(60, 660, 2))
    if message_pixels < 100:
        return None
    return {"viewport": viewport, "width": width, "height": height, "samples": samples,
            "message_pixels": message_pixels, "yes": point(210, 865), "no": point(510, 865)}


def save_directory(logs, marker, pid):
    values = re.findall(re.escape(marker) + r" path=(\S+) pid=" + re.escape(pid) + r"\b", logs)
    if not values:
        return None
    path = values[-1]
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", path) or ".." in PurePosixPath(path).parts:
        raise AssertionError("Unexpected native save-directory marker")
    return path


def native_save_hashes(device, directory):
    if directory.startswith(("/data/data/", "/data/user/", "/data/user_de/")):
        return _native_save_hashes(device, directory, ("shell", "run-as", PACKAGE))
    # Android's scoped external mount permits shell directory listings, but
    # denies reads of the app's save files. Inspect the emulator's backing
    # directory as root, then restore ordinary ADB privileges. The app keeps
    # its own UID and process throughout this read-only snapshot.
    assert directory.startswith("/storage/emulated/0/Android/data/" + PACKAGE + "/files/saves"), (
        "Unexpected external save location")
    assert device.adb("shell", "getprop", "ro.kernel.qemu").strip() == "1", (
        "External save inspection requires the acceptance emulator")
    backing = "/data/media/0/" + directory.removeprefix("/storage/emulated/0/")
    pid = device.runner_pid()
    assert pid.isdigit(), "Save inspection requires the existing app process"
    app_uid = device.adb("shell", "ps", "-p", pid, "-o", "UID").splitlines()[-1].strip()
    assert app_uid.isdigit() and int(app_uid) >= 10000, "The app must retain its ordinary Android UID"
    try:
        device.adb("root")
        device.adb("wait-for-device")
        assert device.adb("shell", "id", "-u").strip() == "0", "Save inspection requires emulator root"
        return _native_save_hashes(device, backing, ("shell",))
    finally:
        device.adb("unroot")
        device.adb("wait-for-device")
        assert device.adb("shell", "id", "-u").strip() == "2000", "Save inspection left ADB privileged"
        assert device.runner_pid() == pid, "Save inspection restarted the app"
        assert device.adb("shell", "ps", "-p", pid, "-o", "UID").splitlines()[-1].strip() == app_uid, (
            "Save inspection changed the app UID")
        print("Verified native save inspection: pid=" + pid + " app_uid=" + app_uid + " shell_uid=2000", flush=True)


def _native_save_hashes(device, directory, prefix):
    names = device.adb(*prefix, "ls", directory).splitlines()
    result = {}
    for name in names:
        if not name.endswith(".save"):
            continue
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", name):
            raise AssertionError("Unexpected native save filename")
        try:
            content = device.adb(*prefix, "sha256sum", directory + "/" + name)
        except subprocess.CalledProcessError as error:
            print("Native save inspection failed: " + (error.stderr or str(error)), flush=True)
            raise
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

    def wait_native_prompt(self, name, pid):
        def visible():
            viewport = (self.device.json_markers(
                self.device.markers(), "SDK_RUNNER_VIEWPORT ") or [{}])[-1]
            frame = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
            return native_prompt_pixels(frame, viewport)
        evidence = self.device.wait_for(visible, 45)
        assert self.device.runner_pid() == pid, "Native confirmation restarted the app"
        self.device.story_screenshot(self.output, name)
        (self.output / (name + ".json")).write_text(json.dumps(evidence, indent=2) + "\n")
        return evidence

    def check_unsigned_resume(self, directory, pid, edited):
        device = self.device
        restored = device.markers().count("SDK_RUNNER_APP_STORY action=restored ")
        with unsigned_app_bookmark(device, directory, self.output) as evidence:
            self.click("Resume story")
            refused = self.wait_native_prompt("app-trust-no-prompt", pid)
            # A route intent arriving during native confirmation must stay
            # pending and must not put Flutter over the native buttons.
            records_link = "/app/records?probe=unsigned-resume-refused"
            self.link(records_link)
            refused = self.wait_native_prompt("app-trust-no-after-link", pid)
            device.adb("shell", "input", "tap", *refused["no"])
            self.control("Title: " + edited, down=True)
            device.wait_for(lambda: (device.json_markers(
                device.markers(), "SDK_RUNNER_VIEWPORT ") or [{}])[-1]
                .get("presentation") == "page", 45)
            assert device.markers().count("SDK_RUNNER_APP_STORY action=restored ") == restored, (
                "Refusing the unsigned bookmark restored a checkpoint")
            self.click("Back", up=True)
            self.control("Resume cancelled.")
            self.control("Story complete", up=True)
            self.control("You kept a note from the lighthouse.")
            assert self.control("Resume story").get("enabled") == "true", (
                "Refusing native confirmation left Resume busy")
            assert device.runner_pid() == pid
            self.checks.append("native unsigned Resume refusal preserves newer records navigation and releases busy")

            self.click("Resume story")
            accepted = self.wait_native_prompt("app-trust-yes-prompt", pid)
            device.adb("shell", "input", "tap", *accepted["yes"])
            self.wait_app_action("restored", pid, restored)
            assert re.search(r"SDK_RUNNER_APP_STORY action=restored phase=active [^\n]*pid="
                             + re.escape(pid) + r"\b", device.markers()), (
                "Accepting native confirmation did not restore an active checkpoint")
            assert self.control("Keep a copy").get("enabled") == "true"
            completed = device.markers().count("SDK_RUNNER_APP_STORY action=completed ")
            self.click("Keep a copy")
            self.wait_native_scene()
            self.advance_native()
            self.wait_app_action("completed", pid, completed)
            self.control("Story complete", up=True)
            self.control("You kept a note from the lighthouse.")
            self.link("/app/records?probe=unsigned-resume-accepted")
            self.control("Title: " + edited, down=True)
            self.click("Back", up=True)
            self.control("App home", up=True)
            assert device.runner_pid() == pid
            evidence.update({"pid": pid, "refused_records_link": records_link,
                             "no": refused, "yes": accepted})
        self.trust_receipt = evidence
        self.checks.append("native unsigned Resume acceptance restores the real bookmark and completes without reverting records")

    def background(self):
        count = self.device.markers().count("Entered background. --------------------------------------------")
        self.device.adb("shell", "input", "keyevent", "3")
        self.device.wait_for(lambda: self.device.markers().count(
            "Entered background. --------------------------------------------") > count, 45)

    def check_unsigned_quick_load(self, directory, pid, edited):
        device = self.device
        restored = device.markers().count("SDK_RUNNER_APP_STORY action=restored ")
        with unsigned_app_bookmark(device, directory, self.output) as evidence:
            self.link("/menu")
            self.click("Quick load")
            self.wait_native_prompt("app-quick-trust-no-prompt", pid)
            refused_link = "/app/records?probe=unsigned-quick-refused"
            self.link(refused_link)
            refused = self.wait_native_prompt("app-quick-trust-no-after-link", pid)
            device.adb("shell", "input", "tap", *refused["no"])
            self.control("Title: " + edited, down=True)
            assert device.markers().count("SDK_RUNNER_APP_STORY action=restored ") == restored, (
                "Refusing Quick load restored a native checkpoint")
            self.link("/menu")
            self.control("Load cancelled.")
            assert self.control("Quick load").get("enabled") == "true", (
                "Refusing Quick load left the menu busy")
            self.checks.append("native unsigned Quick load refusal preserves newer records navigation and releases busy")

            self.click("Quick load")
            self.wait_native_prompt("app-quick-trust-yes-prompt", pid)
            accepted_link = "/app/records?probe=unsigned-quick-accepted"
            self.link(accepted_link)
            accepted = self.wait_native_prompt("app-quick-trust-yes-after-link", pid)
            device.adb("shell", "input", "tap", *accepted["yes"])
            self.wait_app_action("restored", pid, restored)
            self.control("Title: " + edited, down=True)
            self.link("/menu")
            self.control("Loaded saved game.")
            assert self.control("Quick load").get("enabled") == "true", (
                "Accepting Quick load left the menu busy")
            self.link("/app")
            self.click("Resume story")
            self.control("Keep a copy")
            completed = device.markers().count("SDK_RUNNER_APP_STORY action=completed ")
            self.click("Keep a copy")
            self.wait_native_scene()
            self.advance_native()
            self.wait_app_action("completed", pid, completed)
            self.control("Story complete", up=True)
            assert device.runner_pid() == pid, "Quick load restarted the app"
            evidence.update({"pid": pid, "refused_records_link": refused_link,
                             "accepted_records_link": accepted_link, "no": refused, "yes": accepted})
        self.quick_load_trust_receipt = evidence
        self.checks.append("native unsigned Quick load acceptance restores the bookmark without reverting newer records or routing")

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
        app_uid = device.adb("shell", "ps", "-p", source_pid, "-o", "UID").splitlines()[-1].strip()
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
        assert re.search(r"SDK_RUNNER_APP_STORY action=restored phase=completed [^\n]*pid="
                         + re.escape(restored_pid) + r"\b", device.markers()), "Cold recovery lost completed phase"
        self.click("Back", up=True)
        self.control("Story complete", up=True)
        self.control("You kept a note from the lighthouse.")
        self.checks.append("cold explicit records link and completed native recovery retain current data")
        self.check_unsigned_resume(app_directory, restored_pid, edited)
        self.check_unsigned_quick_load(app_directory, restored_pid, edited)
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
                   "app_uid": app_uid,
                   "restored_pid": restored_pid, "default_restored_pid": default_pid,
                   "default_save_directory": baseline["directory"], "app_save_directory": app_directory,
                   "save_digest_reader": "read-only emulator root backing files; restored shell UID 2000",
                   "saved_resume_confirmation": self.trust_receipt,
                   "quick_load_confirmation": self.quick_load_trust_receipt,
                   "default_save_hashes": baseline["save_hashes"], "checks": self.checks}
        (self.output / "app-starter.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print("Passed: optional app starter: " + json.dumps(receipt), flush=True)


def seed_default_story(apk, output, device):
    return AppDeviceScenario(output, device).seed_default(apk)


def check_app_starter(output, device, baseline, baseline_apk):
    (output / "app-starter.json").unlink(missing_ok=True)
    AppDeviceScenario(output, device).run(baseline, baseline_apk)
