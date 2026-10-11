"""Reject stale, ambiguous or incomplete cross-boundary Android evidence."""

import copy
import io
import json
import struct
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from scripts.check_project_capabilities import (
    ACTIVITY, PACKAGE, RECEIPT, artifact_manifest, check_log_errors, check_project_capabilities,
    debug_identity, digest, marker_records, meaningful_rive_event, native_button_bounds,
    owner_proof, pixel_comparison, restored_model, rive_cleanup, rive_ready, save_archive, single_result,
    strict_json,
)


def log(marker, data, pid=101, *, level="I", tag="python"):
    return f"{level}/{tag}  ({pid:5d}): {marker} " + json.dumps(data)


def state(pid=101, revision=7, phase="committed"):
    return {"pid": pid, "owner_thread": 321, "kind": "rive_console", "revision": revision,
            "version": 2, "phase": phase, "state": {"progress": 50.0, "downloading": False, "receipt": None},
            "result": None}


def frame(width=64, height=64, *, changed=False, blank=False, buttons=()):
    colors = ((30, 50, 70, 255), (50, 150, 160, 255), (160, 30, 100, 255), (240, 230, 210, 255))
    pixels = bytearray()
    for y in range(height):
        for x in range(width):
            color = (0, 0, 0, 255) if blank else colors[(x // 16 + y // 16) % 4]
            if changed and 16 <= x < 32 and 16 <= y < 32:
                color = (200, 100, 40, 255)
            if any(left <= x < right and top <= y < bottom for left, top, right, bottom in buttons):
                color = (38, 62, 80, 255)
            pixels.extend(color)
    return struct.pack("<III", width, height, 1) + pixels


class MarkerEvidenceTests(unittest.TestCase):
    def test_android_pid_binds_payload_and_filters_stale_process(self):
        logs = log("SDK_CAP_ACTIVITY_STATE", state()) + "\n" + log("SDK_CAP_ACTIVITY_STATE", state(202), 202)
        records = marker_records(logs, "202")
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["data"]["pid"], 202)
        self.assertEqual(records[0]["line"], 1)
        with self.assertRaisesRegex(RuntimeError, "PID differs"):
            marker_records(log("SDK_CAP_ACTIVITY_STATE", state(202), 101))
        self.assertEqual(marker_records("SDK_CAP_ACTIVITY_STATE " + json.dumps(state())), [])

    def test_malformed_duplicate_nonfinite_and_nonobject_receipts_fail(self):
        for value in ('{"pid":101,"pid":202}', '{"progress":NaN}', '{"progress":1e400}', "[]", "{bad"):
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                marker_records("I/python (101): SDK_CAP_ACTIVITY_STATE " + value)
        with self.assertRaises(ValueError):
            strict_json('{"state":{"progress":Infinity}}')

    def test_exact_restoration_requires_new_revision_or_new_pid(self):
        before, after = state(), state(revision=8, phase="restored")
        self.assertTrue(restored_model(before, after, fresh_process=False)["exact_model"])
        self.assertTrue(restored_model(before, state(202, 1, "restored"), fresh_process=True)["fresh_process"])
        for incorrect in (state(101, 7, "restored"), state(101, 8, "committed"),
                          {**after, "version": 1}, {**after, "state": {"progress": 49}},
                          {**after, "result": {"status": "completed", "value": None}}):
            with self.subTest(value=incorrect), self.assertRaises(RuntimeError):
                restored_model(before, incorrect, fresh_process=False)
        with self.assertRaisesRegex(RuntimeError, "old process"):
            restored_model(before, after, fresh_process=True)

    def test_native_owner_is_consistent_and_install_is_single(self):
        observer = {"pid": 101, "owner_thread": 321, "schema": 1, "observer": "project_capabilities",
                    "source_sha256": "a" * 64}
        logs = log("SDK_CAP_OBSERVER", observer) + "\n" + log("SDK_CAP_ACTIVITY_STATE", state())
        self.assertEqual(owner_proof(marker_records(logs), 101), observer)
        with self.assertRaisesRegex(RuntimeError, "owning thread"):
            owner_proof(marker_records(logs + "\n" + log("SDK_CAP_APP_STATE", {"pid": 101, "owner_thread": 900})), 101)
        with self.assertRaisesRegex(RuntimeError, "one native"):
            owner_proof(marker_records(logs + "\n" + log("SDK_CAP_OBSERVER", observer)), 101)

    def test_native_result_must_be_meaningful_returned_once_and_match_project_story(self):
        expected = {"status": "completed", "value": {"selected": 12, "camera": {"scale": 0.6}, "input_receipts": 2}}
        native = {"pid": 101, "owner_thread": 321, "revision": 7, "kind": "scale_canvas", "result": expected}
        project = {"kind": "scale_canvas", "result": expected}
        logs = log("SDK_CAP_ACTIVITY_RESULT", native) + "\n" + log("SDK_2D_ACTIVITY_RESULT", project)
        self.assertEqual(single_result(marker_records(logs), 101, "scale_canvas", expected)["return_count"], 1)
        for incorrect in (log("SDK_CAP_ACTIVITY_RESULT", native), logs + "\n" + log("SDK_CAP_ACTIVITY_RESULT", native)):
            with self.assertRaisesRegex(RuntimeError, "exactly one"):
                single_result(marker_records(incorrect), 101, "scale_canvas", expected)
        with self.assertRaisesRegex(RuntimeError, "meaningful"):
            single_result(marker_records(logs), 101, "scale_canvas", {"status": "completed", "value": None})

    def test_tracebacks_and_rive_failures_cannot_be_hidden_by_success_marker(self):
        for message in ("Traceback (most recent call last):", "SDK_RIVE_ERROR id=12 message=bad asset",
                        "Unhandled Exception: control disposed", "FATAL EXCEPTION: main"):
            with self.subTest(message=message), self.assertRaises(RuntimeError):
                check_log_errors("E/flutter (101): " + message, [101])
        check_log_errors("I/python (202): Traceback (most recent call last):", [101])


class RiveEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.model = state()["state"]
        self.ready = {"role": "forest", "revision": 7, "data": {
            "artboard": "Tree", "width": 640, "height": 360, "machines": ["Loading"],
            "inputs": {"Progress": "number", "Downloading": "boolean"},
            "numbers": {"Progress": 50.0}, "booleans": {"Downloading": False}}}

    def test_actual_manifest_proves_type_bounds_and_reconstructed_values(self):
        self.assertEqual(rive_ready(self.ready, self.model, "forest"), self.ready)
        for field, value in (("height", 0), ("numbers", {"Progress": 25}),
                             ("booleans", {"Downloading": True}),
                             ("inputs", {"Progress": "boolean", "Downloading": "boolean"})):
            changed = copy.deepcopy(self.ready)
            changed["data"][field] = value
            with self.subTest(field=field), self.assertRaises(RuntimeError):
                rive_ready(changed, self.model, "forest")

    def test_trigger_requires_real_signal_artboard_and_meaningful_event(self):
        signal = {"role": "signal", "data": {"artboard": "New Artboard", "width": 72, "height": 72,
            "machines": ["State Machine 1"], "inputs": {"FireGeneralEvent": "trigger"}}}
        rive_ready(signal, self.model, "signal")
        event = {"role": "signal", "revision": 7, "data": {"name": "SomeGeneralEvent", "type": "general",
            "properties": {"SomeNumber": 11.0, "SomeBoolean": True, "SomeString": "Something"}}}
        self.assertEqual(meaningful_rive_event(event), event["data"])
        for change in ({"data": {"name": "imported"}}, {"role": "forest"},
                       {"data": {**event["data"], "properties": {"SomeNumber": 11.0, "SomeBoolean": 1, "SomeString": "Something"}}}):
            with self.assertRaises(RuntimeError):
                meaningful_rive_event({**event, **change})

    def test_cleanup_requires_every_actual_controller_in_the_fresh_process(self):
        lines = ["I/flutter (202): SDK_RIVE_READY id=forest artboard=Tree",
                 "I/flutter (202): SDK_RIVE_READY id=signal artboard=New Artboard",
                 "I/flutter (202): SDK_RIVE_DISPOSED id=forest"]
        self.assertIsNone(rive_cleanup("\n".join(lines), 202))
        self.assertIsNone(rive_cleanup("\n".join(lines + ["I/flutter (101): SDK_RIVE_DISPOSED id=signal"]), 202))
        proof = rive_cleanup("\n".join(lines + ["I/flutter (202): SDK_RIVE_DISPOSED id=signal"]), 202)
        self.assertTrue(proof["all_controllers_disposed"])
        self.assertEqual(proof["disposed_ids"], ["forest", "signal"])


class ArtifactEvidenceTests(unittest.TestCase):
    def test_playback_and_pause_require_actual_colored_pixels(self):
        bounds = [0, 0, 64, 64]
        motion = pixel_comparison(frame(), frame(changed=True), bounds, moving=True)
        self.assertGreater(motion["changed_fraction"], 0.002)
        self.assertEqual(pixel_comparison(frame(), frame(), bounds, moving=False)["changed_pixels"], 0)
        for first, second, moving in ((frame(), frame(), True), (frame(), frame(changed=True), False),
                                      (frame(blank=True), frame(blank=True), False)):
            with self.subTest(moving=moving), self.assertRaises(RuntimeError):
                pixel_comparison(first, second, bounds, moving=moving)

    def test_native_continue_uses_unique_painted_button_bounds(self):
        actual = native_button_bounds(frame(height=160, buttons=([16, 110, 48, 126],)))
        self.assertTrue(all(abs(one - two) <= 2 for one, two in zip(actual, [16, 110, 48, 126])))
        self.assertTrue(16 <= (actual[0] + actual[2]) // 2 < 48)
        for buttons in ((), ([16, 110, 48, 126], [16, 132, 48, 148])):
            with self.assertRaises(RuntimeError):
                native_button_bounds(frame(height=160, buttons=buttons))

    def test_native_save_metadata_is_read_without_executing_game_pickle(self):
        metadata = {"app_story": {"version": 1, "story_id": "app-recipe", "phase": "active", "value": None}}
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w") as saved:
            for name, data in (("json", json.dumps(metadata)), ("log", b"not executable by this reader"),
                               ("signatures", b"native signature bytes"), ("renpy_version", b"8.5.3")):
                saved.writestr(name, data)
        proof = save_archive(content.getvalue())
        self.assertEqual(proof["metadata"], metadata)
        self.assertFalse(proof["unpickled"])
        self.assertEqual(proof["sha256"], digest(content.getvalue()))
        with self.assertRaises(RuntimeError):
            save_archive(b"not a native save")
        for bad in ([], {"app_story": {**metadata["app_story"], "phase": "completed"}}):
            bad_archive = io.BytesIO()
            with zipfile.ZipFile(bad_archive, "w") as saved:
                for name in ("log", "signatures", "renpy_version"):
                    saved.writestr(name, b"bytes")
                saved.writestr("json", json.dumps(bad))
            with self.assertRaises(RuntimeError):
                save_archive(bad_archive.getvalue())

    def test_raw_artifact_hashes_cover_ui_pixels_and_logs_and_reject_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for name, data in (("ui.xml", b"<hierarchy/>"), ("screen.png", b"actual collected PNG bytes"),
                               ("capabilities-logcat.txt", b"native markers")):
                (output / name).write_bytes(data)
            (output / RECEIPT).write_text("stale receipt is excluded")
            evidence = artifact_manifest(output)
            self.assertNotIn(RECEIPT, evidence)
            self.assertEqual(evidence["ui.xml"], {"sha256": digest(b"<hierarchy/>"), "size": 12})
            (output / "alias.txt").symlink_to(output / "capabilities-logcat.txt")
            with self.assertRaises(RuntimeError):
                artifact_manifest(output)


class PackageGatesTests(unittest.TestCase):
    def test_debug_identity_requires_project_label_version_and_disabled_permissions(self):
        project = {"application_id": PACKAGE, "display_name": "Project Capabilities", "version_code": 7, "version_name": "1.0"}
        badging = (f"package: name='{PACKAGE}' versionCode='7' versionName='1.0'\n"
                   "application-label:'Project Capabilities'\n"
                   f"launchable-activity: name='{ACTIVITY}'\napplication-debuggable\n")
        self.assertTrue(debug_identity(badging, "", "", project)["debuggable"])
        for changed in (badging.replace("Project Capabilities", "Other"), badging.replace("'7'", "'8'"),
                        badging.replace("application-debuggable", "")):
            with self.assertRaises(RuntimeError):
                debug_identity(changed, "", "", project)
        with self.assertRaises(RuntimeError):
            debug_identity(badging, "uses-permission: name='android.permission.RECORD_AUDIO'", "", project)

    def test_invalid_requests_delete_stale_success_and_never_operate_device(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            for options in ({"expected_api": 36}, {"source_sha": "short"}, {"package": "org.someone.app"}):
                (output / RECEIPT).write_text('{"success":true}')
                run = unittest.mock.Mock(side_effect=AssertionError("No device or compiler should run"))
                arguments = {"source_sha": "a" * 40, "project_input_sha256": "b" * 64, "aapt": "aapt", **options}
                with self.subTest(options=options), self.assertRaises(ValueError):
                    check_project_capabilities("fixture.apk", output, run=run, **arguments)
                self.assertFalse((output / RECEIPT).exists())
                run.assert_not_called()

    def test_apk_source_mismatch_fails_before_installation(self):
        with tempfile.TemporaryDirectory() as directory, patch(
                "scripts.check_project_capabilities.inspect_apk", return_value={"source_sha": "c" * 40}):
            run = unittest.mock.Mock()
            with self.assertRaisesRegex(RuntimeError, "APK source"):
                check_project_capabilities("fixture.apk", directory, source_sha="a" * 40,
                                           project_input_sha256="b" * 64, aapt="aapt", run=run)
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
