"""Reject signing/version mismatches and false persistence receipts for updates."""

import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import Mock, patch

from scripts.check_project_update import (
    ACTIVITY, BUILD_RECEIPT, check_project_update, inspect_update_pair, installed_update,
)


class ProjectUpdateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.projects = {}
        self.certificates = {"baseline": "d" * 64, "update": "d" * 64}
        self.source_sha = "a" * 40
        for index, stage in enumerate(("baseline", "update"), 1):
            (self.root / stage).mkdir()
            self.projects[stage] = {
                "application_id": "org.renfletpy.update35", "display_name": "RenFletPy Update Test",
                "version_code": index, "version_name": "0.1." + str(index - 1),
                "input_sha256": str(index) * 64, "game_files": {"story.rpy": "f" * 64},
                "asset_files": {"badge.svg": "e" * 64}, "icon_sha256": None,
                "app_home": "my_app:app_home_view",
            }
        self.write_metadata()

    def write_metadata(self):
        for stage, project in self.projects.items():
            (self.root / stage / BUILD_RECEIPT).write_text(json.dumps(
                {"project": project, "build_type": "release", "signing": "signed"}))

    def inspection(self, apk, abis, startup_template, **options):
        return {"source_sha": self.source_sha, "sha256": ("b" if apk.parent.name == "baseline" else "c") * 64,
                "abis": list(abis), "startup_template": startup_template,
                "build_type": options["build_type"], "project": options["project"]}

    def tools(self, *args, **options):
        stage = Path(args[-1] if args[0] == "apksigner" else args[3]).parent.name
        if args[0] == "apksigner":
            return "Signer #1 certificate SHA-256 digest: " + self.certificates[stage]
        self.assertEqual(args[0], "aapt")
        if args[2] != "badging":
            return ""
        project = self.projects[stage]
        return (f"package: name='{project['application_id']}' versionCode='{project['version_code']}' "
                f"versionName='{project['version_name']}'\napplication-label:'{project['display_name']}'\n"
                f"launchable-activity: name='{ACTIVITY}'\n")

    def inspect_pair(self):
        with patch("scripts.check_project_update.inspect_apk", side_effect=self.inspection):
            return inspect_update_pair(self.root, source_sha="a" * 40, aapt="aapt", apksigner="apksigner",
                                       run=self.tools)

    def test_pair_requires_matching_certificate_package_and_native_story(self):
        pair = self.inspect_pair()
        self.assertEqual(pair["update"]["identity"]["version_code"], 2)
        self.assertEqual(pair["baseline"]["certificate_sha256"], pair["update"]["certificate_sha256"])
        self.certificates["update"] = "e" * 64
        with self.assertRaisesRegex(RuntimeError, "signing certificate"):
            self.inspect_pair()
        self.certificates["update"] = "d" * 64
        self.projects["update"]["application_id"] = "org.renfletpy.other"
        self.write_metadata()
        with self.assertRaisesRegex(RuntimeError, "same package"):
            self.inspect_pair()
        self.projects["update"]["application_id"] = "org.renfletpy.update35"
        self.projects["update"]["game_files"] = {"changed.rpy": "e" * 64}
        self.write_metadata()
        with self.assertRaisesRegex(RuntimeError, "native story"):
            self.inspect_pair()

    def test_equal_or_lower_versions_are_not_updates(self):
        for version in (1, 0):
            with self.subTest(version=version):
                self.projects["update"]["version_code"] = version
                self.write_metadata()
                with self.assertRaisesRegex(RuntimeError, "version_code must increase"):
                    self.inspect_pair()

    def test_unsigned_or_wrong_source_pair_cannot_pass(self):
        self.source_sha = "f" * 40
        with self.assertRaisesRegex(RuntimeError, "source differs"):
            self.inspect_pair()
        self.source_sha = "a" * 40
        self.certificates["baseline"] = ""
        with self.assertRaisesRegex(RuntimeError, "verified signing certificate"):
            self.inspect_pair()
        (self.root / "baseline" / BUILD_RECEIPT).write_text('{"signing":"unsigned","build_type":"release"}')
        with self.assertRaisesRegex(RuntimeError, "signed release"):
            self.inspect_pair()

    def fake_device(self, *, lost_record=False, restored=True):
        pair = self.inspect_pair()
        baseline = {"source_pid": "101", "restarted_pid": "202", "device": {"api": 35},
                    "checks": {"records_after_reopening": {"title": "OriginalRecord"}}}
        device = Mock()
        device.package = "org.renfletpy.update35"
        state = {"stage": "baseline", "pid": "202", "uid": "10234"}

        def adb(*args, **options):
            if args[:3] == ("shell", "dumpsys", "package"):
                version = pair[state["stage"]]["identity"]
                return (f"Package [{device.package}]\nuserId={state['uid']}\n"
                        f"versionCode={version['version_code']} minSdk=24\n"
                        f"versionName={version['version_name']}\npkgFlags=[ HAS_CODE ]\n")
            if args[:3] == ("shell", "pm", "path"):
                return "package:/data/app/~~hash/org.renfletpy.update35-key/base.apk\n"
            if args[:2] == ("shell", "sha256sum"):
                return pair[state["stage"]]["inspection"]["sha256"] + "  /data/app/base.apk\n"
            if args[:2] == ("exec-out", "screencap"):
                return struct.pack("<III", 1, 1, 1) + bytes((24, 60, 70, 255))
            if args[:3] == ("shell", "am", "force-stop"):
                state["pid"] = None
            elif args[0] == "install":
                self.assertEqual(args[1], "-r")
                state["stage"] = "update"
            elif args[:3] == ("shell", "am", "start"):
                state["pid"] = "303"
            return ""

        def control(label, **options):
            if lost_record and label == "Title: OriginalRecord":
                raise RuntimeError("Saved Record is missing after update")
            return {"enabled": "true"}

        def wait(callback, description, **options):
            result = callback()
            if result is None or result is False:
                raise RuntimeError("Did not observe " + description)
            return result

        device.adb.side_effect = adb
        device.pid.side_effect = lambda: state["pid"]
        device.wait.side_effect = wait
        device.control.side_effect = control
        logs = ("SDK_RUNNER_APP_STORY action=started phase=active pid=202\n"
                "SDK_RUNNER_SAVE action=saved kind=scene pid=202\n"
                "SDK_RUNNER_APP_STORY action=completed phase=completed pid=202\n")
        if restored:
            logs += "SDK_RUNNER_APP_STORY action=restored phase=active pid=303\n"
        device.logs.return_value = logs
        return pair, baseline, device

    def probe(self, **options):
        pair, baseline, device = self.fake_device(**options)
        output = self.root / "evidence"
        output.mkdir(exist_ok=True)
        (output / "project-update.json").write_text('{"success":true}')
        with patch("scripts.check_project_update.inspect_update_pair", return_value=pair), \
                patch("scripts.check_project_update.check_project_device", return_value=baseline), \
                patch("scripts.check_project_update.ProjectDevice", return_value=device), \
                patch("scripts.check_project_update.native_dialogue_pixels", return_value={"painted": True}), \
                redirect_stdout(io.StringIO()):
            return check_project_update(self.root, output, source_sha="a" * 40,
                                        aapt="aapt", apksigner="apksigner"), device

    def test_actual_update_records_fresh_process_and_unanswered_checkpoint(self):
        receipt, device = self.probe()
        self.assertEqual(receipt["updated_pid"], "303")
        self.assertEqual(receipt["baseline_install"]["uid"], receipt["updated_install"]["uid"])
        self.assertEqual(receipt["checks"]["records_after_update"]["title"], "OriginalRecord")
        self.assertTrue(receipt["checks"]["story_after_update"]["restored_unanswered_choice"])
        mutations = [call.args for call in device.adb.call_args_list
                     if call.args[0] in ("install", "uninstall") or call.args[:3] == ("shell", "pm", "clear")]
        self.assertEqual(len(mutations), 1)
        self.assertEqual(mutations[0][:2], ("install", "-r"))
        self.assertEqual(receipt["skips"], 0)

    def test_lost_record_or_missing_native_restore_removes_stale_success(self):
        for options in ({"lost_record": True}, {"restored": False}):
            with self.subTest(options=options), self.assertRaisesRegex(RuntimeError, "missing|restored"):
                self.probe(**options)
            self.assertFalse((self.root / "evidence/project-update.json").exists())
            self.assertTrue((self.root / "evidence/update-logcat.txt").exists())

    def test_wrong_installed_version_or_bytes_are_rejected(self):
        pair, _, device = self.fake_device()
        version = copy.deepcopy(pair["baseline"])
        version["identity"]["version_code"] = 2
        with self.assertRaisesRegex(RuntimeError, "identity"):
            installed_update(device, version, self.root, "wrong-version")
        version = copy.deepcopy(pair["baseline"])
        version["inspection"]["sha256"] = "f" * 64
        with self.assertRaisesRegex(RuntimeError, "bytes differ"):
            installed_update(device, version, self.root, "wrong-bytes")


if __name__ == "__main__":
    unittest.main()
