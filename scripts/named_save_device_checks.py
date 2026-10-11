"""Real release-APK named saves, native continuation and newer Records."""

import re
import uuid

from scripts.check_project_device import ACTIVITY, ProjectDevice, framebuffer_shape, native_dialogue_pixels


def native_save_directory(trace, pid, package):
    """Resolve the current process's app-owned internal or scoped external root."""
    roots = re.findall(r"SDK_RUNNER_NATIVE_SAVE_DIR path=(\S+) pid=" + re.escape(pid) + r"\b", trace)
    if len(set(roots)) != 1:
        raise RuntimeError("Missing exact native save directory for the current process")
    path = roots[0]
    base = (r"(?:/data/(?:data|user/0)/" + re.escape(package)
            + r"|/storage/emulated/[0-9]+/Android/data/" + re.escape(package) + r")")
    if not re.fullmatch(base + r"/files/saves/app-starter", path):
        raise RuntimeError("Native save directory is outside the installed project")
    return path


def named_save_input(nodes, package):
    """The browser has one editor; Android omits its visual label from XML."""
    nodes = [node for node in nodes if node.get("package") == package]
    if not any("Saved games" in (node.get("text", ""), node.get("content-desc", "")) for node in nodes):
        return None
    fields = []
    for node in nodes:
        if (node.get("class") != "android.widget.EditText" or node.get("enabled") == "false"
                or node.get("visible-to-user") == "false"):
            continue
        try:
            ProjectDevice.bounds(node)
        except RuntimeError:
            continue
        fields.append(node)
    if len(fields) > 1:
        raise RuntimeError("Ambiguous named-save editor")
    return fields[0] if fields else None


def advance_native_dialogue(device):
    """Use the painted framebuffer dimensions; viewport markers have no width."""
    viewport = device.viewport()
    if viewport.get("presentation") != "scene":
        return False
    frame = device.adb("exec-out", "screencap", binary=True)
    if native_dialogue_pixels(frame, viewport) is None:
        return False
    width, height, _ = framebuffer_shape(frame)
    device.adb("shell", "input", "tap", width // 2, height * 7 // 8)
    return True


def check_named_saves(device, heading):
    pid = device.pid()
    suffix = uuid.uuid4().hex[:8]
    intro, choice, temporary = [name + suffix for name in ("Intro", "Choice", "Temporary")]
    record = "NewerRecord" + suffix
    checks = {}

    def logs():
        return device.adb("logcat", "-d", "--pid", device.pid(), "-v", "brief")

    def click(label, scroll="down"):
        device.tap(device.control(label, scroll=scroll))

    def input_text(label, value, previous=""):
        def editor():
            nodes = device.nodes()
            field = named_save_input(nodes, device.package)
            if field is None:
                scroll = next((node for node in nodes if node.get("class") == "android.widget.ScrollView"
                               and node.get("package") == device.package), None)
                if scroll is not None:
                    left, top, right, bottom = device.bounds(scroll)
                    x = left + (right - left) * 4 // 5
                    device.adb("shell", "input", "swipe", x, top + (bottom - top) // 4,
                               x, bottom - (bottom - top) // 4, "350")
            return field
        field = (device.wait(editor, "the named-save editor")
                 if label == "Save name" else
                 device.control("" if label == "Title" else label,
                                control_class="android.widget.EditText", scroll="up"))
        device.tap(field)
        if previous:
            device.adb("shell", "input", "keyevent", "123")
            device.adb("shell", "input", "keyevent", *(["67"] * len(previous)))
        device.adb("shell", "input", "text", value)
        device.adb("shell", "input", "keyevent", "4")

    def native_scene():
        return native_dialogue_pixels(device.adb("exec-out", "screencap", binary=True), device.viewport())

    def to_choice():
        def advance():
            nodes = device.nodes("named-choice")
            if any("Keep a copy" in (node.get("text", "") + node.get("content-desc", "")) for node in nodes):
                return True
            advance_native_dialogue(device)
            return False
        device.wait(advance, "the actual unanswered native note choice")

    def create(title, previous=""):
        input_text("Save name", title, previous)
        click("Create save", "up")
        device.control("Saved: " + title, scroll="up")
        return device.wait(lambda: (re.findall(
            r"SDK_RUNNER_SLOT action=create slot=(renfletpy-manual-[0-9a-f]{32}) pid=" + device.pid() + r"\b",
            logs()) or [None])[-1], "a native named save write")

    def card(title, action):
        # Android's ordered semantics nodes preserve each card's title/actions.
        def find():
            nodes = device.nodes("named-card")
            for index, node in enumerate(nodes):
                if title not in (node.get("text", "") + node.get("content-desc", "")):
                    continue
                for candidate in nodes[index + 1:]:
                    if action not in (candidate.get("text", ""), candidate.get("content-desc", "")):
                        continue
                    try:
                        device.bounds(candidate)
                    except RuntimeError:
                        continue
                    return candidate
            # Bring the requested card into the viewport before matching its action.
            device.control(title, scroll="down")
            scroll = next(node for node in device.nodes()
                          if node.get("class") == "android.widget.ScrollView"
                          and node.get("package") == device.package)
            left, top, right, bottom = device.bounds(scroll)
            x = left + (right - left) * 4 // 5
            device.adb("shell", "input", "swipe", x, top + (bottom - top) * 4 // 5,
                       x, top + (bottom - top) * 2 // 5, "350")
            return None
        device.tap(device.wait(find, "named card action " + action + " for " + title))

    if device.adb("shell", "getprop", "ro.kernel.qemu").strip() != "1":
        raise RuntimeError("This byte-evidence driver requires the authorized CI emulator")
    device.adb("root")
    device.adb("wait-for-device", timeout=60)
    device.wait(lambda: device.adb("shell", "id", "-u").strip() == "0", "emulator file evidence access")
    click("Back", "up")
    device.home(heading, "named-home")
    click("Start story")
    def started():
        if re.search(r"SDK_RUNNER_APP_STORY action=started [^\n]*pid=" + pid + r"\b", logs()):
            return True
        node = next((node for node in device.nodes() if "Start new story" in
                     (node.get("text", "") + node.get("content-desc", ""))), None)
        if node is not None:
            device.tap(node)
        return False
    device.wait(started, "native story start for named saves")
    device.wait(native_scene, "painted initial native dialogue")
    device.adb("shell", "input", "keyevent", "4")
    click("Quick save", "up")
    device.control("Saved.", scroll="up")
    root = native_save_directory(logs(), pid, device.package)

    def digest(slot):
        path = root + "/" + slot + "-LT1.save"
        return device.adb("shell", "sha256sum", path).split()[0]

    protected = {name[:-9]: digest(name[:-9]) for name in device.adb("shell", "ls", root).splitlines()
                 if re.fullmatch(r"(?:app-recipe-quick|auto-[0-9]+)-LT1\.save", name)}
    if "app-recipe-quick" not in protected:
        raise RuntimeError("Missing protected quick bookmark")
    click("Saved games", "up")
    device.control("Saved games loaded.", scroll="up")
    first = create(intro)
    first_hash = digest(first)
    device.adb("shell", "input", "keyevent", "4")
    click("Resume", "up")
    to_choice()
    device.adb("shell", "input", "keyevent", "4")
    click("Saved games", "up")
    device.control("Saved games loaded.", scroll="up")
    second = create(choice)
    second_hash = digest(second)
    card(choice, "Overwrite")
    click("Cancel", "up")
    if digest(second) != second_hash:
        raise RuntimeError("Cancelled overwrite changed its native bookmark")
    card(choice, "Overwrite")
    click("Overwrite save", "up")
    device.control("Saved: " + choice, scroll="up")
    overwritten_hash = digest(second)
    if overwritten_hash == second_hash or digest(first) != first_hash:
        raise RuntimeError("Overwrite did not change exactly the selected native bookmark")
    third = create(temporary, choice)
    card(temporary, "Delete")
    click("Cancel", "up")
    digest(third)
    card(temporary, "Delete")
    click("Delete save", "up")
    device.control("Deleted: " + temporary, scroll="up")
    names = device.adb("shell", "ls", root).splitlines()
    if third + "-LT1.save" in names:
        raise RuntimeError("Deleted native bookmark still exists")
    checks["create_overwrite_delete"] = {"first": first, "second": second, "deleted": third,
                                          "cancel_kept_files": True, "first_sha256": first_hash,
                                          "second_sha256": overwritten_hash}
    device.screenshot("named-browser")
    device.adb("shell", "input", "keyevent", "4")
    click("Return to app", "up")
    device.home(heading, "named-returned-home")
    click("Application records", "up")
    device.control("Records loaded", scroll="down")
    input_text("Title", record)
    click("Add record")
    device.control("Record saved", scroll="down")
    device.control("Title: " + record, scroll="down")
    device.adb("shell", "am", "force-stop", device.package)
    device.wait(lambda: device.pid() is None, "named-save process stopped")
    device.adb("shell", "am", "start", "-W", "-n", device.package + "/" + ACTIVITY)
    restarted = device.wait(lambda: device.pid(), "fresh named-save app process")
    if restarted == pid:
        raise RuntimeError("Named-save reopening reused the old process")
    device.wait(lambda: device.started(restarted), "both renderers and Flet in the fresh process")
    device.home(heading, "named-reopened-home")
    click("Saved games", "up")
    device.control("Saved games loaded.", scroll="up")
    device.control(intro, scroll="down")
    device.control(choice, scroll="up")
    if digest(first) != first_hash or digest(second) != overwritten_hash:
        raise RuntimeError("Named bookmarks changed during forced restart")
    card(choice, "Load")
    click("Load save", "up")
    device.control("Keep a copy")
    device.screenshot("named-choice-restored")
    checks["cold_choice"] = {"fresh_pid": restarted, "unanswered_choice": True}
    device.adb("shell", "input", "keyevent", "4")
    click("Saved games", "up")
    device.control("Saved games loaded.", scroll="up")
    card(intro, "Load")
    click("Load save", "up")
    painted = device.wait(native_scene, "the earlier actual native dialogue after named load")
    device.screenshot("named-intro-restored")
    checks["distinct_position"] = painted
    to_choice()
    click("Keep a copy")
    device.wait(native_scene, "native ending after restored named save")
    device.wait(lambda: advance_native_dialogue(device), "native ending dialogue tap")
    device.wait(lambda: re.search(r"SDK_RUNNER_APP_STORY action=completed [^\n]*pid="
                                  + restarted + r"\b", logs()), "actual native completion")
    device.home(heading, "named-completed-home")
    device.control("You kept a note from the lighthouse.")
    checks["native_completion"] = True
    for slot, expected in protected.items():
        if digest(slot) != expected:
            raise RuntimeError("Named actions changed a protected quick/autosave")
    checks["protected_saves"] = protected
    click("Application records", "up")
    device.control("Records loaded", scroll="down")
    device.control("Title: " + record, scroll="down")
    device.screenshot("named-newer-record-retained")
    checks["newer_record_retained"] = record
    trace = logs()
    (device.output / "named-save-logcat.txt").write_text(trace)
    if "Full traceback:" in trace or "FATAL EXCEPTION" in trace:
        raise RuntimeError("Native exception during named-save acceptance")
    return {"success": True, "skips": 0, "pid": pid, "restarted_pid": restarted, "checks": checks}
