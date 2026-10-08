"""Reject incorrect save-isolation evidence before a device receipt can pass."""

import unittest
import tempfile
from unittest.mock import patch, call, Mock
from pathlib import Path

from scripts.app_starter_device_checks import assert_native_saves_retained, save_directory, native_save_hashes
from scripts.device_smoke import main


class AppStarterDeviceEvidenceTests(unittest.TestCase):
    def test_save_digests_use_shell_for_external_storage_and_run_as_for_private_data(self):
        for directory, prefix in (
                ("/storage/emulated/0/Android/data/org.sdk.runner/files/saves", ("shell",)),
                ("/data/user/0/org.sdk.runner/files/saves", ("shell", "run-as", "org.sdk.runner"))):
            with self.subTest(directory=directory):
                name = "renfletpy-quick-LT1.save"
                device = Mock()
                device.adb.side_effect = [name + "\napp-starter\n", "a" * 64 + "  " + name]
                self.assertEqual(native_save_hashes(device, directory), {name: "a" * 64})
                self.assertEqual(device.adb.call_args_list, [
                    call(*prefix, "ls", directory), call(*prefix, "sha256sum", directory + "/" + name)])

    def test_native_path_marker_must_belong_to_the_fresh_process(self):
        logs = "SDK_RUNNER_APP_SAVE_DIR path=/data/old/app-starter pid=11\n"
        self.assertIsNone(save_directory(logs, "SDK_RUNNER_APP_SAVE_DIR", "22"))
        logs += "SDK_RUNNER_APP_SAVE_DIR path=/data/new/app-starter pid=22\n"
        self.assertEqual(save_directory(logs, "SDK_RUNNER_APP_SAVE_DIR", "22"), "/data/new/app-starter")

    def test_native_path_marker_rejects_shell_metacharacters_or_parent_traversal(self):
        for path in ("/data/../other", "/data/saves;id", "/data/$(id)"):
            with self.subTest(path=path), self.assertRaises(AssertionError):
                save_directory("SDK_RUNNER_APP_SAVE_DIR path=" + path + " pid=22\n",
                               "SDK_RUNNER_APP_SAVE_DIR", "22")

    def test_missing_or_changed_default_saves_cannot_pass_isolation(self):
        before = {"_reload-1-LT1.save": "a", "renfletpy-quick-LT1.save": "b"}
        assert_native_saves_retained(before, dict(before))
        for after in ({}, {"renfletpy-quick-LT1.save": "b"}, dict(before, **{"_reload-1-LT1.save": "changed"})):
            with self.subTest(after=after), self.assertRaises(AssertionError):
                assert_native_saves_retained(before, after)
        with self.assertRaises(AssertionError):
            assert_native_saves_retained({}, {})

    def test_universal_app_fallback_checks_the_x86_baseline_independently(self):
        with tempfile.TemporaryDirectory() as output, \
                patch("sys.argv", ["device_smoke.py", "app.apk", "--startup-template", "app",
                                   "--baseline-apk", "baseline.apk", "--output", output]), \
                patch("scripts.device_smoke.inspect_apk", return_value={"source_sha": "same", "extensions": []}) as inspect, \
                patch("scripts.device_smoke.subprocess.run", side_effect=RuntimeError("before device")):
            with self.assertRaisesRegex(RuntimeError, "before device"):
                main()
            self.assertEqual(inspect.call_args_list[1], call(
                Path("baseline.apk"), ("x86_64",), startup_template="story"))

    def test_cross_source_baseline_is_rejected_before_adb(self):
        with tempfile.TemporaryDirectory() as output, \
                patch("sys.argv", ["device_smoke.py", "app.apk", "--startup-template", "app",
                                   "--baseline-apk", "baseline.apk", "--output", output]), \
                patch("scripts.device_smoke.inspect_apk", side_effect=[{"source_sha": "app"}, {"source_sha": "other"}]), \
                patch("scripts.device_smoke.subprocess.run") as start:
            with self.assertRaisesRegex(AssertionError, "Baseline APK source differs"):
                main()
            start.assert_not_called()
