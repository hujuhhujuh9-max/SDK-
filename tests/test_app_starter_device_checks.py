"""Reject incorrect save-isolation evidence before a device receipt can pass."""

from contextlib import nullcontext
import hashlib
import io
import json
import unittest
import tempfile
import zipfile
from unittest.mock import patch, call, Mock
from pathlib import Path

from scripts.app_starter_device_checks import (
    APP_BOOKMARK, app_bookmark_path, assert_native_saves_retained, save_directory,
    native_save_hashes, unsigned_app_bookmark, unsigned_bookmark,
)
from scripts.device_smoke import main


class AppStarterDeviceEvidenceTests(unittest.TestCase):
    def test_private_save_digests_use_the_app_uid(self):
        directory = "/data/user/0/org.sdk.runner/files/saves"
        name = "renfletpy-quick-LT1.save"
        device = Mock()
        device.adb.side_effect = [name + "\napp-starter\n", "a" * 64 + "  " + name]
        self.assertEqual(native_save_hashes(device, directory), {name: "a" * 64})
        self.assertEqual(device.adb.call_args_list, [
            call("shell", "run-as", "org.sdk.runner", "ls", directory),
            call("shell", "run-as", "org.sdk.runner", "sha256sum", directory + "/" + name)])

    def test_external_save_digests_read_the_emulator_backing_and_restore_shell_uid(self):
        directory = "/storage/emulated/0/Android/data/org.sdk.runner/files/saves"
        backing = "/data/media/0/Android/data/org.sdk.runner/files/saves"
        name = "renfletpy-quick-LT1.save"
        device = Mock()
        device.runner_pid.return_value = "1234"
        device.adb.side_effect = ["1", "UID\n10216", "", "", "0", name, "a" * 64 + "  " + name,
                                  "", "", "2000", "UID\n10216"]
        self.assertEqual(native_save_hashes(device, directory), {name: "a" * 64})
        self.assertEqual(device.adb.call_args_list, [
            call("shell", "getprop", "ro.kernel.qemu"), call("shell", "ps", "-p", "1234", "-o", "UID"),
            call("root"), call("wait-for-device"),
            call("shell", "id", "-u"), call("shell", "ls", backing),
            call("shell", "sha256sum", backing + "/" + name), call("unroot"), call("wait-for-device"),
            call("shell", "id", "-u"), call("shell", "ps", "-p", "1234", "-o", "UID")])

    def test_external_save_inspection_never_roots_a_physical_device(self):
        device = Mock()
        device.adb.return_value = "0"
        with self.assertRaisesRegex(AssertionError, "acceptance emulator"):
            native_save_hashes(device, "/storage/emulated/0/Android/data/org.sdk.runner/files/saves")
        device.adb.assert_called_once_with("shell", "getprop", "ro.kernel.qemu")

    def test_external_save_inspection_restores_shell_uid_after_read_failure(self):
        device = Mock()
        device.runner_pid.return_value = "1234"
        device.adb.side_effect = ["1", "UID\n10216", "", "", "0", RuntimeError("read failed"),
                                  "", "", "2000", "UID\n10216"]
        with self.assertRaisesRegex(RuntimeError, "read failed"):
            native_save_hashes(device, "/storage/emulated/0/Android/data/org.sdk.runner/files/saves")
        self.assertEqual(device.adb.call_args_list[-4:], [
            call("unroot"), call("wait-for-device"), call("shell", "id", "-u"),
            call("shell", "ps", "-p", "1234", "-o", "UID")])

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


class UnsignedNativeBookmarkTests(unittest.TestCase):
    def signed_bookmark(self, *, phase="active", story_id="app-recipe", signature=b"signature trusted-key payload\n"):
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.comment = b"native checkpoint metadata"
            archive.writestr("json", json.dumps({"app_story": {
                "version": 1, "story_id": story_id, "phase": phase, "value": None}}))
            archive.writestr("log", b"\x80native\x00state\r\n\xff\x81\x00")
            archive.writestr("extra_info", b"The Lighthouse Note")
            archive.writestr("screenshot.png", bytes(range(256)))
            archive.writestr("renpy_version", b"Ren'Py 8.5.3")
            archive.writestr("signatures", signature)
        return output.getvalue()

    def test_unsigned_fixture_preserves_every_native_payload_byte(self):
        data = self.signed_bookmark()
        unsigned = unsigned_bookmark(data)
        self.assertNotEqual(hashlib.sha256(data).digest(), hashlib.sha256(unsigned).digest())
        with zipfile.ZipFile(io.BytesIO(data)) as before, zipfile.ZipFile(io.BytesIO(unsigned)) as after:
            self.assertEqual(after.namelist(), [name for name in before.namelist() if name != "signatures"])
            self.assertEqual(after.comment, before.comment)
            for name in after.namelist():
                self.assertEqual(after.read(name), before.read(name), name)
                self.assertEqual(after.getinfo(name).compress_type, before.getinfo(name).compress_type)
                self.assertEqual(after.getinfo(name).external_attr, before.getinfo(name).external_attr)

    def test_fixture_requires_a_signed_active_app_checkpoint(self):
        for data in (self.signed_bookmark(signature=b""), self.signed_bookmark(phase="completed"),
                     self.signed_bookmark(story_id="another-story")):
            with self.subTest(data=data[:20]), self.assertRaises(AssertionError):
                unsigned_bookmark(data)

    def test_ambiguous_or_incomplete_archive_is_rejected(self):
        for entries in (("log", "json"), ("log", "log", "json", "signatures")):
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as archive:
                for name in entries:
                    with self.assertWarns(UserWarning) if name == "log" and archive.namelist() else nullcontext():
                        archive.writestr(name, b"fixture")
            with self.subTest(entries=entries), self.assertRaises(AssertionError):
                unsigned_bookmark(output.getvalue())

    def test_only_the_exact_app_bookmark_can_be_selected_for_write(self):
        directories = {
            "/storage/emulated/0/Android/data/org.sdk.runner/files/saves/app-starter":
                "/data/media/0/Android/data/org.sdk.runner/files/saves/app-starter/",
            "/data/user/0/org.sdk.runner/files/saves/app-starter":
                "/data/user/0/org.sdk.runner/files/saves/app-starter/",
            "/data/data/org.sdk.runner/files/saves/app-starter":
                "/data/data/org.sdk.runner/files/saves/app-starter/",
            "/data/user_de/0/org.sdk.runner/files/saves/app-starter":
                "/data/user_de/0/org.sdk.runner/files/saves/app-starter/",
        }
        for directory, backing in directories.items():
            with self.subTest(directory=directory):
                self.assertEqual(app_bookmark_path(directory), backing + APP_BOOKMARK)

    def test_default_or_foreign_or_traversal_paths_fail_before_adb(self):
        base = "/storage/emulated/0/Android/data/org.sdk.runner/files/saves"
        for directory in (base, base + "/app-starter/", base + "/app-starter/../",
                          base + "/app-starter-other", base.replace("org.sdk.runner", "another.app") + "/app-starter",
                          base + "/app-starter;id", base + "//app-starter"):
            device = Mock()
            with self.subTest(directory=directory), self.assertRaises(AssertionError), \
                    unsigned_app_bookmark(device, directory, Path("unused")):
                self.fail("Invalid fixture path was accepted")
            device.adb.assert_not_called()

    def test_unsigned_fixture_never_roots_physical_hardware(self):
        device = Mock()
        device.adb.return_value = "0"
        with tempfile.TemporaryDirectory() as directory, self.assertRaisesRegex(AssertionError, "acceptance emulator"), \
                unsigned_app_bookmark(device, "/data/user/0/org.sdk.runner/files/saves/app-starter", Path(directory)):
            self.fail("Physical device was accepted")
        device.adb.assert_called_once_with("shell", "getprop", "ro.kernel.qemu")

    def test_original_signed_bytes_are_restored_when_acceptance_fails(self):
        data = self.signed_bookmark()
        writes = []
        with tempfile.TemporaryDirectory() as output, \
                patch("scripts.app_starter_device_checks._rooted_emulator", side_effect=lambda device: nullcontext()), \
                patch("scripts.app_starter_device_checks._bookmark_stat", return_value="10216:10216:600:42:regular file"), \
                patch("scripts.app_starter_device_checks._bookmark_digest", return_value=hashlib.sha256(data).hexdigest()), \
                patch("scripts.app_starter_device_checks.subprocess.check_output", return_value=data), \
                patch("scripts.app_starter_device_checks._write_bookmark",
                      side_effect=lambda device, path, local, metadata: writes.append(local.read_bytes())):
            with self.assertRaisesRegex(RuntimeError, "acceptance failed"):
                with unsigned_app_bookmark(Mock(), "/data/user/0/org.sdk.runner/files/saves/app-starter", Path(output)):
                    raise RuntimeError("acceptance failed")
        self.assertEqual(writes, [unsigned_bookmark(data), data])
