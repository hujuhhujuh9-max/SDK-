"""Exercise app-control recipes through actual Android input and painted output."""

import json
import re
import shlex
import subprocess
import time
import xml.etree.ElementTree as ET

from scripts.device_smoke import framebuffer_shape, pixel_counts

EDITED_ROWS = [{"name": "Beacon7", "count": 7}, {"name": "Harbor2", "count": 2}]
BLUE, GREEN = (21, 101, 192), (76, 175, 80)
REQUIRED_CHECKS = (
    "keyboard_json_apply", "invalid_json_keeps_table", "table_sort", "table_select",
    "color_change_and_preview", "loading_pending_and_complete", "loading_cancel_and_retry",
    "detached_load_keeps_new_page",
)


def node_text(node):
    return " ".join(value for child in node.iter("node")
                    for value in (child.get("text", ""), child.get("content-desc", "")) if value)


def bounds(node):
    value = node.get("bounds", "")
    if not re.fullmatch(r"\[\d+,\d+\]\[\d+,\d+\]", value):
        raise RuntimeError("Missing Android control bounds: " + value)
    result = list(map(int, re.findall(r"\d+", value)))
    if result[0] >= result[2] or result[1] >= result[3]:
        raise RuntimeError("Android control is not visible: " + value)
    return result


def semantic(nodes, identifier, expected=None):
    matches = [node for node in nodes if node.get("resource-id") in
               (identifier, "org.sdk.runner:id/" + identifier)]
    if len(matches) > 1:
        raise RuntimeError("Ambiguous Android recipe selector: " + identifier)
    if not matches:
        return None
    node = matches[0]
    if expected is not None and expected not in node_text(node):
        return None
    bounds(node)
    return node


def label(nodes, value):
    matches = [node for node in nodes if value in
               (node.get("text", "").strip(), node.get("content-desc", "").strip())]
    return next((node for node in matches if node.get("class") == "android.widget.Button"),
                next(iter(matches), None))


def green_swatch(frame, picker_bounds):
    """Find a painted swatch inside the picker, never an unrelated green widget."""
    report = pixel_counts(frame, picker_bounds, {"green": GREEN})
    if report["colors"]["green"] < 16:
        raise RuntimeError("Green palette swatch did not paint inside the picker")
    width, _, header = framebuffer_shape(frame)
    left, top, right, bottom = picker_bounds
    points = []
    for y in range(top, bottom, 3):
        for x in range(left, right, 3):
            offset = header + (y * width + x) * 4
            if all(abs(a - b) <= 8 for a, b in zip(frame[offset:offset + 3], GREEN)):
                points.append((x, y))
    return (sum(x for x, _ in points) // len(points),
            sum(y for _, y in points) // len(points)), report


def apk_identity(output, startup_template):
    report = json.loads((output / "apk-inspection.json").read_text())
    if (startup_template not in ("story", "app")
            or report.get("startup_template") != startup_template
            or not re.fullmatch(r"[0-9a-f]{40}", str(report.get("source_sha", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(report.get("sha256", "")))
            or not report.get("abis")):
        raise RuntimeError("App-control checks require a matching inspected APK receipt")
    return {name: report[name] for name in ("source_sha", "sha256", "abis", "startup_template")}


def validate_recipe_receipt(receipt, inspection):
    """Reject incomplete device evidence or evidence from another APK/mode."""
    if not isinstance(receipt, dict) or receipt.get("success") is not True \
            or type(receipt.get("skips")) is not int or receipt["skips"] != 0 \
            or receipt.get("deferred") or receipt.get("skipped"):
        raise RuntimeError("App-control receipt must succeed without skips")
    for name in ("source_sha", "sha256", "abis", "startup_template"):
        if receipt.get(name) != inspection.get(name):
            raise RuntimeError("App-control receipt does not match the inspected APK: " + name)
    if (inspection.get("startup_template") not in ("story", "app")
            or not re.fullmatch(r"[0-9a-f]{40}", str(inspection.get("source_sha", "")))
            or not re.fullmatch(r"[0-9a-f]{64}", str(inspection.get("sha256", "")))
            or not isinstance(inspection.get("abis"), list) or not inspection["abis"]
            or not re.fullmatch(r"[1-9][0-9]*", str(receipt.get("source_pid", "")))):
        raise RuntimeError("App-control receipt has invalid APK or process identity")
    checks = receipt.get("checks")
    fields = {
        "keyboard_json_apply": {"rows", "native_text"},
        "invalid_json_keeps_table": {"order", "error"},
        "table_sort": {"column", "order"},
        "table_select": {"selected"},
        "color_change_and_preview": {"color", "palette", "preview"},
        "loading_pending_and_complete": {"rows", "spinner_pixels"},
        "loading_cancel_and_retry": {"cancelled_result_retained", "retry_rows"},
        "detached_load_keeps_new_page": {"result"},
    }
    if not isinstance(checks, dict) or set(checks) != set(REQUIRED_CHECKS):
        raise RuntimeError("Incomplete Android app-control acceptance")
    for name, keys in fields.items():
        if not isinstance(checks[name], dict) or set(checks[name]) != keys:
            raise RuntimeError("Missing or deferred app-control operation evidence: " + name)
    try:
        edited = json.loads(checks["keyboard_json_apply"]["native_text"])
    except (TypeError, ValueError) as error:
        raise RuntimeError("Native keyboard JSON evidence is invalid") from error
    if (edited != EDITED_ROWS or checks["keyboard_json_apply"]["rows"] != EDITED_ROWS
            or checks["invalid_json_keeps_table"]["order"] != ["Beacon7", "Harbor2"]
            or "count must be an integer" not in str(checks["invalid_json_keeps_table"]["error"])
            or checks["table_sort"] != {"column": "Count", "order": ["Harbor2", "Beacon7"]}
            or checks["table_select"]["selected"] != "Beacon7"
            or checks["color_change_and_preview"]["color"] != "#4caf50"
            or type(checks["loading_pending_and_complete"]["rows"]) is not int
            or checks["loading_pending_and_complete"]["rows"] != 3
            or checks["loading_cancel_and_retry"] != {"cancelled_result_retained": True,
                                                       "retry_rows": 3}
            or checks["loading_cancel_and_retry"]["cancelled_result_retained"] is not True
            or checks["detached_load_keeps_new_page"]["result"] != "Ready to load sample."):
        raise RuntimeError("App-control operation evidence has unexpected results")
    for report, color, minimum, fraction in (
            (checks["color_change_and_preview"]["palette"], "green", 16, 0),
            (checks["color_change_and_preview"]["preview"], "green", 16, 0.5),
            (checks["loading_pending_and_complete"]["spinner_pixels"], "blue", 8, 0)):
        if (not isinstance(report, dict) or set(report) != {"bounds", "sampled_pixels", "colors"}
                or not isinstance(report["bounds"], list) or len(report["bounds"]) != 4
                or any(type(value) is not int or value < 0 for value in report["bounds"])
                or report["bounds"][0] >= report["bounds"][2]
                or report["bounds"][1] >= report["bounds"][3]
                or type(report["sampled_pixels"]) is not int or report["sampled_pixels"] < minimum
                or not isinstance(report["colors"], dict) or set(report["colors"]) != {color}
                or type(report["colors"][color]) is not int
                or not max(minimum, report["sampled_pixels"] * fraction)
                <= report["colors"][color] <= report["sampled_pixels"]):
            raise RuntimeError("App-control painted-output evidence is incomplete")
    return receipt


class AndroidRecipes:
    def __init__(self, adb, output):
        self.adb, self.output = adb, output

    def nodes(self):
        remote = "/sdcard/runner-recipes-ui.xml"
        report = self.adb("shell", "uiautomator", "dump", remote)
        if "dumped to:" not in report:
            return []  # A failed dump may leave an old file; never reuse it.
        xml = self.adb("shell", "cat", remote)
        (self.output / "app-recipes-ui.xml").write_text(xml)
        return list(ET.fromstring(xml).iter("node"))

    def wait(self, check, description, seconds=30):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            result = check()
            if isinstance(result, ET.Element) or result:
                return result
            time.sleep(0.2)
        raise RuntimeError("Android app-control check timed out: " + description)

    def result(self, identifier, expected=None):
        return self.wait(lambda: semantic(self.nodes(), identifier, expected),
                         identifier + (": " + expected if expected else ""))

    def pending(self):
        def snapshot():
            nodes = self.nodes()
            status = semantic(nodes, "recipe-loading-result", "Loading sample")
            spinner = semantic(nodes, "recipe-loading")
            cancel = label(nodes, "Cancel load")
            return (spinner, cancel) if status is not None and spinner is not None \
                and cancel is not None else None
        return self.wait(snapshot, "visible loading state and Cancel control")

    def button(self, value):
        return self.wait(lambda: label(self.nodes(), value), value)

    def tap(self, node):
        left, top, right, bottom = bounds(node)
        self.adb("shell", "input", "tap", (left + right) // 2, (top + bottom) // 2)

    def section(self, value):
        self.tap(self.button(value))

    def editor_field(self):
        editor = semantic(self.nodes(), "recipe-editor")
        if editor is None:
            return None
        fields = [node for node in editor.iter("node")
                  if node.get("class") == "android.widget.EditText"]
        if len(fields) > 1:
            raise RuntimeError("App-control editor has multiple native text fields")
        return next(iter(fields), None)

    def edit(self, source):
        field = self.wait(self.editor_field, "native CodeEditor text field")
        self.tap(field)
        self.wait(lambda: (current := self.editor_field()) is not None
                  and current.get("focused") == "true", "CodeEditor keyboard focus")
        # Android 36 sends a real Ctrl+A chord to Flutter's editable text. ADB
        # shell joins arguments, so JSON must keep its quotes through that shell.
        self.adb("shell", "input", "keycombination", "113", "29")
        self.adb("shell", "input", "keyevent", "67")
        self.wait(lambda: (current := self.editor_field()) is not None
                  and current.get("text", "") == "", "cleared CodeEditor")
        self.adb("shell", "input", "text", shlex.quote(source))
        self.wait(lambda: (current := self.editor_field()) is not None
                  and current.get("text") == source, "exact keyboard JSON input")
        self.adb("shell", "input", "keyevent", "4")  # Hide the keyboard.

    def link(self, route):
        self.adb("shell", "am", "start", "-W", "-a", "android.intent.action.VIEW",
                 "-d", "sdk-runner://" + route)

    def frame(self):
        return subprocess.check_output(["adb", "exec-out", "screencap"], timeout=30)

    def screenshot(self, name):
        remote = "/sdcard/runner-recipes.png"
        self.adb("shell", "screencap", "-p", remote)
        self.adb("pull", remote, self.output / ("app-recipes-" + name + ".png"))

    def pid(self):
        candidates = self.adb("shell", "pidof", "org.sdk.runner").split()
        if len(candidates) > 1:
            rows = self.adb("shell", "ps", "-A", "-o", "PID,PPID").splitlines()
            parents = dict(row.split() for row in rows if len(row.split()) == 2
                           and all(value.isdigit() for value in row.split()))
            candidates = [pid for pid in candidates if pid in parents
                          and parents[pid] not in candidates]
        if len(candidates) != 1 or not candidates[0].isdigit():
            raise RuntimeError("App-control checks require one active runner process")
        return candidates[0]


def check_app_recipes(adb, output, startup_template="story"):
    receipt_path = output / "app-recipes.json"
    receipt_path.unlink(missing_ok=True)
    identity = apk_identity(output, startup_template)
    ui = AndroidRecipes(adb, output)
    pid = ui.pid()
    route = "/app/recipes" if startup_template == "app" else "/recipes"
    checks = {}
    ui.link(route + "?probe=controls")
    ui.result("recipe-editor")
    source = json.dumps(EDITED_ROWS, separators=(",", ":"))
    ui.edit(source)
    ui.tap(ui.button("Apply JSON"))
    ui.result("recipe-editor-result", "Applied 2 rows")
    checks["keyboard_json_apply"] = {"rows": EDITED_ROWS, "native_text": source}
    ui.edit('[{"name":"Beacon7","count":true}]')
    ui.tap(ui.button("Apply JSON"))
    error = ui.result("recipe-editor-result", "count must be an integer")
    validation_error = node_text(error)
    ui.section("Table")
    ui.result("recipe-table-result", "Order: Beacon7, Harbor2")
    checks["invalid_json_keeps_table"] = {"order": ["Beacon7", "Harbor2"],
                                          "error": validation_error}
    table = ui.result("recipe-table")
    count = label(list(table.iter("node")), "Count")
    if count is None:
        raise RuntimeError("Native table Count sort heading is missing")
    ui.tap(count)
    ui.result("recipe-table-result", "Order: Harbor2, Beacon7")
    ui.screenshot("table-sorted")
    checks["table_sort"] = {"column": "Count", "order": ["Harbor2", "Beacon7"]}
    table = ui.result("recipe-table")
    row = label(list(table.iter("node")), "Beacon7")
    if row is None:
        raise RuntimeError("Native table row selection target is missing")
    ui.tap(row)
    ui.result("recipe-table-result", "Selected: Beacon7")
    checks["table_select"] = {"selected": "Beacon7"}
    ui.section("Color")
    ui.result("recipe-color-result", "Selected color: #1565c0")
    picker = ui.result("recipe-color-picker")
    point, palette = green_swatch(ui.frame(), bounds(picker))
    ui.adb("shell", "input", "tap", *point)
    ui.result("recipe-color-result", "Selected color: #4caf50")
    preview = ui.result("recipe-color-preview")
    painted = pixel_counts(ui.frame(), bounds(preview), {"green": GREEN})
    if painted["colors"]["green"] < max(16, painted["sampled_pixels"] // 2):
        raise RuntimeError("The changed color did not paint the preview")
    ui.screenshot("green-preview")
    checks["color_change_and_preview"] = {"color": "#4caf50", "palette": palette,
                                           "preview": painted}
    ui.section("Loading")
    ui.result("recipe-loading-result", "Ready to load sample.")
    ui.tap(ui.button("Load sample"))
    spinner, _ = ui.pending()
    spinner_pixels = pixel_counts(ui.frame(), bounds(spinner), {"blue": BLUE})
    if spinner_pixels["colors"]["blue"] < 8:
        raise RuntimeError("The pending ThreeBounce spinner did not paint")
    ui.screenshot("loading-pending")
    ui.result("recipe-loading-result", "Loaded 3 rows")
    ui.wait(lambda: semantic(ui.nodes(), "recipe-loading") is None, "completed spinner removed")
    ui.screenshot("loading-complete")
    ui.section("Table")
    ui.result("recipe-table-result", "Order: Harbor, Lighthouse, Observatory")
    checks["loading_pending_and_complete"] = {"rows": 3, "spinner_pixels": spinner_pixels}
    ui.section("Loading")
    ui.tap(ui.button("Load sample"))
    _, cancel = ui.pending()
    ui.tap(cancel)
    ui.result("recipe-loading-result", "Loading cancelled")
    # Wait past the default loader's completion; cancellation must not publish.
    time.sleep(3.5)
    ui.result("recipe-loading-result", "Loading cancelled")
    ui.tap(ui.button("Load sample"))
    ui.pending()
    ui.result("recipe-loading-result", "Loaded 3 rows")
    checks["loading_cancel_and_retry"] = {"cancelled_result_retained": True, "retry_rows": 3}
    back = ui.button("Back")
    load = ui.button("Load sample")
    ui.tap(load)
    ui.pending()
    ui.tap(back)
    ui.wait(lambda: label(ui.nodes(), "App home" if startup_template == "app" else "Connected"),
            "Back returns to recipe entry page")
    ui.link(route + "?probe=new-view")
    ui.result("recipe-editor")
    ui.section("Loading")
    ui.result("recipe-loading-result", "Ready to load sample.")
    time.sleep(3.5)
    ui.result("recipe-loading-result", "Ready to load sample.")
    checks["detached_load_keeps_new_page"] = {"result": "Ready to load sample."}
    ui.tap(ui.button("Back"))
    ui.wait(lambda: label(ui.nodes(), "App home" if startup_template == "app" else "Connected"),
            "recipe check return")
    if ui.pid() != pid:
        raise RuntimeError("App-control recipes restarted the runner")
    if set(checks) != set(REQUIRED_CHECKS) or any(not value for value in checks.values()):
        raise RuntimeError("Incomplete Android app-control acceptance")
    receipt = {**identity, "scope": "actual Android keyboard, native control events and painted output",
               "source_pid": pid, "checks": checks, "skips": 0, "success": True}
    validate_recipe_receipt(receipt, identity)
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    print("Passed: app-control recipes: " + json.dumps(receipt), flush=True)
    return receipt
