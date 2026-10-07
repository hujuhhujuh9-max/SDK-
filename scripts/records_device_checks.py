"""Verify the optional record recipe through Android UI and native storage."""

import json
import re


def check_records(output, device):
    adb, wait, tap = device.adb, device.wait_for, device.tap
    checks = []

    def control(label, *, up=False, down=False, control_class=None):
        def matching():
            if control_class is not None:
                return next((node for node in device.controls(output / "records-ui.xml")
                             if node.get("class") == control_class
                             and label in (node.get("text", "") + node.get("content-desc", ""))), None)
            node = device.find_control(label, output / "records-ui.xml",
                                       scroll_up=up, scroll_down=down)
            return node
        return wait(matching, 30)

    def link(route):
        adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
            "-d", "sdk-runner://" + route)

    def records(query):
        link("/records?probe=" + query)
        control("Application records", up=True)
        control("Records loaded")

    def title(value, previous=""):
        field = wait(lambda: device.find_control("", output / "records-input.xml",
                         scroll_up=True, control_class="android.widget.EditText"), 30)
        tap(field)
        if previous:
            adb("shell", "input", "keyevent", "123")  # End of the existing title.
            adb("shell", "input", "keyevent", *(["67"] * len(previous)))
        adb("shell", "input", "text", value)
        adb("shell", "input", "keyevent", "4")  # Hide the IME before pressing a button.

    def expect_record(value):
        control("Title: " + value, down=True)

    before = device.runner_pid()
    first = "SDKRecord" + before
    edited = first + "Updated"
    records("warm")
    assert device.runner_pid() == before, "Warm app link restarted the runner"
    tap(control("Add record"))
    control("Title is required")
    title(first)
    tap(control("Add record"))
    control("Record saved")
    expect_record(first)
    checks.append("required input and native record creation")

    # Bookmark the story before editing application data.
    link("/menu")
    saved = device.markers().count("SDK_RUNNER_SAVE action=saved ")
    tap(control("Quick save"))
    wait(lambda: device.markers().count("SDK_RUNNER_SAVE action=saved ") > saved, 30)
    control("Saved. You can return here")
    records("edit")
    expect_record(first)
    tap(control("Edit", down=True))
    title(edited, first)
    tap(control("Save changes"))
    control("Record saved")
    expect_record(edited)
    link("/menu")
    loaded = device.markers().count("SDK_RUNNER_SAVE action=loaded ")
    tap(control("Quick load"))
    wait(lambda: device.markers().count("SDK_RUNNER_SAVE action=loaded ") > loaded, 30)
    records("after-story-load")
    expect_record(edited)
    checks.append("loading an older native story keeps newer application data")

    openings = device.markers().count("SDK_RUNNER_SCENE stage=opening pid=" + before)
    link("/restart")
    tap(control("Replay", up=True, control_class="android.widget.Button"))
    wait(lambda: device.markers().count("SDK_RUNNER_SCENE stage=opening pid=" + before)
         > openings, 30)
    records("after-replay")
    expect_record(edited)
    checks.append("story replay keeps application data")

    for query in ("reentry-one", "reentry-two"):
        adb("shell", "input", "keyevent", "4")
        control("Connected")
        records(query)
        expect_record(edited)
    assert device.runner_pid() == before
    checks.append("query links, Back and repeated warm reentry")

    adb("shell", "input", "keyevent", "3")
    adb("shell", "am", "start", "-W", "-n", "org.sdk.runner/.RunnerActivity")
    control("Application records", up=True)
    expect_record(edited)
    assert device.runner_pid() == before, "Background/resume restarted the record page"
    checks.append("background/resume keeps the app page")

    backgrounds = device.markers().count("Entered background. --------------------------------------------")
    adb("shell", "input", "keyevent", "3")
    wait(lambda: device.markers().count("Entered background. --------------------------------------------") > backgrounds, 30)
    adb("shell", "am", "force-stop", "org.sdk.runner")
    wait(lambda: not device.runner_pid(), 30)
    records("cold")
    device.wait_for_startup()
    after = device.runner_pid()
    assert after != before, "Cold record check reused the old process"
    wait(lambda: re.search(r"SDK_RUNNER_SAVE action=loaded .*pid=" + re.escape(after)
                           + r"\b", device.markers()), 30)
    expect_record(edited)
    checks.append("fresh-process recovery preserves the explicit app link and stored record")
    tap(control("Delete", down=True))
    control("Record deleted")
    control("No records yet")
    tap(control("Back", up=True))
    control("Connected")
    checks.append("native deletion and return to diagnostics")

    receipt = {"scope": "actual Android UI, SharedPreferences and native story saves",
               "source_pid": before, "restored_pid": after, "checks": checks}
    (output / "records-persistence.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print("Passed: optional application records: " + json.dumps(receipt), flush=True)
