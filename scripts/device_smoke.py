"""Check both renderers and shared Python state on a connected Android device."""

import argparse
import hashlib
import json
import os
import re
import struct
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path


if not __package__:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.check_apk import SUPPORTED_ABIS, inspect_apk
from runtime.core_capability_checks import CORE_SERVICE_TYPES


def adb(*args, timeout=60):
    # ADB can briefly drop a live emulator during a large log read. Retry only
    # snapshots; taps, intents and other mutations must never execute twice.
    ui_dump = args[:3] == ("shell", "uiautomator", "dump")
    snapshot = ui_dump or args[:2] in (("logcat", "-d"), ("shell", "dumpsys"), ("devices", "-l"))
    for attempt in range(3 if snapshot else 1):
        try:
            return subprocess.check_output(["adb", *map(str, args)], text=True,
                                           stderr=subprocess.PIPE, timeout=timeout)
        except subprocess.CalledProcessError as error:
            transient = (error.returncode == 255 or "device offline" in (error.stderr or "")
                         or (ui_dump and error.returncode == 137))
            if not snapshot or not transient or attempt == 2:
                raise
            print("Retrying Android snapshot after a transient read failure.", flush=True)
            time.sleep(1)


def wait_for(check, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result is not None and result is not False:
            return result
        time.sleep(1)
    raise RuntimeError("Android smoke check timed out")


def markers():
    return adb("logcat", "-d", "-v", "brief")


def runner_pid():
    result = subprocess.run(["adb", "shell", "pidof", "org.sdk.runner"],
                            capture_output=True, text=True, timeout=15)
    candidates = result.stdout.split()
    if len(candidates) > 1:
        # Native Python can briefly fork a helper before exec. It inherits the
        # package name, so pidof alone cannot distinguish it from the app.
        rows = adb("shell", "ps", "-A", "-o", "PID,PPID").splitlines()
        parents = dict(row.split() for row in rows if len(row.split()) == 2
                       and all(value.isdigit() for value in row.split()))
        roots = [pid for pid in candidates if pid in parents
                 and parents[pid] not in candidates]
        if len(roots) == 1:
            print("App process: pid=" + roots[0] + " helper_pids=" +
                  ",".join(pid for pid in candidates if pid != roots[0]), flush=True)
            return roots[0]
    return " ".join(candidates)


def focused_window():
    return " | ".join(line.strip() for line in adb("shell", "dumpsys", "window").splitlines()
                      if "mCurrentFocus=" in line)


def wait_for_startup():
    expected_pid = wait_for(runner_pid, 30)
    assert len(expected_pid.split()) == 1, ("Unexpected runner processes", expected_pid)
    last_recovery = time.monotonic()
    recoveries = 0

    def ready():
        nonlocal last_recovery, recoveries
        current_pid = runner_pid()
        assert current_pid == expected_pid, ("Runner exited or restarted during startup",
                                             expected_pid, current_pid)
        focus = focused_window()
        if "org.sdk.runner" not in focus or "RunnerActivity" not in focus:
            # Emulator setup/overlay changes can send the newly launched app
            # behind Launcher. Restore its existing Activity, never a dead process.
            if time.monotonic() - last_recovery >= 5:
                assert recoveries < 3, ("Runner repeatedly lost startup focus", focus)
                recoveries += 1
                print("Startup foreground recovery " + str(recoveries) +
                      ": pid=" + expected_pid + " focus=" + focus, flush=True)
                adb("shell", "am", "start", "-W", "--activity-reorder-to-front",
                    "-n", "org.sdk.runner/.RunnerActivity")
                assert runner_pid() == expected_pid, "Foreground recovery restarted Runner"
                last_recovery = time.monotonic()
            return None
        logs = markers()
        return logs if all(marker + " pid=" + expected_pid in logs for marker in
                           ("SDK_RUNNER_FLUTTER_ATTACHED", "SDK_RUNNER_RENPY_READY",
                            "SDK_RUNNER_FLET_READY")) else None

    return wait_for(ready)


def renpy_rendered(output, expected=(27, 40, 56), y_fraction=0.3):
    # Android screencap emits a raw RGBA framebuffer after its header. Probe
    # the fixed sample's dark-blue SDL canvas, above the Flutter panel.
    frame = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
    width, height, pixel_format = struct.unpack_from("<III", frame)
    header = len(frame) - width * height * 4
    assert pixel_format == 1 and header in (12, 16), "Expected an RGBA_8888 screenshot"
    y = int(height * y_fraction)
    samples = []
    for n in (1, 2, 3, 4):
        pixel = header + (y * width + width * n // 5) * 4
        samples.append(list(frame[pixel:pixel + 3]))
    output.write_text(json.dumps({"width": width, "height": height, "samples": samples}))
    return any(all(abs(actual - target) <= 8
                   for actual, target in zip(sample, expected))
               for sample in samples)


def story_screenshot(output, name):
    remote = "/sdcard/runner-story.png"
    adb("shell", "screencap", "-p", remote)
    adb("pull", remote, output / (name + ".png"))


def check_story(output):
    """Exercise native dialogue, Flet interludes and native save recovery."""
    pid = runner_pid()
    save_source_pid = pid
    def minigame_button(label):
        return wait_for(lambda: next((node for node in controls(output / "story-minigame.xml")
            if node.get("class") == "android.widget.Button"
            and (node.get("text", "") + node.get("content-desc", "")).strip() == label), None), 30)

    def reading_settings(large, name, speed="instant", change=False):
        # Enter from the current story interaction and return to it without
        # advancing dialogue or resetting an active puzzle.
        adb("shell", "input", "keyevent", "4")
        tap(minigame_button("Reading settings"))
        if change:
            tap(minigame_button("Larger" if large else "Standard"))
        wait_for(lambda: find_control("Text size: " + ("Larger" if large else "Standard"),
                                      output / "story-reading-settings.xml"), 30)
        wait_for(lambda: find_control("Dialogue: " + ("Instant" if speed == "instant" else "Animated"),
                                      output / "story-reading-settings.xml"), 30)
        story_screenshot(output, name)
        adb("shell", "input", "keyevent", "4")
        tap(minigame_button("Resume"))

    def scene(stage, color):
        wait_for(lambda: "SDK_RUNNER_SCENE stage=" + stage + " pid=" + pid in markers(), 30)
        wait_for(lambda: renpy_rendered(output / ("story-" + stage + "-scene.json"), color, 0.15), 30)
        def scene_viewport():
            viewports = json_markers(markers(), "SDK_RUNNER_VIEWPORT ")
            return viewports[-1] if viewports and viewports[-1]["presentation"] == "scene" else None
        viewport = wait_for(scene_viewport, 30)
        assert viewport["scene_height"] == viewport["height"] and viewport["flet_height"] == 0, viewport
        return viewport

    viewport = scene("opening", (24, 38, 53))
    story_screenshot(output, "story-initial")
    opening_count = markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid)
    adb("shell", "input", "keyevent", "4")
    wait_for(lambda: find_control("Resume", output / "story-menu.xml"), 30)
    story_screenshot(output, "story-menu")
    adb("shell", "input", "keyevent", "4")
    scene("opening", (24, 38, 53))
    assert markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid) == opening_count

    reading_settings(True, "story-larger-settings", change=True)
    wait_for(lambda: "SDK_RUNNER_READING large_text=True text_cps=0 pid=" + pid in markers(), 30)
    scene("opening", (24, 38, 53))
    story_screenshot(output, "story-larger-native")
    adb("shell", "input", "keyevent", "4")
    tap(minigame_button("Reading settings"))
    tap(minigame_button("Animated"))
    wait_for(lambda: "SDK_RUNNER_READING large_text=True text_cps=30 pid=" + pid in markers(), 30)
    wait_for(lambda: find_control("Dialogue: Animated", output / "story-reading-animated.xml"), 30)
    story_screenshot(output, "story-reading-animated")
    tap(minigame_button("Instant"))
    wait_for(lambda: find_control("Dialogue: Instant", output / "story-reading-instant.xml"), 30)
    adb("shell", "input", "keyevent", "4")
    tap(minigame_button("Resume"))
    assert markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid) == opening_count

    # This tap advances an ordinary native Ren'Py say interaction.
    frame = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
    width, height = struct.unpack_from("<II", frame)
    adb("shell", "input", "tap", width // 2, height * 7 // 8)
    minigame_button("Deneb")
    assert json_markers(markers(), "SDK_RUNNER_VIEWPORT ")[-1]["presentation"] == "interlude"
    story_screenshot(output, "story-minigame")
    tap(minigame_button("Altair"))
    wait_for(lambda: find_control("Start with Deneb", output / "story-wrong-star.xml"), 30)
    tap(minigame_button("Deneb"))
    wait_for(lambda: find_control("Stars connected: 1 / 3", output / "story-progress.xml"), 30)
    adb("shell", "input", "keyevent", "3")
    adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
    wait_for(lambda: find_control("Stars connected: 1 / 3", output / "story-background-resumed.xml"), 30)
    adb("shell", "input", "keyevent", "4")
    wait_for(lambda: find_control("Resume", output / "story-menu.xml"), 30)
    tap(minigame_button("Quick save"))
    wait_for(lambda: "SDK_RUNNER_SAVE action=saved progress=1 pid=" + pid in markers(), 30)
    wait_for(lambda: find_control("Saved. You can return here", output / "story-saved.xml"), 30)
    story_screenshot(output, "story-save-menu")
    tap(wait_for(lambda: find_control("Resume", output / "story-menu.xml"), 30))
    wait_for(lambda: find_control("Stars connected: 1 / 3", output / "story-resumed.xml"), 30)
    tap(minigame_button("Vega"))
    wait_for(lambda: find_control("Stars connected: 2 / 3", output / "story-progress.xml"), 30)
    reading_settings(False, "story-reading-changed-after-save", change=True)
    adb("shell", "input", "keyevent", "4")
    tap(minigame_button("Quick load"))
    wait_for(lambda: "SDK_RUNNER_SAVE action=loaded kind=star_map progress=1 pid=" + pid in markers(), 30)
    wait_for(lambda: find_control("Stars connected: 1 / 3", output / "story-loaded.xml"), 30)
    assert runner_pid() == pid, "Loading a minigame restarted the runner"
    story_screenshot(output, "story-minigame-loaded")
    reading_settings(False, "story-reading-kept-after-load")
    reading_settings(True, "story-reading-large-again", change=True)
    wait_for(lambda: find_control("Stars connected: 1 / 3", output / "story-loaded.xml"), 30)

    # Load the same native save after a forced process restart. A fresh backend
    # must render the stored interlude, rather than start a new puzzle.
    adb("shell", "am", "force-stop", "org.sdk.runner")
    wait_for(lambda: not runner_pid(), 30)
    adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
    wait_for_startup()
    pid = runner_pid()
    assert pid != save_source_pid, "Cold save test did not start a fresh process"
    scene("opening", (24, 38, 53))
    opening_count = markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid)
    adb("shell", "input", "keyevent", "4")
    tap(minigame_button("Quick load"))
    wait_for(lambda: "SDK_RUNNER_SAVE action=loaded kind=star_map progress=1 pid=" + pid in markers(), 30)
    wait_for(lambda: find_control("Stars connected: 1 / 3", output / "story-cold-loaded.xml"), 30)
    story_screenshot(output, "story-minigame-cold-loaded")
    reading_settings(True, "story-reading-kept-cold")
    wait_for(lambda: find_control("Stars connected: 1 / 3", output / "story-cold-loaded.xml"), 30)
    tap(minigame_button("Vega"))
    wait_for(lambda: find_control("Stars connected: 2 / 3", output / "story-progress.xml"), 30)
    # Save a newer move through Android's own background path, without touching
    # the quick bookmark, then lose the process while it remains backgrounded.
    background_source_pid = pid
    backgrounds = markers().count("Entered background. --------------------------------------------")
    adb("shell", "input", "keyevent", "3")
    wait_for(lambda: markers().count("Entered background. --------------------------------------------") > backgrounds, 30)
    adb("shell", "am", "force-stop", "org.sdk.runner")
    wait_for(lambda: not runner_pid(), 30)
    adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
    wait_for_startup()
    pid = runner_pid()
    assert pid != background_source_pid, "Background recovery reused the old process"
    wait_for(lambda: "SDK_RUNNER_SAVE action=loaded kind=star_map progress=2 pid=" + pid in markers(), 30)
    wait_for(lambda: find_control("Stars connected: 2 / 3", output / "story-auto-recovered.xml"), 30)
    story_screenshot(output, "story-background-recovered")
    reading_settings(True, "story-reading-background-recovered")
    wait_for(lambda: find_control("Stars connected: 2 / 3", output / "story-auto-recovered.xml"), 30)
    # Recovery is a separate native save: the manual one-star bookmark remains.
    adb("shell", "input", "keyevent", "4")
    tap(minigame_button("Quick load"))
    wait_for(lambda: find_control("Stars connected: 1 / 3", output / "story-quick-preserved.xml"), 30)
    tap(minigame_button("Vega"))
    wait_for(lambda: find_control("Stars connected: 2 / 3", output / "story-progress.xml"), 30)
    tap(minigame_button("Altair"))
    scene("aligned", (33, 59, 74))
    assert "result=aligned pid=" + pid in markers(), "Minigame result did not return to Ren'Py"
    story_screenshot(output, "story-branch")

    # Native dialogue and completed interludes appear together in scene order.
    adb("shell", "input", "keyevent", "4")
    tap(wait_for(lambda: find_control("Story history", output / "story-menu.xml"), 30))
    wait_for(lambda: find_control("You made it before sunrise", output / "story-history.xml"), 30)
    wait_for(lambda: find_control("→ Constellation aligned", output / "story-history.xml"), 30)
    wait_for(lambda: find_control("You found it", output / "story-history.xml"), 30)
    story_screenshot(output, "story-history")
    adb("shell", "input", "keyevent", "4")
    tap(minigame_button("Quick save"))
    wait_for(lambda: "SDK_RUNNER_SAVE action=saved progress=0 pid=" + pid in markers(), 30)
    tap(wait_for(lambda: find_control("Resume", output / "story-menu.xml"), 30))
    scene("aligned", (33, 59, 74))
    # The next Flet panel returns a journal choice to ordinary Ren'Py dialogue.
    adb("shell", "input", "tap", width // 2, height * 7 // 8)
    tap(minigame_button("The constellation"))
    wait_for(lambda: "result=constellation pid=" + pid in markers(), 30)
    scene("journal_constellation", (33, 59, 74))
    adb("shell", "input", "tap", width // 2, height * 7 // 8)
    wait_for(lambda: "SDK_RUNNER_SCENE stage=first_light pid=" + pid in markers(), 30)
    adb("shell", "input", "tap", width // 2, height * 7 // 8)
    minigame_button("Play again")
    story_screenshot(output, "story-ending")
    ending_openings = markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid)
    adb("shell", "input", "keyevent", "4")
    tap(wait_for(lambda: find_control("Resume", output / "story-ending-menu.xml"), 30))
    minigame_button("Play again")
    assert markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid) == ending_openings
    tap(minigame_button("Play again"))
    wait_for(lambda: markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid) > ending_openings, 30)
    scene("opening", (24, 38, 53))
    adb("shell", "input", "keyevent", "4")
    tap(minigame_button("Quick load"))
    wait_for(lambda: "SDK_RUNNER_SAVE action=loaded kind=scene progress=0 pid=" + pid in markers(), 30)
    scene("aligned", (33, 59, 74))
    story_screenshot(output, "story-scene-loaded")
    adb("shell", "input", "keyevent", "4")
    tap(wait_for(lambda: find_control("Story history", output / "story-menu.xml"), 30))
    wait_for(lambda: find_control("You made it before sunrise", output / "story-restored-history.xml"), 30)
    wait_for(lambda: find_control("→ Constellation aligned", output / "story-restored-history.xml"), 30)
    adb("shell", "input", "keyevent", "4")
    tap(wait_for(lambda: find_control("Resume", output / "story-menu.xml"), 30))
    opening_count = markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid)

    adb("shell", "input", "keyevent", "4")
    tap(wait_for(lambda: find_control("Replay story", output / "story-menu.xml"), 30))
    tap(wait_for(lambda: next((node for node in controls(output / "story-replay.xml")
        if node.get("class") == "android.widget.Button"
        and (node.get("text", "") + node.get("content-desc", "")).strip() == "Replay"), None), 30))
    wait_for(lambda: markers().count("SDK_RUNNER_SCENE stage=opening pid=" + pid) > opening_count, 30)
    scene("opening", (24, 38, 53))
    adb("shell", "input", "tap", width // 2, height * 7 // 8)
    tap(minigame_button("Skip minigame"))
    scene("skipped", (48, 43, 69))
    assert "result=skipped pid=" + pid in markers()
    story_screenshot(output, "story-skipped")
    assert runner_pid() == pid, "Interlude, menu or replay started another process"
    (output / "story-experience.json").write_text(json.dumps({
        "pid": int(pid), "save_source_pid": int(save_source_pid), "initial_viewport": viewport,
        "background_source_pid": int(background_source_pid),
        "renpy_dialogue": True, "flet_minigame": "star_map", "results": ["aligned", "skipped"],
        "wrong_star_retry": True, "interlude_history": True, "scene_back_menu": True,
        "menu_resume": True, "background_resume": True, "replay_same_process": True,
        "flet_hidden_after_return": True,
        "minigame_save_load": True, "minigame_cold_load": True,
        "native_scene_save_load": True, "restored_interlude_history": True,
        "native_background_cold_recovery": True, "quick_save_kept_after_recovery": True,
        "unified_story_history": True, "flet_panel_result": "constellation",
        "explicit_ending": True,
        "shared_reading_settings": True, "reading_preferences_after_load": True,
        "reading_preferences_cold": True,
    }, indent=2) + "\n")
    print("Passed: native story, shared reading settings, minigame/panel results, warm/cold saves, background recovery, unified history and ending")
    adb("shell", "input", "keyevent", "4")
    tap(wait_for(lambda: find_control("Device diagnostics", output / "story-menu.xml"), 30))
    wait_for(lambda: find_control("Increment", output / "diagnostics.xml"), 30)


def tap(node):
    bounds = [int(value) for value in re.findall(r"\d+", node.get("bounds"))]
    adb("shell", "input", "tap", (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)


def controls(output):
    adb("shell", "uiautomator", "dump", "/sdcard/runner-ui.xml")
    xml = adb("shell", "cat", "/sdcard/runner-ui.xml")
    output.write_text(xml)
    return list(ET.fromstring(xml).iter("node"))


def increment_button(output):
    nodes = controls(output)
    for node in nodes:
        if node.get("resource-id") == "android:id/ok" and node.get("text") == "Got it":
            tap(node)
            return None
    return next((node for node in nodes if "Increment" in
                 (node.get("text", "") + node.get("content-desc", ""))), None)


def find_control(label, output, scroll_up=False, scroll_down=False, control_class=None, focused=False, minimum_height=0):
    nodes = controls(output)
    for node in nodes:
        matches = (node.get("class") == control_class if control_class else
                   label in (node.get("text", "") + node.get("content-desc", "")))
        if not matches or (focused and node.get("focused") != "true"):
            continue
        if minimum_height:
            bounds = list(map(int, re.findall(r"\d+", node.get("bounds", ""))))
            if len(bounds) != 4 or bounds[3] - bounds[1] < minimum_height:
                continue
        return node
    if scroll_up or scroll_down:
        scroll = next((node for node in nodes if node.get("class") == "android.widget.ScrollView"
                       and node.get("package") == "org.sdk.runner"), None)
        if scroll is not None:
            left, top, right, bottom = map(int, re.findall(r"\d+", scroll.get("bounds")))
            # Keep vertical scrolls outside Android's Back-gesture edge zones.
            x = left + (right - left) * 4 // 5
            upper, lower = top + (bottom - top) // 4, bottom - (bottom - top) // 4
            adb("shell", "input", "swipe", x, upper if scroll_up else lower,
                x, lower if scroll_up else upper, "400")
    return None


def json_markers(logs, marker):
    return [json.loads(line.split(marker, 1)[1])
            for line in logs.splitlines() if marker in line]


def check_file_selection(output, phase="initial"):
    """Select two fresh binary fixtures through DocumentsUI and read their cached bytes."""
    receipts = []
    expected_pid = runner_pid()
    for attempt in range(2):
        name = "sdk-runner-" + phase + "-selected-" + str(attempt + 1) + ".bin"
        fixture = output / name
        contents = (b"SDK runner native file selection\n" + os.urandom(32)
                    + bytes(range(256)) * (280 + attempt) + "café".encode("utf-8"))
        fixture.write_bytes(contents)
        adb("push", fixture, "/sdcard/Download/" + name)
        adb("shell", "am", "broadcast", "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
            "-d", "file:///sdcard/Download/" + name)
        before = markers()
        before_files = len(json_markers(before, "SDK_RUNNER_PICKER_FILE "))
        tap(wait_for(lambda: find_control("Open file picker", output / "picker-open.xml", scroll_up=True), 30))
        wait_for(lambda: "documentsui" in focused_window(), 30)

        def document_node(label, path):
            return next((node for node in controls(path)
                         if "documentsui" in node.get("package", "")
                         and node.get("text") == label), None)

        file_node = document_node(name, output / "picker-initial.xml")
        if file_node is None:
            roots = document_node("Downloads", output / "picker-roots.xml")
            if roots is None:
                def navigation():
                    return next((node for node in controls(output / "picker-navigation.xml")
                                 if "documentsui" in node.get("package", "")
                                 and node.get("content-desc", "").lower() in
                                 ("show roots", "open navigation drawer", "show sidebar")), None)
                tap(wait_for(navigation, 30))
                roots = wait_for(lambda: document_node("Downloads", output / "picker-roots.xml"), 30)
            tap(roots)
            file_node = wait_for(lambda: document_node(name, output / "picker-files.xml"), 30)
        tap(file_node)

        def selected():
            logs = markers()
            if logs.count("SDK_RUNNER_PICKER_ERROR") > before.count("SDK_RUNNER_PICKER_ERROR"):
                raise AssertionError("Native selected-file read failed; see logcat")
            return logs.count("SDK_RUNNER_PICKER_RETURNED count=1") > before.count(
                "SDK_RUNNER_PICKER_RETURNED count=1")

        wait_for(selected, 30)
        fresh = json_markers(markers(), "SDK_RUNNER_PICKER_FILE ")[before_files:]
        expected = {"name": name, "size": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}
        assert fresh == [expected], ("Selected file bytes differ from CI fixture", fresh, expected)
        assert runner_pid() == expected_pid, "File selection restarted the runner"
        wait_for(lambda: "org.sdk.runner" in focused_window(), 30)
        receipts.append(expected)
    receipt_path = output / "file-selections.json"
    earlier = json.loads(receipt_path.read_text()) if receipt_path.exists() else []
    receipt_path.write_text(json.dumps(earlier + receipts, indent=2))
    print("Passed: two native file selections returned exact binary bytes to the shared Python process")



def record_device_environment(output, expected_display=None):
    properties = dict(re.findall(r"\[([^\]]+)\]: \[([^\]]*)\]", adb("shell", "getprop")))
    sizes = re.findall(r"(?:Physical|Override) size: (\d+)x(\d+)", adb("shell", "wm", "size"))
    densities = re.findall(r"(?:Physical|Override) density: (\d+)", adb("shell", "wm", "density"))
    assert sizes and densities, "Missing Android display configuration"
    width, height = map(int, sizes[-1])
    density = int(densities[-1])
    assert width > 0 and height > 0 and density > 0, "Invalid Android display configuration"
    report = {
        "android_api": int(properties["ro.build.version.sdk"]),
        "native_abi": properties["ro.product.cpu.abi"],
        "emulator": properties.get("ro.kernel.qemu") == "1",
        "display_pixels": [width, height], "density_dpi": density,
        "logical_display_dp": [round(value * 160 / density, 3) for value in (width, height)],
        "egl_hardware": properties.get("ro.hardware.egl"),
        "vulkan_hardware": properties.get("ro.hardware.vulkan"),
        "host_cpus": os.cpu_count(),
    }
    (output / "device-environment.json").write_text(json.dumps(report, indent=2) + "\n")
    print("Android verification environment: " + json.dumps(report, sort_keys=True), flush=True)
    if expected_display is not None:
        assert [width, height, density] == list(expected_display), (
            "Android display differs from the selected emulator profile", report, expected_display)
    return report


def pixel_counts(frame, bounds, colors):
    """Count sampled RGB pixels inside one visible semantic control."""
    width, height, pixel_format = struct.unpack_from("<III", frame)
    header = len(frame) - width * height * 4
    assert pixel_format == 1 and header in (12, 16), "Expected an RGBA_8888 screenshot"
    left, top, right, bottom = bounds
    assert 0 <= left < right <= width and 0 <= top < bottom <= height, (
        "Visual control is outside the framebuffer", bounds, width, height)
    counts = dict.fromkeys(colors, 0)
    samples = 0
    for y in range(top, bottom, 3):
        for x in range(left, right, 3):
            offset = header + (y * width + x) * 4
            rgb = frame[offset:offset + 3]
            samples += 1
            for name, expected in colors.items():
                if all(abs(actual - target) <= 8 for actual, target in zip(rgb, expected)):
                    counts[name] += 1
    return {"bounds": bounds, "sampled_pixels": samples, "colors": counts}


def check_local_visuals(output):
    receipt_path = output / "local-visuals.json"
    earlier = json.loads(receipt_path.read_text()) if receipt_path.exists() else []
    index = len(earlier) + 1
    pid = int(runner_pid())
    results = {}
    density = json.loads((output / "device-environment.json").read_text())["density_dpi"]
    for name, label, height_dp, colors in (
            ("svg", "Local asset image", 48, {"blue": (21, 101, 192)}),
            ("chart", "Local bar chart", 100, {"pink": (233, 30, 99), "green": (76, 175, 80)})):
        node = wait_for(lambda: find_control(label, output / ("visual-" + name + ".xml"),
                                             scroll_down=True,
                                             minimum_height=int(height_dp * density / 160) - 1), 30)
        bounds = list(map(int, re.findall(r"\d+", node.get("bounds"))))
        frame = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
        result = pixel_counts(frame, bounds, colors)
        if name == "svg":
            assert result["colors"]["blue"] >= max(16, result["sampled_pixels"] // 4), (
                "Local SVG did not paint its expected blue body", result)
        else:
            assert all(count >= 8 for count in result["colors"].values()), (
                "Local chart did not paint both expected bars", result)
        adb("shell", "screencap", "-p", "/sdcard/runner-visual.png", timeout=15)
        adb("pull", "/sdcard/runner-visual.png", output / ("visual-" + str(index) + "-" + name + ".png"),
            timeout=15)
        results[name] = result
    assert int(runner_pid()) == pid, "Visual verification restarted the runner"
    earlier.append({"pid": pid, "checks": results})
    receipt_path.write_text(json.dumps(earlier, indent=2) + "\n")
    wait_for(lambda: find_control("Run checks", output / "visual-returned.xml", scroll_up=True), 30)
    print("Local visual verification: " + json.dumps({"pid": pid, "checks": results}, sort_keys=True), flush=True)
    print("Passed: local SVG and both chart bars paint inside their visible control bounds", flush=True)


def record_core_services(output, receipt, pid):
    services = receipt.get("services", {})
    assert receipt.get("pid") == pid, ("Stale native-service receipt", receipt, pid)
    assert set(services) == set(CORE_SERVICE_TYPES), ("Incomplete core-service receipt", receipt)
    ids = list(services.values())
    assert all(type(value) is int and value > 0 for value in ids) and len(set(ids)) == 7, (
        "Invalid native-service identities", receipt)
    path = output / "core-service-reuse.json"
    earlier = json.loads(path.read_text()) if path.exists() else []
    for previous in earlier:
        if previous["pid"] == pid:
            assert previous["services"] == services, (
                "Repeated capability checks created replacement core services", previous, receipt)
    path.write_text(json.dumps(earlier + [receipt], indent=2) + "\n")


def run_capability_checks(output):
    names = ["python_extensions_19", "clipboard", "preferences", "secure_storage",
             "storage_paths", "storage_persistence", "local_auth_query", "permission_query",
             "webview_local_asset", "audio_local_asset", "video_local_asset",
             "python_native_modules", "python_android_jni_providers", "python_android_jni_thread",
             "python_android_jni_page_thread", "python_android_jni_pubsub", "python_android_jni_asyncio_thread",
             "battery", "connectivity", "wakelock",
             "brightness", "accessibility", "haptic_channel", "url_launcher_query"]
    before = markers()
    before_storage = len(json_markers(before, "SDK_RUNNER_STORAGE_CHECK "))
    before_services = len(json_markers(before, "SDK_RUNNER_CORE_SERVICES "))
    tap(wait_for(lambda: find_control("Run checks", output / "capabilities.xml"), 30))

    def checked():
        logs = markers()
        if logs.count("SDK_RUNNER_CAPABILITY_ERROR") > before.count("SDK_RUNNER_CAPABILITY_ERROR"):
            raise AssertionError("A native capability check failed; see logcat")
        return logs.count("SDK_RUNNER_CAPABILITIES_PASSED") > before.count("SDK_RUNNER_CAPABILITIES_PASSED")

    wait_for(checked, 90)
    logs = markers()
    for name in names:
        marker = "SDK_RUNNER_CAPABILITY_OK name=" + name
        assert logs.count(marker) > before.count(marker), "Missing fresh check: " + name
    receipts = json_markers(logs, "SDK_RUNNER_STORAGE_CHECK ")[before_storage:]
    assert len(receipts) == 1, ("Missing unique fresh storage result", receipts)
    pid = int(runner_pid())
    assert receipts[0]["pid"] == pid, ("Stale storage result", receipts)
    core_receipts = json_markers(logs, "SDK_RUNNER_CORE_SERVICES ")[before_services:]
    assert len(core_receipts) == 1, ("Missing unique fresh core-service receipt", core_receipts)
    record_core_services(output, core_receipts[0], pid)
    check_local_visuals(output)
    return receipts[0]


def check_capabilities(output):
    tap(wait_for(lambda: find_control("Capabilities", output / "capabilities.xml"), 30))
    storage_receipt = run_capability_checks(output)

    focus_attempts = 0
    density = json.loads((output / "device-environment.json").read_text())["density_dpi"]
    input_height = int(56 * density / 160) - 1
    def focus_input():
        nonlocal focus_attempts
        field = find_control("Input probe", output / "input-focused.xml", scroll_down=True,
                             control_class="android.widget.EditText", minimum_height=input_height)
        if field is None:
            return None
        if field.get("focused") == "true":
            viewports = json_markers(markers(), "SDK_RUNNER_VIEWPORT ")
            if viewports and viewports[-1]["ime_overlap"] > 0:
                ime = adb("shell", "dumpsys", "input_method", timeout=15)
                (output / "input-method-open.txt").write_text(ime)
                if "mIsInputViewShown=true" in ime and "mInputShown=true" in ime:
                    return field
            return None
        # Reacquire geometry after layout/scroll changes. A dispatched tap does
        # not guarantee focus; require committed semantics before injecting text.
        if focus_attempts < 3:
            focus_attempts += 1
            print("Input focus tap " + str(focus_attempts) + ": bounds=" +
                  field.get("bounds", "") + " focus=" + field.get("focused", ""), flush=True)
            tap(field)
        return None
    field = wait_for(focus_input, 30)
    bounds = list(map(int, re.findall(r"\d+", field.get("bounds"))))
    viewports = json_markers(markers(), "SDK_RUNNER_VIEWPORT ")
    assert viewports, "Missing host keyboard viewport receipt"
    viewport = viewports[-1]
    assert viewport["ime_overlap"] > 0, ("Keyboard did not open during text-input check", viewport)
    assert viewport["flet_top"] + viewport["flet_height"] <= viewport["keyboard_top"], (
        "Embedded Flutter panel overlaps the keyboard", viewport)
    assert bounds[1] >= viewport["flet_top"] and bounds[3] <= viewport["keyboard_top"], (
        "Focused input is obscured by the keyboard", bounds, viewport)
    window = adb("shell", "dumpsys", "window", timeout=15)
    (output / "keyboard-window.txt").write_text(window)
    ime_heights = {int(value) for value in re.findall(
        r"mType=ime[^\n]*mInsetsHint=Insets\{[^}]*bottom=(\d+)", window) if int(value) > 0}
    assert len(ime_heights) == 1, ("Missing unique native IME surface height", ime_heights)
    ime_height = ime_heights.pop()
    assert viewport["ime_overlap"] == ime_height, (
        "Host panel layout differs from the visible keyboard surface", viewport, ime_height)
    (output / "keyboard-viewport.json").write_text(json.dumps(
        {"pid": int(runner_pid()), "input_bounds": bounds, "viewport": viewport,
         "native_ime_height": ime_height, "software_input_view_shown": True}, indent=2) + "\n")
    print("Keyboard viewport verification: " + json.dumps(viewport, sort_keys=True), flush=True)
    before_input = markers().count("SDK_RUNNER_TEXT_INPUT_PASSED")
    adb("shell", "input", "text", "runner_test")
    wait_for(lambda: markers().count("SDK_RUNNER_TEXT_INPUT_PASSED") > before_input, 30)
    adb("shell", "input", "keyevent", "4")  # Hide the keyboard.
    def keyboard_closed():
        viewports = json_markers(markers(), "SDK_RUNNER_VIEWPORT ")
        if not viewports or viewports[-1]["ime_overlap"] != 0:
            return None
        restored = viewports[-1]
        assert restored["flet_height"] == restored["height"] * 2 // 5, (
            "Normal panel split was not restored after text entry", restored)
        return restored
    restored = wait_for(keyboard_closed, 30)
    receipt_path = output / "keyboard-viewport.json"
    receipt = json.loads(receipt_path.read_text())
    receipt["restored"] = restored
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Passed: visible text input above the keyboard and normal panel restoration", flush=True)
    tap(wait_for(lambda: find_control("Open file picker", output / "picker.xml", scroll_up=True), 30))
    wait_for(lambda: any("documentsui" in node.get("package", "")
                         for node in controls(output / "picker.xml")), 30)
    def cancel_picker():
        if "SDK_RUNNER_PICKER_RETURNED count=0" in markers():
            return True
        # A visible picker tree can precede window focus. Back can also first
        # dismiss its search keyboard or drawer; keep cancellation in that app.
        focused = adb("shell", "dumpsys", "window")
        if any("mCurrentFocus=" in line and "documentsui" in line
               for line in focused.splitlines()):
            adb("shell", "input", "keyevent", "4")
        return False

    wait_for(cancel_picker, 30)
    check_file_selection(output)

    tap(wait_for(lambda: find_control("Share local file", output / "share.xml", scroll_down=True), 30))
    wait_for(lambda: "ChooserActivity" in adb("shell", "dumpsys", "activity", "activities"), 30)
    controls(output / "share.xml")
    adb("shell", "input", "keyevent", "4")
    wait_for(lambda: "SDK_RUNNER_SHARE_RETURNED status=" in markers(), 30)

    tap(wait_for(lambda: find_control("Request camera permission", output / "permission.xml", scroll_down=True), 30))

    def grant_permission():
        if "SDK_RUNNER_PERMISSION_RETURNED status=granted" in markers():
            return True
        nodes = controls(output / "permission.xml")
        allow = next((node for node in nodes if node.get("resource-id", "").endswith(
            "/permission_allow_foreground_only_button")), None)
        if allow is not None:
            tap(allow)
        return False

    wait_for(grant_permission, 30)

    adb("shell", "settings", "put", "system", "accelerometer_rotation", "0")
    try:
        adb("shell", "settings", "put", "system", "user_rotation", "1")

        def rotated():
            path = output / "rotated.xml"
            controls(path)
            return ET.fromstring(path.read_text()).get("rotation") == "1"

        wait_for(rotated, 30)
        adb("shell", "input", "keyevent", "3")
        adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
        wait_for(lambda: find_control("Run checks", output / "capabilities-resumed.xml", scroll_up=True), 30)
    finally:
        adb("shell", "settings", "put", "system", "user_rotation", "0")
    wait_for(lambda: find_control("Back", output / "capabilities-resumed.xml"), 30)
    adb("shell", "input", "keyevent", "4")  # Pop the Flet view through the host.
    wait_for(lambda: find_control("Count: 1", output / "returned.xml"), 30)
    wait_for(lambda: renpy_rendered(output / "renpy-back.json"), 30)
    tap(wait_for(lambda: find_control("Increment", output / "returned.xml"), 30))
    wait_for(lambda: "SDK_RUNNER_RENPY_COUNTER value=2" in markers(), 30)
    wait_for(lambda: find_control("Count: 2", output / "returned.xml"), 30)
    wait_for(lambda: renpy_rendered(output / "renpy-returned.json"), 30)
    print("Passed: extensions, native services, assets, media, text input, picker, rotation, back")
    print("Passed: RenPy canvas renders and shared state updates after returning from Flet")
    return storage_receipt


def require_storage_restored(previous_storage, restored):
    assert restored["state"] == "restored", ("Storage was seeded again after restart", restored)
    assert restored["sha256"] == previous_storage["sha256"], ("Durable challenge changed", previous_storage, restored)
    assert restored["source_pid"] == previous_storage["source_pid"], ("Storage receipt was rewritten", restored)
    assert restored["pid"] != previous_storage["pid"], ("Storage was not read by a new process", restored)


def check_shutdown_and_relaunch(output, previous_storage):
    before = runner_pid()
    assert previous_storage["pid"] == int(before), ("Wrong initial storage process", previous_storage, before)
    stopped = markers().count("SDK_RUNNER_FLET_STOPPED")
    adb("shell", "screencap", "-p", "/sdcard/shared-counter.png")
    adb("pull", "/sdcard/shared-counter.png", output / "shared-counter.png")
    tap(wait_for(lambda: find_control("Quit runner", output / "quit.xml"), 30))
    wait_for(lambda: markers().count("SDK_RUNNER_FLET_STOPPED") > stopped, 30)
    wait_for(lambda: not runner_pid(), 30)
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
        "-d", "sdk-runner:///capabilities?probe=cold")
    after = wait_for(runner_pid, 30)
    assert before != after, "Android did not start a fresh process"
    for marker in ("SDK_RUNNER_FLUTTER_ATTACHED", "SDK_RUNNER_RENPY_READY", "SDK_RUNNER_FLET_READY"):
        wait_for(lambda: marker + " pid=" + after in markers(), 90)
    wait_for(lambda: find_control("Run checks", output / "cold-link.xml"), 30)
    restored = run_capability_checks(output)
    require_storage_restored(previous_storage, restored)
    (output / "storage-persistence.json").write_text(json.dumps(
        {"before": previous_storage, "after": restored}, indent=2))
    print("Passed: app data, preferences and secure storage restored unchanged in a fresh Android process")
    adb("shell", "input", "keyevent", "4")
    wait_for(lambda: find_control("Count: 0", output / "relaunched.xml"), 30)
    tap(wait_for(lambda: find_control("Increment", output / "relaunched.xml"), 30))
    wait_for(lambda: "SDK_RUNNER_RENPY_COUNTER value=1 pid=" + after in markers(), 30)
    wait_for(lambda: find_control("Count: 1", output / "relaunched.xml"), 30)
    wait_for(lambda: renpy_rendered(output / "renpy-relaunched.json"), 30)
    print("Passed: RenPy-owned clean shutdown, Flet thread exit, and fresh Android relaunch")
    print("Passed: implicit cold deep link and fresh native services after plugin reattachment")
    return restored


def check_forced_restart(output, previous_storage):
    before = runner_pid()
    assert previous_storage["pid"] == int(before), ("Wrong storage process before force-stop", previous_storage)
    adb("shell", "am", "force-stop", "org.sdk.runner")
    wait_for(lambda: not runner_pid(), 30)
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
        "-d", "sdk-runner:///capabilities?probe=forced-cold")
    wait_for_startup()
    after = runner_pid()
    assert after != before, ("Force-stop did not produce a fresh process", before, after)
    wait_for(lambda: find_control("Run checks", output / "forced-link.xml"), 30)
    restored = run_capability_checks(output)
    require_storage_restored(previous_storage, restored)
    receipt_path = output / "storage-persistence.json"
    results = json.loads(receipt_path.read_text())
    results["after_force_stop"] = restored
    receipt_path.write_text(json.dumps(results, indent=2))
    check_file_selection(output, phase="restarted")
    adb("shell", "input", "keyevent", "4")
    wait_for(lambda: find_control("Count: 0", output / "forced-return.xml"), 30)
    tap(wait_for(lambda: find_control("Increment", output / "forced-return.xml"), 30))
    wait_for(lambda: "SDK_RUNNER_RENPY_COUNTER value=1 pid=" + after in markers(), 30)
    wait_for(lambda: find_control("Count: 1", output / "forced-return.xml"), 30)
    wait_for(lambda: renpy_rendered(output / "renpy-forced-restart.json"), 30)
    print("Passed: force-stop/cold startup restores durable storage, all native services, picker and both renderers")


def gesture_diagnostics(output, stage):
    state = adb("shell", "dumpsys", "activity", "service", "com.android.systemui/.SystemUIService")
    (output / ("systemui-" + stage + ".txt")).write_text(state)
    lines = state.splitlines()
    starts = [index for index, line in enumerate(lines) if "EdgeBackGestureHandler:" in line]
    for start in starts:
        print("SystemUI gesture state " + stage + ":\n" + "\n".join(lines[start:start + 60]), flush=True)
    window = adb("shell", "dumpsys", "window")
    (output / ("window-" + stage + ".txt")).write_text(window)
    print("Gesture window state " + stage + ":\n" + "\n".join(
        line.strip() for line in window.splitlines()
        if any(name in line for name in ("mCurrentFocus=", "mSystemGestureExclusion",
                                         "mRequestedVisibleTypes", "mForceConsumeSystemBars",
                                         "mLastSystemUiFlags", "mSystemUiVisibility"))), flush=True)


def check_deep_link_and_back_gesture(output, count=1):
    expected_count = "Count: " + str(count)
    frame = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
    width, height = struct.unpack_from("<II", frame)
    adb("shell", "input", "tap", width // 2, height * 3 // 10)  # Select SDL first.
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
        "-d", "sdk-runner:///capabilities?probe=warm")
    wait_for(lambda: find_control("Run checks", output / "deep-link.xml"), 30)
    linked_pid = runner_pid()
    reused = run_capability_checks(output)
    previous = json.loads((output / "storage-persistence.json").read_text())["after"]
    assert reused["state"] == "restored", ("Reopened view seeded storage again", reused)
    assert all(reused[key] == previous[key] for key in ("pid", "source_pid", "sha256")), (
        "Reopened view changed durable storage or process", previous, reused)
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
        "-d", "sdk-runner:///diagnostics?probe=root")
    wait_for(lambda: find_control(expected_count, output / "root-link.xml"), 30)
    assert runner_pid() == linked_pid, "Warm root link restarted Runner"
    wait_for(lambda: renpy_rendered(output / "renpy-root-link.json"), 30)
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
        "-d", "sdk-runner:///capabilities?probe=gesture")
    wait_for(lambda: find_control("Run checks", output / "deep-link.xml"), 30)
    # A real edge swipe exercises Android's started/progressed/committed
    # callbacks, unlike an injected legacy KEYCODE_BACK.
    assert adb("shell", "settings", "get", "secure", "navigation_mode").strip() == "2"
    wait_for(lambda: any("mCurrentFocus=" in line and "org.sdk.runner" in line and "RunnerActivity" in line
                         for line in adb("shell", "dumpsys", "window").splitlines()), 30)
    gesture_diagnostics(output, "before")
    before = markers()
    gestures = {name: before.count("SDK_RUNNER_BACK_GESTURE " + name)
                for name in ("started", "progressed", "committed")}
    frame = subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)
    width, height = struct.unpack_from("<II", frame)
    print("Gesture environment: navigation=" +
          adb("shell", "settings", "get", "secure", "navigation_mode").strip() +
          " setup=" + adb("shell", "settings", "get", "secure", "user_setup_complete").strip() +
          " provisioned=" + adb("shell", "settings", "get", "global", "device_provisioned").strip())
    # SDL's immersive window can consume the first side swipe to reveal bars.
    # Retry immediately, before its transient bars hide; never replace the swipe
    # with KEYCODE_BACK or accept a callback from an earlier navigation.
    for attempt in (1, 2):
        adb("shell", "input", "touchscreen", "swipe", 1, height * 4 // 5,
            width * 3 // 4, height * 4 // 5, "600")
        logs = markers()
        fresh = {name: logs.count("SDK_RUNNER_BACK_GESTURE " + name) - count
                 for name, count in gestures.items()}
        print("Predictive Back swipe " + str(attempt) + ": " + str(fresh))
        if fresh["started"] > 0:
            break
    gesture_diagnostics(output, "after")
    wait_for(lambda: all(logs.count("SDK_RUNNER_BACK_GESTURE " + name) > count
                         for name, count in gestures.items()) if (logs := markers()) else False, 30)
    wait_for(lambda: find_control(expected_count, output / "gesture-returned.xml"), 30)
    wait_for(lambda: renpy_rendered(output / "renpy-gesture.json"), 30)
    reentry_logs = markers()
    audio_ids = re.findall(r"I/flutter\s*\(\s*" + linked_pid + r"\): Audio\((\d+)\)\.init:", reentry_logs)
    core = json.loads((output / "core-service-reuse.json").read_text())[-1]
    assert core["pid"] == int(linked_pid), ("Wrong service-reuse process", core, linked_pid)
    core_initializations = {}
    for name, factory in CORE_SERVICE_TYPES.items():
        native_type = factory if factory.endswith("Service") else factory + "Service"
        ids = re.findall(r"I/flutter\s*\(\s*" + linked_pid + r"\): " + native_type
                         + r"\((\d+)\)\.init\b", reentry_logs)
        assert ids == [str(core["services"][name])], (
            "Navigation recreated a native core service", name, ids, core)
        core_initializations[name] = ids
    assert len(audio_ids) == 1, ("Navigation recreated the native audio player", linked_pid, audio_ids)
    (output / "capability-service-reuse.json").write_text(json.dumps(
        {"pid": int(linked_pid), "view_visits": 3, "capability_runs": 2,
         "audio_initializations": audio_ids, "core_initializations": core_initializations,
         "storage": reused}, indent=2))
    print("Passed: one audio player and one initialization of each core service across three view visits")
    print("Passed: Android intent deep link and predictive Back gesture with both renderers")


def check_keyboard_and_profile(output):
    tap(wait_for(lambda: find_control("Connected", output / "profile-ui.xml"), 30))
    before = markers()
    key_markers = ["SDK_RUNNER_UNHANDLED_F1 " + kind for kind in ("down", "up", "repeat")]
    counts = [before.count(marker) for marker in key_markers]
    adb("shell", "input", "keyevent", "131")
    wait_for(lambda: all(markers().count(marker) > count
                         for marker, count in zip(key_markers[:2], counts[:2])), 10)
    time.sleep(1)
    delta = [markers().count(marker) - count for marker, count in zip(key_markers, counts)]
    assert delta == [1, 1, 0], ("Unhandled hardware key was redispatched repeatedly", delta)
    print("Passed: unhandled Flutter F1 reaches the framework exactly once per down/up")

    started = markers().count("SDK_RUNNER_FRAME_PROFILE start ")
    adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity",
        "--es", "runner.profile", "start")
    wait_for(lambda: markers().count("SDK_RUNNER_FRAME_PROFILE start ") > started, 10)
    button = wait_for(lambda: find_control("Increment", output / "profile-ui.xml"), 30)
    pid = runner_pid()
    for _ in range(20):
        tap(button)
    wait_for(lambda: "SDK_RUNNER_RENPY_COUNTER value=21 pid=" + pid in markers(), 30)
    wait_for(lambda: find_control("Count: 21", output / "profile-ui.xml"), 30)
    wait_for(lambda: renpy_rendered(output / "renpy-profile.json"), 30)
    # Flutter batches its timing callbacks; allow the final sample to arrive.
    time.sleep(1)
    stopped = markers().count("SDK_RUNNER_FRAME_PROFILE stop ")
    adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity",
        "--es", "runner.profile", "stop")
    wait_for(lambda: markers().count("SDK_RUNNER_FRAME_PROFILE stop ") > stopped, 10)
    payload = re.findall(r"SDK_RUNNER_FRAME_PROFILE stop (\{[^\n]+\})", markers())[-1]
    report = json.loads(payload)
    assert report["recorded_frames"] > 0, report
    (output / "flutter-frame-profile.json").write_text(json.dumps(report, indent=2))
    (output / "profile-memory.txt").write_text(adb("shell", "dumpsys", "meminfo", "org.sdk.runner"))
    print("Passed: 20 additional counter events update both renderers in one process")
    print("Flutter debug frame measurements: " + json.dumps(report))


def collect_diagnostics(output):
    """Attempt every snapshot; retain earlier files if a read fails."""
    errors = {}
    for name, command in (
            ("devices.txt", ("devices", "-l")),
            ("window.txt", ("shell", "dumpsys", "window")),
            ("activity.txt", ("shell", "dumpsys", "activity", "activities")),
            ("input-method.txt", ("shell", "dumpsys", "input_method")),
            ("logcat.txt", ("logcat", "-d", "-v", "brief"))):
        try:
            content = adb(*command, timeout=15)
            (output / name).write_text(content)
        except (OSError, subprocess.SubprocessError) as error:
            errors[name] = str(error)
            print("Diagnostic unavailable: " + name + ": " + str(error), flush=True)
            continue
        if name == "window.txt":
            print("Final window state:\n" + "\n".join(
                line.strip() for line in content.splitlines()
                if any(label in line for label in ("mCurrentFocus=", "mImeInputTarget=", "mImeLayeringTarget=", "mImeControlTarget=",
                                                   "ime(", "ime}", "InputMethod", "mFrame=",
                                                   "Keyguard", "mAwake=",
                                                   "mShowingLockscreen", "mDreamingLockscreen"))))
        elif name == "input-method.txt":
            print("Final input-method state:\n" + content, flush=True)
        elif name == "logcat.txt":
            runner_pids = set(re.findall(
                r"SDK_RUNNER_(?:FLUTTER_ATTACHED|RENPY_READY|FLET_READY) pid=(\d+)", content))
            print("\n".join(line for line in content.splitlines()
                            if "SDK_RUNNER" in line or "AndroidRuntime" in line
                            or any(re.search(r"\(\s*" + pid + r"\)", line) for pid in runner_pids)))
    for sample in sorted(output.glob("renpy-*.json")):
        print("SDL framebuffer sample " + sample.name + ": " + sample.read_text())
    try:
        adb("shell", "screencap", "-p", "/sdcard/runner.png", timeout=15)
        adb("pull", "/sdcard/runner.png", output / "runner.png", timeout=15)
    except (OSError, subprocess.SubprocessError) as error:
        errors["runner.png"] = str(error)
        print("Diagnostic unavailable: runner.png: " + str(error), flush=True)
    (output / "diagnostics.json").write_text(json.dumps({"errors": errors}, indent=2) + "\n")
    if errors:
        raise RuntimeError("Incomplete Android diagnostics: " + ", ".join(errors))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--abi", choices=("universal", *SUPPORTED_ABIS), default="universal")
    parser.add_argument("--output", type=Path, default=Path(".android-build/device-check"))
    parser.add_argument("--expected-display", nargs=3, type=int, metavar=("WIDTH", "HEIGHT", "DPI"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    abis = SUPPORTED_ABIS if args.abi == "universal" else (args.abi,)
    apk_report = inspect_apk(args.apk, abis)
    extensions = apk_report["extensions"]
    (args.output / "apk-inspection.json").write_text(json.dumps(apk_report, indent=2) + "\n")
    print("Verified device APK: " + json.dumps(apk_report, sort_keys=True), flush=True)
    subprocess.run(["adb", "wait-for-device"], check=True, timeout=180)
    try:
        wait_for(lambda: adb("shell", "getprop", "sys.boot_completed").strip() == "1", 180)
        record_device_environment(args.output, args.expected_display)
        adb("shell", "input", "keyevent", "82")
        if adb("shell", "getprop", "ro.kernel.qemu").strip() == "1":
            # A default AVD has no setup wizard, but SystemUI still gates gestures
            # and transient bars on these completed-device-setup flags.
            adb("shell", "settings", "put", "global", "device_provisioned", "1")
            adb("shell", "settings", "put", "secure", "user_setup_complete", "1")
            # Host keyboard attachment must not turn the IME test into a
            # navigation-strip-only check on some CI workers.
            adb("shell", "settings", "put", "secure", "show_ime_with_hard_keyboard", "1")
            # First-use immersive help obscures the framebuffer after focus recovery.
            adb("shell", "settings", "put", "secure", "immersive_mode_confirmations", "confirmed")
        # Changing navigation overlays can recreate/background a running Activity.
        # Configure the emulator before installation and startup, not mid-gesture test.
        adb("shell", "cmd", "overlay", "enable-exclusive", "--category",
            "com.android.internal.systemui.navbar.gestural")
        wait_for(lambda: adb("shell", "settings", "get", "secure", "navigation_mode").strip() == "2", 30)
        adb("install", "-r", args.apk)
        adb("shell", "input", "keyevent", "224")  # Wake after SystemUI reconfiguration.
        adb("shell", "wm", "dismiss-keyguard")
        home = adb("shell", "cmd", "package", "resolve-activity", "--brief",
                   "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME").strip()
        assert "/" in home, ("No HOME Activity", home)
        home_package = home.splitlines()[-1].split("/")[0]
        adb("shell", "input", "keyevent", "3")
        print("Bootstrap HOME: " + home + " focus=" + focused_window(), flush=True)
        wait_for(lambda: home_package in focused_window(), 60)
        adb("logcat", "-c")
        adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
        logs = wait_for_startup()
        pids = [re.search(marker + r" pid=(\d+)", logs).group(1) for marker in
            ["SDK_RUNNER_FLUTTER_ATTACHED", "SDK_RUNNER_RENPY_READY", "SDK_RUNNER_FLET_READY"]]
        assert len(set(pids)) == 1, ("Runtimes did not use the same process", pids)
        if extensions:
            wait_for(lambda: "SDK_RUNNER_EXTENSIONS_READY count=19" in markers(), 30)
            wait_for(lambda: "SDK_RUNNER_SENSITIVE_CONTENT_READY supported=true" in markers(), 30)
        check_story(args.output)
        button = wait_for(lambda: increment_button(args.output / "ui.xml"), 30)
        tap(button)
        wait_for(lambda: "SDK_RUNNER_RENPY_COUNTER value=1" in markers(), 30)
        wait_for(lambda: renpy_rendered(args.output / "renpy-initial.json"), 30)
        adb("shell", "input", "keyevent", "3")
        adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
        resumed = args.output / "resumed.xml"
        wait_for(lambda: any("Count: 1" in (node.get("text", "") + node.get("content-desc", ""))
                             for node in controls(resumed)), 30)
        wait_for(lambda: renpy_rendered(args.output / "renpy-resumed.json"), 30)
        print("Passed: both renderers, one process, shared counter, background/resume")
        if extensions:
            storage_receipt = check_capabilities(args.output)
            (args.output / "initial-logcat.txt").write_text(markers())
            storage_receipt = check_shutdown_and_relaunch(args.output, storage_receipt)
            (args.output / "clean-relaunch-logcat.txt").write_text(markers())
            check_keyboard_and_profile(args.output)
            (args.output / "profile-logcat.txt").write_text(markers())
            check_deep_link_and_back_gesture(args.output, count=21)
            (args.output / "view-reentry-logcat.txt").write_text(markers())
            check_forced_restart(args.output, storage_receipt)
    except Exception:
        for pattern in ("input*.xml", "picker*.xml"):
            for path in sorted(args.output.glob(pattern)):
                print("UI diagnostic " + path.name + ": " + path.read_text())
        raise
    finally:
        primary_error = sys.exc_info()[1]
        try:
            collect_diagnostics(args.output)
        except Exception as error:
            if primary_error is None:
                raise
            print("Diagnostic collection also failed: " + str(error), flush=True)



if __name__ == "__main__":
    main()
