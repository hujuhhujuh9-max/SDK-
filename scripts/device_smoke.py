"""Check both renderers and shared Python state on a connected Android device."""

import argparse
import re
import subprocess
import time
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path


def adb(*args):
    return subprocess.check_output(["adb", *map(str, args)], text=True)


def wait_for(check, seconds=120):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        result = check()
        if result:
            return result
        time.sleep(1)
    raise RuntimeError("Android smoke check timed out")


def markers():
    return adb("logcat", "-d", "-v", "brief")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--output", type=Path, default=Path(".android-build/device-check"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(args.apk) as apk:
        names = apk.namelist()
        for abi in ["arm64-v8a", "armeabi-v7a", "x86_64"]:
            assert f"lib/{abi}/librenpython.so" in names, abi
            assert f"lib/{abi}/libflutter.so" in names, abi
        assert not any("dart_bridge" in name or "serious_python" in name for name in names)
    subprocess.run(["adb", "wait-for-device"], check=True, timeout=180)
    wait_for(lambda: adb("shell", "getprop", "sys.boot_completed").strip() == "1", 180)
    adb("shell", "input", "keyevent", "82")
    adb("install", "-r", args.apk)
    adb("logcat", "-c")
    adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
    try:
        logs = wait_for(lambda: (text if all(marker in text for marker in
            ["SDK_RUNNER_FLUTTER_ATTACHED", "SDK_RUNNER_RENPY_READY", "SDK_RUNNER_FLET_READY"])
            else None) if (text := markers()) else None)
        pids = [re.search(marker + r" pid=(\d+)", logs).group(1) for marker in
            ["SDK_RUNNER_FLUTTER_ATTACHED", "SDK_RUNNER_RENPY_READY", "SDK_RUNNER_FLET_READY"]]
        assert len(set(pids)) == 1, ("Runtimes did not use the same process", pids)
        adb("shell", "uiautomator", "dump", "/sdcard/runner-ui.xml")
        xml = adb("shell", "cat", "/sdcard/runner-ui.xml")
        (args.output / "ui.xml").write_text(xml)
        nodes = ET.fromstring(xml).iter("node")
        button = next(node for node in nodes if "Increment" in
            (node.get("text", "") + node.get("content-desc", "")))
        bounds = [int(value) for value in re.findall(r"\d+", button.get("bounds"))]
        adb("shell", "input", "tap", (bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
        wait_for(lambda: "SDK_RUNNER_RENPY_COUNTER value=1" in markers(), 30)
        adb("shell", "input", "keyevent", "3")
        adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
        adb("shell", "uiautomator", "dump", "/sdcard/runner-resumed.xml")
        resumed = adb("shell", "cat", "/sdcard/runner-resumed.xml")
        assert "Count: 1" in resumed, "Flet state did not survive background/resume"
        adb("shell", "screencap", "-p", "/sdcard/runner.png")
        adb("pull", "/sdcard/runner.png", args.output / "runner.png")
        print("Passed: both renderers, one process, shared counter, background/resume")
    finally:
        (args.output / "logcat.txt").write_text(markers())


if __name__ == "__main__":
    main()
