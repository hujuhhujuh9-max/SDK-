import json
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from scripts.device_smoke import collect_diagnostics, find_control, main, wait_for


class DeviceWaitTests(unittest.TestCase):
    def test_leaf_ui_control_is_a_successful_result(self):
        button = ET.fromstring('<node class="android.widget.Button" content-desc="Increment" />')
        self.assertIs(wait_for(lambda: button, seconds=0.1), button)

    def test_android_text_field_can_be_selected_without_serialized_hint(self):
        field = ET.fromstring('<node class="android.widget.EditText" text="" content-desc="" />')
        label = ET.fromstring('<node class="android.widget.TextView" text="Capabilities" />')
        with patch("scripts.device_smoke.controls", return_value=[label, field]):
            self.assertIs(find_control("Input probe", Path("unused.xml"),
                                      control_class="android.widget.EditText"), field)


class DeviceDiagnosticsTests(unittest.TestCase):
    def test_unavailable_window_does_not_prevent_other_snapshots(self):
        def read(*command, timeout):
            self.assertEqual(timeout, 15)
            if command == ("shell", "dumpsys", "window"):
                raise subprocess.CalledProcessError(1, ["adb", *command])
            return "SDK_RUNNER_FLET_READY pid=123\n"

        with tempfile.TemporaryDirectory() as folder, patch("scripts.device_smoke.adb", side_effect=read):
            output = Path(folder)
            with self.assertRaisesRegex(RuntimeError, "window.txt"):
                collect_diagnostics(output)
            self.assertTrue((output / "activity.txt").is_file())
            self.assertTrue((output / "input-method.txt").is_file())
            self.assertIn("SDK_RUNNER_FLET_READY", (output / "logcat.txt").read_text())
            self.assertEqual(set(json.loads((output / "diagnostics.json").read_text())["errors"]),
                             {"window.txt"})

    def test_disconnect_keeps_previously_saved_logs(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "logcat.txt").write_text("last available device log")
            failure = subprocess.TimeoutExpired(["adb", "logcat"], 15)
            with patch("scripts.device_smoke.adb", side_effect=failure):
                with self.assertRaisesRegex(RuntimeError, "Incomplete Android diagnostics"):
                    collect_diagnostics(output)
            self.assertEqual((output / "logcat.txt").read_text(), "last available device log")
            errors = json.loads((output / "diagnostics.json").read_text())["errors"]
            self.assertIn("logcat.txt", errors)
            self.assertIn("runner.png", errors)

    def test_cleanup_failure_does_not_replace_the_original_device_error(self):
        primary = subprocess.CalledProcessError(1, ["adb", "shell", "getprop"], stderr="device offline")
        with tempfile.TemporaryDirectory() as folder:
            with patch("sys.argv", ["device_smoke.py", "unused.apk", "--output", folder]), \
                    patch("scripts.device_smoke.inspect_apk", return_value={"extensions": ["flet_audio"]}), \
                    patch("scripts.device_smoke.subprocess.run"), \
                    patch("scripts.device_smoke.adb", side_effect=primary), \
                    patch("scripts.device_smoke.collect_diagnostics",
                          side_effect=RuntimeError("diagnostics connection failed")):
                with self.assertRaises(subprocess.CalledProcessError) as raised:
                    main()
            self.assertIs(raised.exception, primary)


if __name__ == "__main__":
    unittest.main()
