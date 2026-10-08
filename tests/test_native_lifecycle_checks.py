"""The native verifier must reject missing evidence and preserve save fixtures."""

import json
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from scripts.check_native_lifecycle import copy_metadata, run_process, run_source_check, save_hashes


class NativeLifecycleChecksTests(unittest.TestCase):
    def test_guard_fixtures_change_json_without_breaking_log_or_signature(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "original.save"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("json", json.dumps({"_version": "original", "sdk_native_story": {"schema": 1}}))
                archive.writestr("log", b"original native script position")
                archive.writestr("signatures", b"original signature")
            original = source.read_bytes()
            for identity in (None, "corrupt", {"profile": "foreign", "schema": 999}):
                with self.subTest(identity=identity):
                    destination = root / "guard.save"
                    copy_metadata(source, destination, identity)
                    with zipfile.ZipFile(destination) as archive:
                        self.assertEqual(archive.read("log"), b"original native script position")
                        self.assertEqual(archive.read("signatures"), b"original signature")
                        if identity == "corrupt":
                            with self.assertRaises(json.JSONDecodeError):
                                json.loads(archive.read("json"))
                        else:
                            metadata = json.loads(archive.read("json"))
                            self.assertEqual(metadata["_version"], "original")
                            self.assertEqual(metadata.get("sdk_native_story"), identity)
            self.assertEqual(source.read_bytes(), original)

    def test_demo_hash_snapshot_tracks_replacement_and_excludes_profile_children(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "quick.save").write_bytes(b"demo")
            profile = root / "optional"
            profile.mkdir()
            (profile / "quick.save").write_bytes(b"optional")
            original = save_hashes(root)
            self.assertEqual(list(original), ["quick.save"])
            (profile / "quick.save").write_bytes(b"optional changed")
            self.assertEqual(save_hashes(root), original)
            (root / "quick.save").write_bytes(b"demo overwritten")
            self.assertNotEqual(save_hashes(root), original)

    def test_zero_exit_and_stale_receipt_cannot_pass_without_new_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            (output / "probe.json").write_text('{"mode": "probe", "checks": ["stale"]}')
            with patch("scripts.check_native_lifecycle.subprocess.run", return_value=SimpleNamespace(returncode=0)):
                with self.assertRaisesRegex(RuntimeError, "Native probe failed"):
                    run_process(output, output, output, "probe", output, {})

    def test_timeout_reports_the_phase_log(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            with patch("scripts.check_native_lifecycle.subprocess.run",
                       side_effect=subprocess.TimeoutExpired("renpy", 60)):
                with self.assertRaisesRegex(RuntimeError, "probe timed out.*probe.log"):
                    run_process(output, output, output, "probe", output, {})

    def test_unknown_override_is_removed_between_fresh_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)

            def complete(command, **kwargs):
                env = kwargs["env"]
                self.assertNotIn("RENPY_AUTO_LOAD", env)
                Path(env["SDK_NATIVE_LIFECYCLE_RECEIPT"]).write_text(
                    json.dumps({"mode": "probe", "pid": 42, "checks": ["fresh"]}))
                return SimpleNamespace(returncode=0)

            with patch("scripts.check_native_lifecycle.subprocess.run", side_effect=complete):
                receipt = run_process(output, output, output, "probe", output, {"RENPY_AUTO_LOAD": "foreign"})
            self.assertEqual(receipt["pid"], 42)

    def test_compile_zero_exit_with_init_exception_is_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)

            def failed(command, **kwargs):
                kwargs["stdout"].write("Full traceback:\nAn init callback failed.\n")
                return SimpleNamespace(returncode=0)

            with patch("scripts.check_native_lifecycle.subprocess.run", side_effect=failed):
                with self.assertRaisesRegex(RuntimeError, "compile failed"):
                    run_source_check(output, output, output, "compile", output / "compile.log", {})
