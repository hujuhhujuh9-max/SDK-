"""Exercise custom release gates with isolated Android command/frame fixtures."""

from contextlib import redirect_stdout
import hashlib
import io
import json
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.check_project_device import (
    ACTIVITY, FORBIDDEN_PERMISSIONS, LOCATION_SERVICE, ProjectDevice,
    check_project_device, release_identity,
)


PACKAGE = "org.renfletpy.example"
HEADING = "My RenFletPy App"
PROJECT = {"application_id": PACKAGE, "display_name": "RenFletPy Example",
           "version_code": 7, "version_name": "1.2", "input_sha256": "c" * 64}
INSPECTION = {"source_sha": "a" * 40, "sha256": "b" * 64, "abis": ["x86_64"],
              "startup_template": "app", "build_type": "release", "project": PROJECT}
BADGING = (f"package: name='{PACKAGE}' versionCode='7' versionName='1.2'\n"
           "application-label:'RenFletPy Example'\n" + f"launchable-activity: name='{ACTIVITY}'\n")
# Actual main run 37931772567: AAPT resolved every density to this shortened path.
ICON_BADGING = "".join(f"application-icon-{density}:'res/NN.png'\n"
                       for density in (120, 160, 240, 320, 480, 640, 65534))
ICON = b"\x89PNG\r\n\x1a\nretained supplied icon fixture"
ICON_SHA256 = hashlib.sha256(ICON).hexdigest()


def quick_wait(self, callback, description, seconds=60):
    result = callback()
    if result is None or result is False:
        raise RuntimeError("Fixture did not observe " + description)
    return result


class AndroidFixture:
    def __init__(self):
        self.calls = []
        self.badging = BADGING
        self.starts = 0
        self.pid = None
        self.mode = "home"
        self.logs = ""
        self.asset_paints = True
        self.native_covered = False
        self.native_blank = False
        self.same_restart_pid = False
        self.emit_story_marker = True
        self.installed_digest = "b" * 64
        self.certificates = True
        self.fail_return = False
        self.failed = False
        self.fail_diagnostics = False

    def frame(self):
        width, height = 480, 800
        color = (24, 60, 70, 255) if self.mode == "native" else (0, 0, 0, 255)
        pixels = bytearray(bytes(color) * width * height)
        if self.mode == "native" and not self.native_blank:
            box, color = (30, 650, 400, 720), bytes((244, 240, 232, 255))
        elif self.mode != "native" and self.asset_paints:
            box, color = (10, 10, 190, 58), bytes((21, 101, 192, 255))
        else:
            box = (0, 0, 0, 0)
        left, top, right, bottom = box
        for y in range(top, bottom):
            pixels[(y * width + left) * 4:(y * width + right) * 4] = color * (right - left)
        return struct.pack("<III", width, height, 1) + pixels

    def run(self, *args, **options):
        args = tuple(map(str, args))
        self.calls.append((args, options))
        if args[0] == "apksigner":
            return "Signer #1 certificate SHA-256 digest: " + "d" * 64 if self.certificates else ""
        if args[0] == "aapt":
            return self.badging if args[2] == "badging" else ""
        if args[0] != "adb":
            raise AssertionError(args)
        cmd = args[1:]
        if cmd == ("wait-for-device",):
            return ""
        if cmd[:2] == ("shell", "getprop"):
            return {"sys.boot_completed": "1", "ro.build.version.sdk": "36",
                    "ro.product.cpu.abi": "x86_64", "ro.kernel.qemu": "1"}[cmd[2]]
        if cmd == ("shell", "wm", "density"):
            return "Physical density: 420\n"
        if cmd[0] == "install":
            return "Success\n"
        if cmd[:3] == ("shell", "dumpsys", "package"):
            return f"Package [{PACKAGE}]\nversionCode=7 minSdk=24\nversionName=1.2\npkgFlags=[ HAS_CODE ]\n"
        if cmd[:3] == ("shell", "pm", "path"):
            return f"package:/data/app/~~hash/{PACKAGE}-key/base.apk\n"
        if cmd[:2] == ("shell", "sha256sum"):
            return self.installed_digest + "  /data/app/base.apk\n"
        if cmd == ("logcat", "-c"):
            self.logs = ""
            return ""
        if cmd[:2] == ("logcat", "-d"):
            if self.failed and self.fail_diagnostics:
                raise RuntimeError("diagnostic failure")
            return self.logs
        if cmd[:3] == ("shell", "am", "start"):
            self.starts += 1
            self.pid = "101" if self.starts == 1 or self.same_restart_pid else "202"
            self.mode = "home"
            self.logs += "\n".join("SDK_RUNNER_" + marker + " pid=" + self.pid for marker in
                                   ("FLUTTER_ATTACHED", "RENPY_READY", "FLET_READY")) + "\n"
            return "Status: ok\n"
        if cmd[:3] == ("shell", "am", "force-stop"):
            self.pid = None
            return ""
        if cmd[:2] == ("shell", "pidof"):
            if self.pid is None:
                raise subprocess.CalledProcessError(1, args, output="")
            return self.pid
        if cmd[:3] == ("shell", "uiautomator", "dump"):
            return "UI hierarchy dumped\n"
        if cmd[:2] == ("shell", "cat"):
            button = "Return to app" if self.mode == "menu" else "Start story"
            return (f'<hierarchy><node text="{HEADING}" bounds="[10,150][400,200]" />'
                    f'<node resource-id="{PACKAGE}:id/project-home-asset" bounds="[10,10][190,58]" />'
                    f'<node text="{button}" class="android.widget.Button" enabled="true" '
                    'bounds="[10,80][190,130]" /></hierarchy>')
        if cmd[:3] == ("shell", "input", "tap"):
            if self.mode == "menu":
                self.mode = "home"
                self.logs += "SDK_RUNNER_APP_STORY action=return revision=1 pid=" + self.pid + "\n"
            else:
                self.mode = "native"
                self.logs += "SDK_RUNNER_APP_STORY action=started revision=1 pid=" + self.pid + "\n"
                if self.emit_story_marker:
                    self.logs += "SDK_RUNNER_PROJECT_STORY pid=" + self.pid + "\n"
                viewport = {"presentation": "scene", "height": 800, "scene_height": 800,
                            "flet_height": 100 if self.native_covered else 0, "ime_overlap": 0}
                self.logs += "SDK_RUNNER_VIEWPORT " + json.dumps(viewport) + "\n"
            return ""
        if cmd[:3] == ("shell", "input", "keyevent"):
            if self.fail_return:
                self.failed = True
                raise RuntimeError("native Return failure")
            self.mode = "menu"
            return ""
        if cmd[:2] == ("exec-out", "screencap"):
            return b"\x89PNG\r\n\x1a\nfixture screenshot" if "-p" in cmd else self.frame()
        raise AssertionError(args)


class ProjectDeviceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name)
        self.device = AndroidFixture()

    def probe(self, *, apk="fixture.apk", inspection=INSPECTION, **changes):
        options = {"source_sha": "a" * 40, "project_input_sha256": "c" * 64,
                   "story_marker": "SDK_RUNNER_PROJECT_STORY", "aapt": "aapt", "apksigner": "apksigner",
                   "expected_display": (480, 800, 420), "run": self.device.run} | changes
        with patch("scripts.check_project_device.inspect_apk", return_value=inspection) as inspected, \
                patch.object(ProjectDevice, "wait", quick_wait), redirect_stdout(io.StringIO()):
            result = check_project_device(apk, PACKAGE, HEADING, self.output, **options)
            inspected.assert_called_once_with(apk, ("x86_64",), "app", build_type="release",
                                             project={"application_id": PACKAGE, "input_sha256": "c" * 64})
            return result

    def icon_apk(self, files):
        path = self.output / "icons.apk"
        with zipfile.ZipFile(path, "w") as apk:
            for name, data in files.items():
                apk.writestr(name, data)
        return path

    def test_signed_custom_release_proves_home_asset_native_return_and_fresh_restart(self):
        receipt = self.probe()
        self.assertEqual((receipt["source_pid"], receipt["restarted_pid"]), ("101", "202"))
        self.assertEqual(receipt["project_input_sha256"], "c" * 64)
        self.assertEqual(receipt["installed_sha256"], "b" * 64)
        self.assertEqual(receipt["certificate_sha256"], ["d" * 64])
        self.assertEqual(receipt["checks"]["native_story"]["story_marker_pid"], "101")
        self.assertEqual(set(receipt["checks"]), {"custom_home", "native_story", "return_to_custom_home", "fresh_process_home"})
        self.assertEqual(receipt["skips"], 0)
        self.assertEqual(json.loads((self.output / "project-device.json").read_text()), receipt)
        for name in ("project-home", "project-native-story", "project-returned", "project-restarted"):
            self.assertTrue((self.output / (name + ".png")).exists())
        self.assertEqual(next(options["timeout"] for args, options in self.device.calls if args[1] == "install"), 180)

    def test_manifest_identity_release_and_every_disabled_permission_are_required(self):
        for data in (BADGING.replace(PACKAGE, "org.other.app"), BADGING.replace("versionCode='7'", "versionCode='8'"),
                     BADGING + "application-debuggable\n"):
            with self.subTest(data=data):
                with self.assertRaises(RuntimeError):
                    release_identity(data, "", "", PROJECT)
        for permission in FORBIDDEN_PERMISSIONS:
            with self.subTest(permission=permission):
                with self.assertRaisesRegex(RuntimeError, "disabled"):
                    release_identity(BADGING, "uses-permission: name='" + permission + "'", "", PROJECT)
        with self.assertRaisesRegex(RuntimeError, "disabled"):
            release_identity(BADGING, "", LOCATION_SERVICE, PROJECT)
        self.assertEqual(release_identity(BADGING, "", "", PROJECT)["version_code"], 7)

    def test_compiled_icon_bytes_accept_actual_aapt_shortening_and_density_qualifiers(self):
        project = PROJECT | {"icon_sha256": ICON_SHA256}
        for path, badging in (("res/NN.png", ICON_BADGING),
                              ("res/drawable-xxxhdpi-v4/runner_icon.png",
                               "application-icon-640:'res/drawable-xxxhdpi-v4/runner_icon.png'\n")):
            with self.subTest(path=path):
                apk = self.icon_apk({path: ICON})
                identity = release_identity(BADGING + badging, "", "", project, apk=apk)
                self.assertEqual(identity["application_icons"], [path] * (7 if path == "res/NN.png" else 1))
                self.assertEqual(identity["application_icon_sha256"], {path: ICON_SHA256})

    def test_icon_evidence_rejects_missing_tampered_or_unrelated_compiled_bytes(self):
        project = PROJECT | {"icon_sha256": ICON_SHA256}
        original = {"assets/retained-original.png": ICON}
        cases = ((BADGING, original), (BADGING + ICON_BADGING, original),
                 (BADGING + ICON_BADGING, original | {"res/NN.png": b"changed compiled icon"}),
                 (BADGING + ICON_BADGING + "application-icon-960:'res/other.png'\n",
                  original | {"res/NN.png": ICON, "res/other.png": b"unrelated icon"}))
        for badging, files in cases:
            with self.subTest(badging=badging, files=list(files)):
                with self.assertRaisesRegex(RuntimeError, "compiled application icon|Compiled application icon"):
                    release_identity(badging, "", "", project, apk=self.icon_apk(files))
        with self.assertRaisesRegex(RuntimeError, "differs from the supplied icon"):
            release_identity(BADGING + ICON_BADGING, "", "", project | {"icon_sha256": "e" * 64},
                             apk=self.icon_apk({"res/NN.png": ICON}))
        with self.assertRaisesRegex(RuntimeError, "Missing compiled application icon evidence"):
            release_identity(BADGING + ICON_BADGING, "", "", project)

    def test_icon_guard_failure_retains_compiled_diagnostics_before_any_device_operation(self):
        self.device.badging += ICON_BADGING
        inspection = INSPECTION | {"project": PROJECT | {"icon_sha256": ICON_SHA256}}
        (self.output / "project-device.json").write_text('{"success":true}')
        with self.assertRaisesRegex(RuntimeError, "Missing compiled application icon bytes"):
            self.probe(apk=self.icon_apk({"assets/retained-original.png": ICON}), inspection=inspection)
        self.assertEqual(json.loads((self.output / "apk-inspection.json").read_text()), inspection)
        self.assertIn(ICON_BADGING, (self.output / "project-apk-manifest.txt").read_text())
        self.assertTrue((self.output / "project-apk-signature.txt").exists())
        self.assertFalse(any(args[0] == "adb" for args, _ in self.device.calls))
        self.assertFalse((self.output / "project-device.json").exists())

    def test_visible_leaf_xml_control_is_an_acknowledgement_even_without_children(self):
        node = ET.fromstring('<node text="My RenFletPy App" />')
        device = ProjectDevice(PACKAGE, self.output, self.device.run)
        self.assertIs(device.wait(lambda: node, "visible heading"), node)

    def test_missing_signature_or_wrong_source_rejects_before_device_mutation(self):
        self.device.certificates = False
        with self.assertRaisesRegex(RuntimeError, "signing certificate"):
            self.probe()
        self.assertFalse(any(args[0] == "adb" for args, _ in self.device.calls))
        with self.assertRaisesRegex(RuntimeError, "source"):
            self.probe(source_sha="f" * 40)
        self.assertFalse((self.output / "project-device.json").exists())

    def test_installed_bytes_cannot_claim_another_inspected_release(self):
        self.device.installed_digest = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "Installed APK bytes"):
            self.probe()
        self.assertEqual(self.device.starts, 0)
        self.assertFalse((self.output / "project-device.json").exists())

    def test_blank_asset_rejects_and_removes_a_previous_success_receipt(self):
        self.device.asset_paints = False
        (self.output / "project-device.json").write_text('{"success":true}')
        with self.assertRaisesRegex(RuntimeError, "asset did not paint"):
            self.probe()
        self.assertFalse((self.output / "project-device.json").exists())

    def test_native_scope_dialogue_and_supplied_marker_each_need_actual_evidence(self):
        for field in ("native_covered", "native_blank", "emit_story_marker"):
            with self.subTest(field=field):
                self.device = AndroidFixture()
                setattr(self.device, field, field != "emit_story_marker")
                with self.assertRaisesRegex(RuntimeError, "native"):
                    self.probe()
                self.assertFalse((self.output / "project-device.json").exists())

    def test_restart_requires_a_distinct_process(self):
        self.device.same_restart_pid = True
        with self.assertRaisesRegex(RuntimeError, "fresh process"):
            self.probe()
        self.assertFalse((self.output / "project-device.json").exists())

    def test_diagnostic_failure_does_not_mask_the_native_failure_or_write_success(self):
        self.device.fail_return = self.device.fail_diagnostics = True
        with self.assertRaisesRegex(RuntimeError, "native Return failure"):
            self.probe()
        self.assertFalse((self.output / "project-device.json").exists())

    def test_invalid_external_digest_or_marker_rejects_before_tools(self):
        for options in ({"project_input_sha256": "unknown"}, {"story_marker": "bad; command"}):
            with self.subTest(options=options):
                with self.assertRaises(ValueError):
                    self.probe(**options)
        self.assertEqual(self.device.calls, [])
