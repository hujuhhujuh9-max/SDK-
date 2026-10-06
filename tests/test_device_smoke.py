import json
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

from scripts.device_smoke import (adb, collect_diagnostics, find_control, main, pixel_counts,
                                 record_core_services, record_device_environment, runner_pid, wait_for)
from runtime.core_capability_checks import CORE_SERVICE_TYPES


class DeviceWaitTests(unittest.TestCase):
    def test_a_killed_read_only_ui_dump_retries_without_repeating_an_interaction(self):
        command = ("shell", "uiautomator", "dump", "/sdcard/runner-ui.xml")
        killed = subprocess.CalledProcessError(137, ["adb", *command], stderr="Killed")
        with patch("scripts.device_smoke.subprocess.check_output", side_effect=[killed, "UI dumped"]), \
                patch("scripts.device_smoke.time.sleep"):
            self.assertEqual(adb(*command), "UI dumped")
        with patch("scripts.device_smoke.subprocess.check_output", side_effect=killed) as read, \
                patch("scripts.device_smoke.time.sleep"):
            with self.assertRaises(subprocess.CalledProcessError):
                adb(*command)
            self.assertEqual(read.call_count, 3)

    def test_native_helper_is_not_a_second_app_process(self):
        result = type("Result", (), {"stdout": "3011 3144\n"})()
        with patch("scripts.device_smoke.subprocess.run", return_value=result), \
                patch("scripts.device_smoke.adb", return_value="PID PPID\n3011 560\n3144 3011\n"):
            self.assertEqual(runner_pid(), "3011")

    def test_an_exited_helper_and_a_single_pid_still_select_the_app(self):
        result = type("Result", (), {"stdout": "3011 3144\n"})()
        with patch("scripts.device_smoke.subprocess.run", return_value=result), \
                patch("scripts.device_smoke.adb", return_value="PID PPID\n3011 560\n") as read:
            self.assertEqual(runner_pid(), "3011")
            read.reset_mock()
            result.stdout = "3011\n"
            self.assertEqual(runner_pid(), "3011")
            read.assert_not_called()

    def test_two_independent_app_processes_are_still_reported(self):
        result = type("Result", (), {"stdout": "3011 3144\n"})()
        with patch("scripts.device_smoke.subprocess.run", return_value=result), \
                patch("scripts.device_smoke.adb", return_value="PID PPID\n3011 560\n3144 560\n"):
            self.assertEqual(runner_pid(), "3011 3144")

    def test_snapshot_retries_a_brief_offline_connection(self):
        offline = subprocess.CalledProcessError(255, ["adb", "logcat"], stderr="device offline")
        with patch("scripts.device_smoke.subprocess.check_output", side_effect=[offline, "fresh logs"]) as read, \
                patch("scripts.device_smoke.time.sleep"):
            self.assertEqual(adb("logcat", "-d", "-v", "brief"), "fresh logs")
        self.assertEqual(read.call_count, 2)

    def test_failed_taps_are_never_repeated(self):
        offline = subprocess.CalledProcessError(255, ["adb", "shell", "input"], stderr="device offline")
        with patch("scripts.device_smoke.subprocess.check_output", side_effect=offline) as read:
            with self.assertRaises(subprocess.CalledProcessError):
                adb("shell", "input", "tap", 10, 20)
        read.assert_called_once()

    def test_a_permanent_snapshot_failure_still_fails(self):
        offline = subprocess.CalledProcessError(255, ["adb", "logcat"], stderr="device offline")
        with patch("scripts.device_smoke.subprocess.check_output", side_effect=offline) as read, \
                patch("scripts.device_smoke.time.sleep"):
            with self.assertRaises(subprocess.CalledProcessError):
                adb("logcat", "-d", "-v", "brief")
        self.assertEqual(read.call_count, 3)

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


class NativeServiceReceiptTests(unittest.TestCase):
    def receipt(self, pid=100):
        return {"pid": pid, "services": dict(zip(CORE_SERVICE_TYPES, range(1, 8)))}

    def test_reentry_keeps_ids_and_new_process_gets_an_independent_set(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            first = self.receipt()
            record_core_services(output, first, 100)
            record_core_services(output, first, 100)
            other = self.receipt(200)
            other["services"]["battery"] = 50
            record_core_services(output, other, 200)
            self.assertEqual(len(json.loads((output / "core-service-reuse.json").read_text())), 3)

    def test_replaced_service_in_the_same_process_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            record_core_services(output, self.receipt(), 100)
            replaced = self.receipt()
            replaced["services"]["battery"] = 50
            with self.assertRaisesRegex(AssertionError, "replacement core services"):
                record_core_services(output, replaced, 100)
            self.assertEqual(len(json.loads((output / "core-service-reuse.json").read_text())), 1)

    def test_stale_missing_and_duplicate_service_receipts_fail(self):
        for fault in ("stale", "missing", "duplicate"):
            receipt = self.receipt()
            if fault == "stale":
                receipt["pid"] = 200
            elif fault == "missing":
                del receipt["services"]["battery"]
            else:
                receipt["services"]["battery"] = receipt["services"]["connectivity"]
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(AssertionError):
                    record_core_services(Path(folder), receipt, 100)


class LocalVisualPixelTests(unittest.TestCase):
    def framebuffer(self, header_size=12, pixel_format=1):
        pixels = b"".join(bytes((*((233, 30, 99) if x < 3 else (21, 101, 192)), 255))
                          for _ in range(3) for x in range(6))
        return struct.pack("<III", 6, 3, pixel_format) + b"\0" * (header_size - 12) + pixels

    def test_pixels_outside_the_selected_control_cannot_pass_its_probe(self):
        colors = {"pink": (233, 30, 99), "blue": (21, 101, 192)}
        for size in (12, 16):
            with self.subTest(header=size):
                report = pixel_counts(self.framebuffer(size), [3, 0, 6, 3], colors)
                self.assertEqual(report["colors"], {"pink": 0, "blue": 1})
                self.assertEqual(report["sampled_pixels"], 1)

    def test_corrupt_or_unsupported_framebuffer_fails(self):
        for frame in (self.framebuffer()[:-1], self.framebuffer(pixel_format=2)):
            with self.subTest(length=len(frame)), self.assertRaises(AssertionError):
                pixel_counts(frame, [0, 0, 3, 3], {"blue": (21, 101, 192)})

    def test_empty_or_offscreen_bounds_fail(self):
        for bounds in ([0, 0, 0, 3], [0, 0, 7, 3], [-1, 0, 3, 3]):
            with self.subTest(bounds=bounds), self.assertRaises(AssertionError):
                pixel_counts(self.framebuffer(), bounds, {"blue": (21, 101, 192)})


class DeviceEnvironmentTests(unittest.TestCase):
    def read(self, *command):
        return {
            ("shell", "getprop"): "[ro.build.version.sdk]: [35]\n"
                "[ro.product.cpu.abi]: [x86_64]\n[ro.kernel.qemu]: [1]\n",
            ("shell", "wm", "size"): "Physical size: 1080x1920\nOverride size: 720x1280\n",
            ("shell", "wm", "density"): "Physical density: 420\nOverride density: 280\n",
        }[command]

    def test_effective_display_matches_the_selected_profile(self):
        with tempfile.TemporaryDirectory() as folder, patch("scripts.device_smoke.adb", side_effect=self.read):
            report = record_device_environment(Path(folder), (720, 1280, 280))
            self.assertEqual(report["display_pixels"], [720, 1280])
            self.assertEqual(report["density_dpi"], 280)
            self.assertEqual(report["logical_display_dp"], [411.429, 731.429])
            self.assertTrue(report["emulator"])

    def test_wrong_profile_fails_but_keeps_the_actual_environment(self):
        with tempfile.TemporaryDirectory() as folder, patch("scripts.device_smoke.adb", side_effect=self.read):
            output = Path(folder)
            with self.assertRaisesRegex(AssertionError, "selected emulator profile"):
                record_device_environment(output, (1080, 1920, 420))
            actual = json.loads((output / "device-environment.json").read_text())
            self.assertEqual(actual["display_pixels"], [720, 1280])


if __name__ == "__main__":
    unittest.main()
