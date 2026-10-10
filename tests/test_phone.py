"""Check device selection and prevent false phone passes with Android fixtures."""

from contextlib import redirect_stdout
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.check_apk import SUPPORTED_ABIS
from scripts.check_phone import PhoneDevice, check_phone
from test_project_device import AndroidFixture, HEADING, INSPECTION, PACKAGE, quick_wait


class PhoneFixture(AndroidFixture):
    def __init__(self):
        super().__init__()
        self.serial_calls = []
        self.properties = {"ro.build.version.sdk": "35", "ro.build.version.release": "15",
                           "ro.product.cpu.abi": "arm64-v8a", "ro.product.model": "Test ARM phone",
                           "ro.build.fingerprint": "test/physical/API35", "ro.kernel.qemu": "0",
                           "sys.boot_completed": "1"}
        self.state = "device"
        self.title = ""
        self.draft = ""
        self.status = "Records loaded"
        self.lose_record = False
        self.stale_dump = False
        self.new_story_confirmation = False

    def run(self, *args, **options):
        args = tuple(map(str, args))
        if args[0] != "adb":
            return super().run(*args, **options)
        if args[1:3] != ("-s", "PHONE_SERIAL"):
            raise AssertionError("ADB operation was not bound to the selected phone: " + str(args))
        self.serial_calls.append((args, options))
        cmd = args[3:]
        if cmd == ("get-state",):
            return self.state
        if cmd[:2] == ("shell", "getprop"):
            return self.properties[cmd[2]]
        if cmd[:3] == ("shell", "rm", "-f"):
            return ""
        if cmd[:3] == ("shell", "uiautomator", "dump"):
            return "snapshot not ready" if self.stale_dump else "UI hierarchy dumped to: " + cmd[-1]
        if cmd[:2] == ("shell", "cat"):
            if self.mode == "records":
                return ('<hierarchy>'
                        '<node text="Application records" bounds="[10,10][400,50]" />'
                        '<node text="Title" class="android.widget.EditText" bounds="[10,60][400,100]" />'
                        '<node text="Add record" class="android.widget.Button" bounds="[10,110][190,150]" />'
                        f'<node text="{self.status}" bounds="[10,160][400,200]" />'
                        f'<node text="Title: {self.title}" bounds="[10,210][400,250]" />'
                        '</hierarchy>')
            if self.mode == "confirm":
                return ('<hierarchy><node text="Start new story" class="android.widget.Button" '
                        'bounds="[10,80][190,130]" /></hierarchy>')
            xml = super().run("adb", *cmd, **options)
            return xml.replace('</hierarchy>', '<node text="Application records" '
                               'class="android.widget.Button" bounds="[10,250][190,300]" /></hierarchy>')
        if cmd[:3] == ("shell", "input", "tap"):
            if cmd[-1] == "275":
                self.mode = "records"
                self.status = "Records loaded"
                return ""
            if self.mode == "records":
                if cmd[-1] == "130":
                    self.title, self.status = self.draft, "Record saved"
                return ""
            if self.mode == "home" and self.new_story_confirmation:
                self.mode = "confirm"
                return ""
        if cmd[:3] == ("shell", "input", "text"):
            self.draft = cmd[-1]
            return ""
        if cmd[:3] == ("shell", "input", "keyevent") and self.mode == "records":
            return ""
        if cmd[:3] == ("shell", "am", "start") and self.lose_record and self.starts:
            self.title = ""
        return super().run("adb", *cmd, **options)


class PhoneTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / "pass"
        self.device = PhoneFixture()
        self.inspection = INSPECTION | {"abis": list(SUPPORTED_ABIS)}

    def probe(self, **changes):
        options = {"serial": "PHONE_SERIAL", "sha256": "b" * 64, "source_sha": "a" * 40,
                   "aapt": "aapt", "apksigner": "apksigner", "run": self.device.run} | changes
        with patch("scripts.check_phone.inspect_apk", return_value=self.inspection) as inspected, \
                patch.object(PhoneDevice, "wait", quick_wait), redirect_stdout(io.StringIO()):
            result = check_phone("fixture.apk", self.output, **options)
        inspected.assert_called_once_with("fixture.apk", startup_template="app", build_type="release")
        return result

    def receipt(self):
        return json.loads((self.output / "api35-phone.json").read_text())

    def test_api35_arm_pass_binds_all_device_commands_and_proves_fresh_records(self):
        result = self.probe()
        self.assertTrue(result["success"])
        self.assertEqual(result["stage"], "complete")
        self.assertEqual((result["source_pid"], result["restarted_pid"]), ("101", "202"))
        self.assertEqual(result["device"]["api"], 35)
        self.assertFalse(result["device"]["emulator"])
        self.assertEqual(result["device"]["display_pixels"], [480, 800])
        self.assertEqual(result["record_title"], result["checks"]["records_after_reopening"]["title"])
        self.assertEqual(set(result["checks"]), {"install", "launch", "story_start_return", "records_after_reopening"})
        self.assertEqual(self.receipt(), result)
        for name in ("home", "native-story", "returned-home", "record-saved", "reopened-home", "record-reopened"):
            self.assertTrue((self.output / (name + ".png")).exists())
        commands = [args[3:] for args, _ in self.device.serial_calls]
        self.assertNotIn(("logcat", "-c"), commands)
        self.assertFalse(any("uninstall" in cmd or cmd[:3] == ("shell", "pm", "clear") for cmd in commands))
        self.assertEqual(sum(cmd[:3] == ("shell", "am", "force-stop") for cmd in commands), 2)
        self.assertIn(("logcat", "-d", "--pid", "202", "-v", "threadtime"), commands)

    def test_invalid_api_abi_emulator_and_authorization_fail_before_install(self):
        cases = [("ro.build.version.sdk", "36"), ("ro.product.cpu.abi", "x86_64"),
                 ("ro.kernel.qemu", "1"), ("sys.boot_completed", "0")]
        for index, (name, value) in enumerate(cases):
            with self.subTest(name=name):
                self.output = self.output.parent / str(index)
                self.device = PhoneFixture()
                self.device.properties[name] = value
                with self.assertRaises(RuntimeError):
                    self.probe()
                self.assertFalse(self.receipt()["success"])
                self.assertEqual(self.receipt()["stage"], "phone preflight")
                self.assertFalse(any(args[3] == "install" for args, _ in self.device.serial_calls))
        self.output = self.output.parent / "unauthorized"
        self.device = PhoneFixture()
        self.device.state = "unauthorized"
        with self.assertRaisesRegex(RuntimeError, "authorized"):
            self.probe()

    def test_changed_hash_source_or_unsigned_release_never_contacts_phone(self):
        for index, options in enumerate(({"sha256": "e" * 64}, {"source_sha": "e" * 40}, {})):
            with self.subTest(options=options):
                self.output = self.output.parent / str(index)
                self.device = PhoneFixture()
                if not options:
                    self.device.certificates = False
                with self.assertRaises(RuntimeError):
                    self.probe(**options)
                self.assertFalse(self.device.serial_calls)
                self.assertFalse(self.receipt()["success"])

    def test_installed_hash_mismatch_cannot_launch(self):
        self.device.installed_digest = "e" * 64
        with self.assertRaisesRegex(RuntimeError, "Installed APK bytes"):
            self.probe()
        self.assertEqual(self.receipt()["stage"], "install")
        self.assertEqual(self.device.starts, 0)

    def test_lost_record_after_restart_never_reports_a_pass(self):
        self.device.lose_record = True
        with self.assertRaisesRegex(RuntimeError, "Title: API35Record"):
            self.probe()
        result = self.receipt()
        self.assertFalse(result["success"])
        self.assertEqual(result["stage"], "Records after reopening")
        self.assertNotIn("records_after_reopening", result["checks"])
        self.assertTrue((self.output / "phone-logcat.txt").exists())

    def test_same_restart_pid_is_not_fresh_process_evidence(self):
        self.device.same_restart_pid = True
        with self.assertRaisesRegex(RuntimeError, "original app process"):
            self.probe()
        self.assertFalse(self.receipt()["success"])

    def test_blank_native_dialogue_cannot_pass_start_return(self):
        self.device.native_blank = True
        with self.assertRaisesRegex(RuntimeError, "painted native dialogue"):
            self.probe()
        self.assertEqual(self.receipt()["stage"], "story Start/Return")
        self.assertFalse(self.receipt()["success"])

    def test_repeat_run_confirms_new_test_story_without_clearing_records(self):
        self.device.new_story_confirmation = True
        self.assertTrue(self.probe()["success"])

    def test_existing_output_is_not_reused_or_overwritten(self):
        self.output.mkdir()
        old = self.output / "api35-phone.json"
        old.write_text('{"success": true, "old": true}')
        with self.assertRaises(FileExistsError):
            self.probe()
        self.assertEqual(old.read_text(), '{"success": true, "old": true}')
        self.assertFalse(self.device.serial_calls)

    def test_unready_ui_dump_cannot_read_or_tap_a_stale_snapshot(self):
        self.output.mkdir()
        self.device.stale_dump = True
        phone = PhoneDevice(PACKAGE, self.output, "PHONE_SERIAL", "adb", self.device.run)
        self.assertEqual(phone.nodes(), [])
        commands = [args[3:] for args, _ in self.device.serial_calls]
        self.assertEqual(commands[0][:3], ("shell", "rm", "-f"))
        self.assertFalse(any(cmd[:2] == ("shell", "cat") for cmd in commands))


if __name__ == "__main__":
    unittest.main()
