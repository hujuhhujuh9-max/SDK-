"""Check both renderers and shared Python state on a connected Android device."""

import argparse
import hashlib
import json
import re
import struct
import subprocess
import tarfile
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def check_packaged_components(apk):
    inventory = json.loads(apk.read("assets/runner-capabilities.json"))
    expected = inventory["python_files"]
    assert expected, "Missing upstream package inventory"
    remaining = set(expected)
    with apk.open("assets/private.mp3") as stream, tarfile.open(fileobj=stream, mode="r|gz") as private:
        for member in private:
            if member.name in expected:
                digest = hashlib.file_digest(private.extractfile(member), "sha256").hexdigest()
                assert digest == expected[member.name], "Changed component file: " + member.name
                remaining.remove(member.name)
    assert not remaining, "Missing component files: " + ", ".join(sorted(remaining))
    for name, checksum in inventory.get("android_assets", {}).items():
        assert hashlib.sha256(apk.read(name)).hexdigest() == checksum, "Changed Android asset: " + name
    print("Passed: all " + str(len(expected)) + " upstream Python package/resource files retained in APK")
    print("Passed: all " + str(len(inventory.get("android_assets", {}))) + " RenPy common assets retained in APK")


def adb(*args):
    return subprocess.check_output(["adb", *map(str, args)], text=True)


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
                            capture_output=True, text=True)
    return result.stdout.strip()


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


def renpy_rendered(output):
    # Android screencap emits a raw RGBA framebuffer after its header. Probe
    # the fixed sample's dark-blue SDL canvas, above the Flutter panel.
    frame = subprocess.check_output(["adb", "exec-out", "screencap"])
    width, height, pixel_format = struct.unpack_from("<III", frame)
    header = len(frame) - width * height * 4
    assert pixel_format == 1 and header in (12, 16), "Expected an RGBA_8888 screenshot"
    y = height * 3 // 10
    samples = []
    for n in (1, 2, 3, 4):
        pixel = header + (y * width + width * n // 5) * 4
        samples.append(list(frame[pixel:pixel + 3]))
    output.write_text(json.dumps({"width": width, "height": height, "samples": samples}))
    return any(all(abs(actual - expected) <= 8
                   for actual, expected in zip(sample, (27, 40, 56)))
               for sample in samples)


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


def find_control(label, output, scroll_up=False, scroll_down=False, control_class=None):
    nodes = controls(output)
    found = next((node for node in nodes if
                  (node.get("class") == control_class if control_class else
                   label in (node.get("text", "") + node.get("content-desc", "")))), None)
    if found is not None:
        return found
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


def run_capability_checks(output):
    names = ["python_extensions_19", "clipboard", "preferences", "secure_storage",
             "storage_paths", "local_auth_query", "permission_query",
             "webview_local_asset", "audio_local_asset", "video_local_asset",
             "python_native_modules", "python_android_jni_providers", "python_android_jni_thread",
             "python_android_jni_page_thread", "python_android_jni_pubsub", "python_android_jni_asyncio_thread",
             "battery", "connectivity", "wakelock",
             "brightness", "accessibility", "haptic_channel", "url_launcher_query"]
    before = markers()
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


def check_capabilities(output):
    tap(wait_for(lambda: find_control("Capabilities", output / "capabilities.xml"), 30))
    run_capability_checks(output)

    field = wait_for(lambda: find_control("Input probe", output / "input.xml", scroll_down=True,
                                         control_class="android.widget.EditText"), 30)
    tap(field)
    adb("shell", "input", "text", "runner_test")
    wait_for(lambda: "SDK_RUNNER_TEXT_INPUT_PASSED" in markers(), 30)
    adb("shell", "input", "keyevent", "4")  # Hide the keyboard.
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


def check_shutdown_and_relaunch(output):
    def pid():
        result = subprocess.run(["adb", "shell", "pidof", "org.sdk.runner"],
                                capture_output=True, text=True)
        return result.stdout.strip()

    before = pid()
    stopped = markers().count("SDK_RUNNER_FLET_STOPPED")
    adb("shell", "screencap", "-p", "/sdcard/shared-counter.png")
    adb("pull", "/sdcard/shared-counter.png", output / "shared-counter.png")
    tap(wait_for(lambda: find_control("Quit runner", output / "quit.xml"), 30))
    wait_for(lambda: markers().count("SDK_RUNNER_FLET_STOPPED") > stopped, 30)
    wait_for(lambda: not pid(), 30)
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
        "-d", "sdk-runner:///capabilities?probe=cold")
    after = wait_for(pid, 30)
    assert before != after, "Android did not start a fresh process"
    for marker in ("SDK_RUNNER_FLUTTER_ATTACHED", "SDK_RUNNER_RENPY_READY", "SDK_RUNNER_FLET_READY"):
        wait_for(lambda: marker + " pid=" + after in markers(), 90)
    wait_for(lambda: find_control("Run checks", output / "cold-link.xml"), 30)
    run_capability_checks(output)
    adb("shell", "input", "keyevent", "4")
    wait_for(lambda: find_control("Count: 0", output / "relaunched.xml"), 30)
    tap(wait_for(lambda: find_control("Increment", output / "relaunched.xml"), 30))
    wait_for(lambda: "SDK_RUNNER_RENPY_COUNTER value=1 pid=" + after in markers(), 30)
    wait_for(lambda: find_control("Count: 1", output / "relaunched.xml"), 30)
    wait_for(lambda: renpy_rendered(output / "renpy-relaunched.json"), 30)
    print("Passed: RenPy-owned clean shutdown, Flet thread exit, and fresh Android relaunch")
    print("Passed: implicit cold deep link and fresh native services after plugin reattachment")


def check_deep_link_and_back_gesture(output):
    frame = subprocess.check_output(["adb", "exec-out", "screencap"])
    width, height = struct.unpack_from("<II", frame)
    adb("shell", "input", "tap", width // 2, height * 3 // 10)  # Select SDL first.
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
        "-d", "sdk-runner:///capabilities?probe=warm")
    wait_for(lambda: find_control("Run checks", output / "deep-link.xml"), 30)
    linked_pid = runner_pid()
    adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
        "-d", "sdk-runner:///?probe=root")
    wait_for(lambda: find_control("Count: 1", output / "root-link.xml"), 30)
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
    before = markers()
    gestures = {name: before.count("SDK_RUNNER_BACK_GESTURE " + name)
                for name in ("started", "progressed", "committed")}
    frame = subprocess.check_output(["adb", "exec-out", "screencap"])
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
    wait_for(lambda: all(logs.count("SDK_RUNNER_BACK_GESTURE " + name) > count
                         for name, count in gestures.items()) if (logs := markers()) else False, 30)
    wait_for(lambda: find_control("Count: 1", output / "gesture-returned.xml"), 30)
    wait_for(lambda: renpy_rendered(output / "renpy-gesture.json"), 30)
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".android-build/device-check"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.apk) as apk:
        names = apk.namelist()
        extensions = (json.loads(apk.read("assets/runner-capabilities.json"))["extensions"]
                      if "assets/runner-capabilities.json" in names else [])
        if extensions:
            assert len(extensions) == len(set(extensions)) == 19, extensions
            check_packaged_components(apk)
        for abi in ["arm64-v8a", "armeabi-v7a", "x86_64"]:
            assert f"lib/{abi}/librenpython.so" in names, abi
            assert f"lib/{abi}/libflutter.so" in names, abi
        assert not any("dart_bridge" in name or "serious_python" in name for name in names)
    subprocess.run(["adb", "wait-for-device"], check=True, timeout=180)
    try:
        wait_for(lambda: adb("shell", "getprop", "sys.boot_completed").strip() == "1", 180)
        adb("shell", "input", "keyevent", "82")
        if adb("shell", "getprop", "ro.kernel.qemu").strip() == "1":
            # A default AVD has no setup wizard, but SystemUI still gates gestures
            # and transient bars on these completed-device-setup flags.
            adb("shell", "settings", "put", "global", "device_provisioned", "1")
            adb("shell", "settings", "put", "secure", "user_setup_complete", "1")
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
            check_capabilities(args.output)
            check_shutdown_and_relaunch(args.output)
            check_deep_link_and_back_gesture(args.output)
            check_keyboard_and_profile(args.output)
    finally:
        window = adb("shell", "dumpsys", "window")
        print("Final window state:\n" + "\n".join(line.strip() for line in window.splitlines()
              if any(label in line for label in ("mCurrentFocus=", "Keyguard", "mAwake=",
                                                  "mShowingLockscreen", "mDreamingLockscreen"))))
        for sample in sorted(args.output.glob("renpy-*.json")):
            print("SDL framebuffer sample " + sample.name + ": " + sample.read_text())
        (args.output / "window.txt").write_text(window)
        (args.output / "activity.txt").write_text(adb("shell", "dumpsys", "activity", "activities"))
        logs = markers()
        (args.output / "logcat.txt").write_text(logs)
        runner_pids = set(re.findall(
            r"SDK_RUNNER_(?:FLUTTER_ATTACHED|RENPY_READY|FLET_READY) pid=(\d+)", logs))
        print("\n".join(line for line in logs.splitlines()
                        if "SDK_RUNNER" in line or "AndroidRuntime" in line
                        or any(re.search(r"\(\s*" + pid + r"\)", line) for pid in runner_pids)))
        adb("shell", "screencap", "-p", "/sdcard/runner.png")
        adb("pull", "/sdcard/runner.png", args.output / "runner.png")


if __name__ == "__main__":
    main()
