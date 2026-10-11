"""Reject stale, ambiguous or incomplete cross-boundary Android evidence."""

import copy
import gzip
import io
import json
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import Mock, call, patch

from scripts.check_project_capabilities import (
    ACTIVITY, PACKAGE, RECEIPT, CapabilitiesProbe, artifact_manifest, check_log_errors, check_project_capabilities,
    check_story_rive,
    debug_identity, digest, marker_records, meaningful_rive_event, native_button_bounds,
    owner_proof, pixel_comparison, restored_model, rive_cleanup, rive_lifecycle, rive_ready, rive_slider_bounds,
    save_archive, set_rive_progress, single_result,
    strict_json,
)
from scripts.check_project_device import ProjectDevice


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

    def test_concatenated_markers_keep_both_payloads_and_android_origin(self):
        # Run 38146631432 concatenated Canvas input and native state writes
        # onto one Android log line while the two owner loops were active.
        input_event = {"workload": "canvas", "command": "camera", "revision": 407,
                       "note": "}SDK_CAP_ACTIVITY_STATE {inside a JSON string"}
        logs = (log("SDK_2D_INPUT", input_event) + "SDK_CAP_ACTIVITY_STATE " + json.dumps(state())
                + "\n" + log("SDK_CAP_ACTIVITY_STATE", state(revision=8)))
        records = marker_records(logs, 101)
        self.assertEqual([record["marker"] for record in records],
                         ["SDK_2D_INPUT", "SDK_CAP_ACTIVITY_STATE", "SDK_CAP_ACTIVITY_STATE"])
        self.assertEqual([record["pid"] for record in records], [101, 101, 101])
        self.assertEqual([record["line"] for record in records], [0, 0, 1])
        self.assertEqual([record["data"] for record in records], [input_event, state(), state(revision=8)])
        self.assertEqual(marker_records(logs, 202), [])

    def test_concatenated_markers_still_reject_corruption_and_wrong_pid(self):
        first = log("SDK_2D_INPUT", {"workload": "canvas", "command": "camera"})
        for suffix in ('SDK_CAP_ACTIVITY_STATE {"pid":202}',
                       'SDK_CAP_ACTIVITY_STATE {"pid":101,"pid":101}',
                       'SDK_CAP_ACTIVITY_STATE {"progress":NaN}',
                       'SDK_CAP_ACTIVITY_STATE {"progress":1e400}',
                       'SDK_CAP_ACTIVITY_STATE []', 'SDK_CAP_ACTIVITY_STATE {bad',
                       '{}', 'unrelated text'):
            with self.subTest(suffix=suffix), self.assertRaises(RuntimeError):
                marker_records(first + suffix)

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

    def test_forest_projection_preserves_native_terminal_game_value(self):
        terminal = {**self.model, "progress": 100.0}
        projected = copy.deepcopy(self.ready)
        projected["data"]["numbers"]["Progress"] = 99.0
        self.assertEqual(rive_ready(projected, terminal, "forest"), projected)
        self.assertEqual(terminal["progress"], 100.0)
        for wrong in (100.0, 98.0, 50.0):
            projected["data"]["numbers"]["Progress"] = wrong
            with self.subTest(value=wrong), self.assertRaises(RuntimeError):
                rive_ready(projected, terminal, "forest")

    def test_loop_requires_the_actual_selected_animation_manifest(self):
        loop = {"role": "loop", "revision": 7, "data": {"artboard": "New Artboard", "width": 1000,
            "height": 1000, "animations": ["bouncing"], "machines": [], "inputs": {}, "numbers": {}, "booleans": {},
            "active": False, "speed_multiplier": 0.0}}
        self.assertEqual(rive_ready(loop, self.model, "loop"), loop)
        for field, value in (("animations", []), ("animations", ["bouncing", "other"]),
                             ("machines", ["State Machine 1"]), ("numbers", {"Progress": 50}),
                             ("artboard", "Tree"), ("active", True), ("active", 0),
                             ("speed_multiplier", 1.0), ("speed_multiplier", False)):
            changed = copy.deepcopy(loop)
            changed["data"][field] = value
            with self.subTest(field=field, value=value), self.assertRaises(RuntimeError):
                rive_ready(changed, self.model, "loop")
        playing = copy.deepcopy(loop)
        playing["data"].update(active=True, speed_multiplier=1.0)
        rive_ready(playing, {**self.model, "downloading": True}, "loop")

    def test_pause_and_resume_require_actual_loop_playback_transitions(self):
        paused = {"role": "loop", "revision": 7, "data": {"active": False, "reason": "properties"}}
        self.assertEqual(rive_lifecycle(paused, active=False, reasons=("properties",)), paused)
        rive_lifecycle({"role": "loop", "data": {"active": True, "reason": "resumed"}},
                       active=True, reasons=("resumed",))
        for incorrect in ({**paused, "role": "forest"}, {**paused, "data": {"active": 0, "reason": "properties"}},
                          {**paused, "data": {"active": True, "reason": "properties"}},
                          {**paused, "data": {"active": False, "reason": "resumed"}}):
            with self.assertRaises(RuntimeError):
                rive_lifecycle(incorrect, active=False, reasons=("properties",))

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
                 "I/flutter (202): SDK_RIVE_READY id=loop artboard=New Artboard",
                 "I/flutter (202): SDK_RIVE_DISPOSED id=forest",
                 "I/flutter (202): SDK_RIVE_DISPOSED id=signal"]
        self.assertIsNone(rive_cleanup("\n".join(lines), 202))
        self.assertIsNone(rive_cleanup("\n".join(lines + ["I/flutter (101): SDK_RIVE_DISPOSED id=loop"]), 202))
        proof = rive_cleanup("\n".join(lines + ["I/flutter (202): SDK_RIVE_DISPOSED id=loop"]), 202)
        self.assertTrue(proof["all_controllers_disposed"])
        self.assertEqual(proof["disposed_ids"], ["forest", "loop", "signal"])
        self.assertIsNone(rive_cleanup("\n".join(line for line in lines if "id=loop" not in line), 202))


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

    def test_native_narrow_edge_buttons_use_pixels_instead_of_sample_counts(self):
        for button in ([6, 420, 120, 460], [222, 420, 300, 460]):
            with self.subTest(button=button):
                captured = frame(width=300, height=600, buttons=(button,))
                self.assertEqual(native_button_bounds(captured), button)
        for buttons in ((), ([6, 420, 120, 460], [6, 470, 120, 510])):
            with self.subTest(buttons=buttons), self.assertRaisesRegex(RuntimeError, "uniquely locate"):
                native_button_bounds(frame(width=300, height=600, buttons=buttons))

    def test_native_continue_is_unique_in_the_actual_api35_failure_capture(self):
        # Run 38130952147, SDK 2027e31eadeba276063aaf3b5323cddf5732eced:
        # 1080x1920 RGBA screencap including the real button caption and shaders.
        fixture = Path(__file__).parent / "fixtures/capabilities-native-continue-api35.rgba.gz"
        captured = gzip.decompress(fixture.read_bytes())
        self.assertEqual(digest(captured), "44f063a3ab39de250b55a251a2a8f82b5b1ce2c763c6fa639b9c78c79fd0703c")
        painted = native_button_bounds(captured)
        self.assertEqual(painted, [24, 1346, 430, 1394])
        # Caption pixels can split a band. Its measured center remains within
        # the complete visible button [24,1346,429,1442], without a guessed tap.
        self.assertTrue(24 <= (painted[0] + painted[2]) // 2 < 429)
        self.assertTrue(1346 <= (painted[1] + painted[3]) // 2 < 1442)

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

    def test_only_top_level_emulator_stream_can_change_after_artifact_sealing(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "nested").mkdir()
            contents = {"ui.xml": b"<hierarchy/>", "screen.png": b"collected PNG bytes",
                        "capabilities-logcat.txt": b"native owner and result markers",
                        "quick.save": b"native save archive", "playback.rgba.gz": b"raw motion pixels",
                        "emulator.log.bak": b"immutable diagnostic", "nested/emulator.log": b"nested evidence"}
            for name, data in contents.items():
                (output / name).write_bytes(data)
            stream = output / "emulator.log"
            stream.write_text("emulator running\n")
            sealed = artifact_manifest(output)
            self.assertEqual(set(sealed), set(contents))
            with stream.open("a") as writer:
                writer.write("normal emulator shutdown\n")
            self.assertEqual(artifact_manifest(output), sealed)
            self.assertIn("normal emulator shutdown", stream.read_text())
            for name, data in contents.items():
                with self.subTest(immutable_artifact=name):
                    self.assertEqual(sealed[name], {"sha256": digest(data), "size": len(data)})
                    (output / name).write_bytes(data + b"changed")
                    self.assertNotEqual(artifact_manifest(output)[name], sealed[name])
                    (output / name).write_bytes(data)

    def test_emulator_stream_exclusion_preserves_symlink_and_missing_raw_ui_refusals(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "ui.xml").write_text("<hierarchy/>")
            (output / "screen.png").write_bytes(b"collected PNG bytes")
            (output / "emulator.log").symlink_to(output / "ui.xml")
            with self.assertRaisesRegex(RuntimeError, "regular files"):
                artifact_manifest(output)
            (output / "emulator.log").unlink()
            (output / "screen.png").unlink()
            (output / "emulator.log").write_text("diagnostic is not a raw screenshot")
            with self.assertRaisesRegex(RuntimeError, "raw semantic UI or screenshots"):
                artifact_manifest(output)


class RiveBackgroundFenceTests(unittest.TestCase):
    class FinishedFirstBackground(Exception):
        pass

    def setUp(self):
        self.order = []
        self.cursor_value = 0
        self.toggle_cursor = None
        self.background_ready_roles = set()
        self.corrupt_loop = False
        self.device = Mock(package=PACKAGE)
        self.probe = Mock(device=self.device)
        self.initial = self.model(25, True, 7)
        self.loaded = self.model(50, False, 8)
        self.newer = self.model(50, True, 8)
        self.previous = {"sha256": "a" * 64, "read_scope": {"read_only": True, "shell_uid_after": 2000}}
        self.records = iter([
            *self.ready(self.initial),
            ("SDK_CAP_RIVE_LIFECYCLE", self.lifecycle(False, "properties", 7)),
            ("SDK_CAP_RIVE_LIFECYCLE", self.lifecycle(True, "properties", 7)),
            ("SDK_CAP_RIVE_INPUT", self.manifest("forest", self.model(50, False, 7))),
            *self.ready(self.loaded), *self.ready(self.newer),
            ("SDK_CAP_RIVE_LIFECYCLE", self.lifecycle(False, "paused", 8)),
            ("SDK_CAP_RIVE_LIFECYCLE", self.lifecycle(True, "resumed", 8)),
        ])
        self.models = iter([self.model(25, False, 7), self.initial, self.model(50, False, 7), self.newer])
        self.probe.cursor.side_effect = self.cursor
        self.probe.activity.side_effect = self.activity
        self.probe.wait_record.side_effect = self.record
        self.probe.quick_load.return_value = {"after": self.loaded}
        self.probe.previous_mobile_save.side_effect = self.prior_save
        self.probe.save_bytes.side_effect = self.saved
        self.probe.background_reopen.side_effect = self.FinishedFirstBackground
        self.device.adb.side_effect = self.adb
        self.enterContext(patch("scripts.check_project_capabilities.advance_to_activity", return_value=self.initial))
        self.enterContext(patch("scripts.check_project_capabilities.set_rive_progress"))
        self.enterContext(patch("scripts.check_project_capabilities.time.sleep"))

    @staticmethod
    def model(progress, playing, revision):
        result = state(revision=revision)
        result["state"].update(progress=progress, downloading=playing)
        return result

    @staticmethod
    def manifest(role, model):
        playing, progress = model["state"]["downloading"], model["state"]["progress"]
        data = {
            "forest": {"artboard": "Tree", "width": 640, "height": 360, "machines": ["Loading"],
                       "inputs": {"Progress": "number", "Downloading": "boolean"},
                       "numbers": {"Progress": progress}, "booleans": {"Downloading": playing}},
            "signal": {"artboard": "New Artboard", "width": 72, "height": 72,
                       "machines": ["State Machine 1"], "inputs": {"FireGeneralEvent": "trigger"}},
            "loop": {"artboard": "New Artboard", "width": 1000, "height": 1000,
                     "animations": ["bouncing"], "machines": [], "inputs": {}, "numbers": {}, "booleans": {},
                     "active": playing, "speed_multiplier": 1.0 if playing else 0.0},
        }[role]
        return {"role": role, "revision": model["revision"], "data": data}

    def ready(self, model):
        return [("SDK_CAP_RIVE_READY", self.manifest(role, model)) for role in ("forest", "signal", "loop")]

    @staticmethod
    def lifecycle(active, reason, revision):
        return {"role": "loop", "revision": revision, "data": {"active": active, "reason": reason}}

    def cursor(self):
        self.cursor_value += 1
        return self.cursor_value

    def activity(self, kind, pid, *, after, predicate):
        model = next(self.models)
        self.assertEqual((kind, pid), ("rive_console", "101"))
        self.assertTrue(predicate(model))
        if model is self.newer:
            self.toggle_cursor = after
            self.order.append("native_committed")
        return model

    def record(self, marker, *, pid, after=-1, predicate):
        expected, result = next(self.records)
        self.assertEqual((marker, pid), (expected, "101"))
        self.assertTrue(predicate(result))
        if marker == "SDK_CAP_RIVE_READY" and result["revision"] == 8 and after != -1:
            self.assertEqual(after, self.toggle_cursor, "Ready must follow the same playback toggle")
            self.assertFalse(predicate({**result, "revision": 7}))
            self.assertFalse(predicate({**result, "role": "unrelated"}))
            self.order.append("ready_" + result["role"])
            self.background_ready_roles.add(result["role"])
            if self.corrupt_loop and result["role"] == "loop":
                result["data"].update(active=False, speed_multiplier=0.0)
        elif marker == "SDK_CAP_RIVE_LIFECYCLE" and result["data"]["reason"] in ("paused", "resumed"):
            self.order.append(result["data"]["reason"])
        return result

    def prior_save(self, pid):
        self.assertEqual(pid, "101")
        self.assertEqual(self.background_ready_roles, {"forest", "signal", "loop"})
        self.order.append("prior_save")
        return self.previous

    def saved(self, pid, slot, name, *, previous_sha):
        self.assertEqual((pid, slot, name, previous_sha), ("101", "_reload-1", "rive-background", "a" * 64))
        self.assertEqual(self.order[-1], "paused")
        self.order.append("new_archive")
        return {"sha256": "b" * 64}

    def adb(self, *args):
        if args == ("shell", "input", "keyevent", "3"):
            self.assertEqual(self.background_ready_roles, {"forest", "signal", "loop"})
            self.assertEqual(self.order[-1], "prior_save")
            self.order.append("home")
        elif args == ("shell", "am", "start", "-W", "-n", PACKAGE + "/" + ACTIVITY):
            self.assertEqual(self.order[-1], "new_archive")
            self.order.append("foreground")
        else:
            self.fail("Unexpected device command: " + repr(args))

    def test_home_follows_fresh_actual_ready_and_save_waits_for_prior_archive_replacement(self):
        with self.assertRaises(self.FinishedFirstBackground):
            check_story_rive(self.probe, "101")
        self.assertEqual(self.order, ["native_committed", "ready_forest", "ready_signal", "ready_loop",
                                     "prior_save", "home", "paused", "new_archive", "foreground", "resumed"])
        self.probe.background_reopen.assert_called_once_with(self.newer, "rive")

    def test_committed_playing_model_with_actual_paused_loop_manifest_cannot_send_home(self):
        self.corrupt_loop = True
        with self.assertRaisesRegex(RuntimeError, "actual bouncing animation"):
            check_story_rive(self.probe, "101")
        self.device.adb.assert_not_called()
        self.probe.previous_mobile_save.assert_not_called()
        self.probe.save_bytes.assert_not_called()


class RiveSliderGeometryTests(unittest.TestCase):
    def setUp(self):
        # Run 38139184828 attempt 2/job114470624415; actual API35 Flutter tree.
        self.captured = (Path(__file__).parent / "fixtures/capabilities-rive-slider-api35.xml").read_bytes()
        self.root = ET.fromstring(self.captured)

    @staticmethod
    def controls(root):
        slider = next(node for node in root.iter("node") if node.get("class") == "android.widget.SeekBar")
        parent = next(node for node in root.iter("node") if any(child is slider for child in node))
        return slider, parent

    def test_actual_capture_exposes_a_thumb_but_the_parent_contains_the_full_slider(self):
        self.assertEqual(digest(self.captured), "342d3806af057413bbf5b75e7ea5a97c3e2b338bcebf275019c479969137c606")
        slider, _ = self.controls(self.root)
        self.assertEqual(ProjectDevice.bounds(slider), [283, 1257, 409, 1383])
        self.assertEqual(slider.get("content-desc"), "25%")
        self.assertEqual(rive_slider_bounds(self.root.iter("node")), [84, 1257, 996, 1383])

    def test_real_input_targets_full_bounds_and_still_waits_for_exact_native_game_values(self):
        for value, x in ((50, 540), (100, 994)):
            with self.subTest(value=value):
                device = Mock()
                device.nodes.return_value = list(self.root.iter("node"))
                device.control.return_value = self.controls(self.root)[0]
                device.bounds.side_effect = ProjectDevice.bounds
                probe = Mock(device=device)
                probe.cursor.return_value = 73
                committed = state()
                committed["state"]["progress"] = value

                def observed(kind, pid, *, after, predicate):
                    self.assertEqual((kind, pid, after), ("rive_console", "101", 73))
                    self.assertTrue(predicate(committed))
                    for wrong in (25, value - 0.01):
                        changed = copy.deepcopy(committed)
                        changed["state"]["progress"] = wrong
                        self.assertFalse(predicate(changed))
                    return committed

                probe.activity.side_effect = observed
                self.assertIs(set_rive_progress(probe, "101", value), committed)
                device.adb.assert_called_once_with("shell", "input", "tap", x, 1320)

    def test_unsupported_accessibility_shapes_and_parent_geometry_fail_before_input(self):
        for target, attribute, value in (
                ("slider", "enabled", "false"), ("slider", "package", "other.package"),
                ("parent", "clickable", "true"), ("parent", "scrollable", "true"),
                ("parent", "class", "android.widget.ScrollView"), ("parent", "visible-to-user", "false"),
                ("parent", "bounds", "[84,84][996,1836]"),  # The actual scroll grandparent.
                ("parent", "bounds", "[283,1257][409,1383]"),  # Thumb-sized parent.
                ("parent", "bounds", "[500,1257][996,1383]")):
            with self.subTest(target=target, attribute=attribute, value=value):
                root = copy.deepcopy(self.root)
                slider, parent = self.controls(root)
                (slider if target == "slider" else parent).set(attribute, value)
                device = Mock()
                device.nodes.return_value = list(root.iter("node"))
                probe = Mock(device=device)
                with self.assertRaises(RuntimeError):
                    set_rive_progress(probe, "101", 50)
                device.adb.assert_not_called()
                probe.activity.assert_not_called()

    def test_missing_hidden_or_ambiguous_seekbars_and_parents_are_rejected(self):
        for change in ("missing", "hidden", "duplicate", "missing_parent", "duplicate_parent"):
            with self.subTest(change=change):
                root = copy.deepcopy(self.root)
                slider, parent = self.controls(root)
                if change == "missing":
                    parent.remove(slider)
                elif change == "hidden":
                    slider.set("visible-to-user", "false")
                elif change == "duplicate":
                    parent.append(copy.deepcopy(slider))
                nodes = list(root.iter("node"))
                if change == "missing_parent":
                    nodes.remove(parent)
                elif change == "duplicate_parent":
                    nodes.append(parent)
                with self.assertRaisesRegex(RuntimeError, "uniquely locate"):
                    rive_slider_bounds(nodes)

    def test_unsupported_goal_values_cannot_inject_a_different_slider_value(self):
        for value in (0, 25, 49.9, 101):
            with self.subTest(value=value):
                probe = Mock()
                with self.assertRaises(ValueError):
                    set_rive_progress(probe, "101", value)
                probe.device.adb.assert_not_called()


class NativeSaveProbeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.output = Path(directory.name)
        self.save_directory = f"/storage/emulated/0/Android/data/{PACKAGE}/files/saves/app-starter"
        self.logs = (f"I/python (101): SDK_RUNNER_APP_SAVE_DIR path={self.save_directory} pid=101\n"
                     "I/python (202): SDK_RUNNER_APP_SAVE_DIR path=/data/user/0/other/files/saves pid=202")
        self.device = Mock(package=PACKAGE, output=self.output)
        self.device.logs.return_value = self.logs
        self.device.wait.side_effect = self.completed
        self.device.pid.return_value = "101"
        self.qemu, self.shell_uid, self.app_uid = "1", "2000", "10123"
        self.read_response = self.archive()
        self.read_responses = None
        self.read_handler = None
        self.device.adb.side_effect = self.adb
        self.restart = self.enterContext(patch(
            "scripts.check_project_capabilities.restart_emulator_adbd", side_effect=self.restart_reader))
        self.probe = CapabilitiesProbe(self.device)
        self.probe.pids = ["101"]

    def restart_reader(self, *, root):
        self.shell_uid = "0" if root else "2000"

    def adb(self, *args, **options):
        if args == ("shell", "getprop", "ro.kernel.qemu"):
            return self.qemu
        if args == ("shell", "id", "-u"):
            return self.shell_uid
        if args == ("shell", "ps", "-p", "101", "-o", "UID"):
            return "UID\n" + self.app_uid
        if args[0] == "exec-out":
            if self.read_handler:
                return self.read_handler(*args, **options)
            result = self.read_responses.pop(0) if self.read_responses is not None else self.read_response
            if isinstance(result, BaseException):
                raise result
            return result
        self.fail("Unexpected device command: " + repr(args))

    def read_calls(self):
        return [item for item in self.device.adb.call_args_list if item.args[0] == "exec-out"]

    @staticmethod
    def archive(game_data=b"saved native game data", *, phase="active"):
        content = io.BytesIO()
        metadata = {"app_story": {"version": 1, "story_id": "app-recipe", "phase": phase, "value": None}}
        with zipfile.ZipFile(content, "w") as saved:
            for name, data in (("json", json.dumps(metadata)), ("log", game_data),
                               ("signatures", b"native signature bytes"), ("renpy_version", b"8.5.3")):
                saved.writestr(name, data)
        return content.getvalue()

    @staticmethod
    def completed(callback, description, seconds=60):
        result = callback()
        if result is None or result is False:
            raise RuntimeError("Timed out waiting for " + description)
        return result

    def test_quick_and_mobile_read_exact_pinned_slot_filenames_for_the_current_pid(self):
        data = self.archive()
        self.read_response = data
        for slot in ("app-recipe-quick", "_reload-1"):
            with self.subTest(slot=slot):
                self.device.adb.reset_mock()
                self.restart.reset_mock()
                proof = self.probe.save_bytes("101", slot, slot)
                expected = self.save_directory + "/" + slot + "-LT1.save"
                backing = expected.replace("/storage/emulated/0/", "/data/media/0/", 1)
                self.assertEqual(self.read_calls(), [call("exec-out", "cat", backing, binary=True)])
                self.assertEqual(proof["path"], expected)
                self.assertEqual(proof["artifact"], slot + ".save")
                self.assertEqual((self.output / proof["artifact"]).read_bytes(), data)
                self.assertFalse(proof["unpickled"])
                self.assertEqual(proof["read_scope"], {
                    "method": "emulator_root_backing_file", "read_only": True, "emulator": True,
                    "temporary_adb_root": True, "package": PACKAGE, "slot": slot,
                    "path": expected, "read_path": backing, "app_pid": "101", "app_uid": 10123,
                    "shell_uid_before": 2000, "shell_uid_after": 2000, "same_app_pid": True, "same_app_uid": True})
                self.assertEqual(self.restart.call_args_list, [call(root=True), call(root=False)])

    def test_missing_partial_and_unchanged_archives_retry_until_new_native_data_is_complete(self):
        old, new = self.archive(b"old model"), self.archive(b"new model")
        path = f"/data/media/0/Android/data/{PACKAGE}/files/saves/app-starter/_reload-1-LT1.save"
        self.read_responses = [subprocess.CalledProcessError(1, ["cat", path]),
                               b"PK\x03\x04unfinished zip", old, new]

        def retry(callback, description, seconds):
            self.assertEqual(seconds, 45)
            self.assertEqual(description, "completed native _reload-1 save")
            for _ in range(3):
                self.assertIsNone(callback())
                self.assertFalse((self.output / "fresh-mobile.save").exists())
            return callback()

        self.device.wait.side_effect = retry
        proof = self.probe.save_bytes("101", "_reload-1", "fresh-mobile", previous_sha=digest(old))
        self.assertEqual(proof["sha256"], digest(new))
        self.assertEqual(proof["game_data_sha256"], digest(b"new model"))
        self.assertEqual((self.output / "fresh-mobile.save").read_bytes(), new)
        self.assertEqual(self.read_calls(), [call("exec-out", "cat", path, binary=True)] * 4)
        self.assertEqual(self.restart.call_args_list, [call(root=True), call(root=False)])
        self.assertEqual(self.shell_uid, "2000")

    def test_invalid_completed_native_archive_cannot_become_success_evidence(self):
        self.read_response = self.archive(phase="completed")

        def retry(callback, description, seconds):
            for _ in range(3):
                self.assertIsNone(callback())
            raise RuntimeError("Timed out waiting for " + description)

        self.device.wait.side_effect = retry
        with self.assertRaisesRegex(RuntimeError, "completed native app-recipe-quick save"):
            self.probe.save_bytes("101", "app-recipe-quick", "invalid-quick")
        self.assertEqual(len(self.read_calls()), 3)
        self.assertFalse((self.output / "invalid-quick.save").exists())
        self.assertEqual(self.restart.call_args_list, [call(root=True), call(root=False)])
        self.assertEqual(self.shell_uid, "2000")

    def test_quick_save_reads_its_logical_slot_after_the_native_saved_marker(self):
        self.device.adb.side_effect = None
        self.probe.cursor = Mock(return_value=42)
        self.probe.wait_native = Mock(return_value="SDK_RUNNER_SAVE action=saved pid=101")
        self.probe.tap = Mock()
        proof = save_archive(self.archive())

        def saved(pid, slot, name):
            self.probe.wait_native.assert_called_once_with("SDK_RUNNER_SAVE", "saved", "101", after=42)
            self.assertEqual(self.probe.tap.call_args_list, [call("Quick save", scroll="up")])
            self.assertEqual((pid, slot, name), ("101", "app-recipe-quick", "canvas-quick"))
            return proof

        self.probe.save_bytes = Mock(side_effect=saved)
        self.assertEqual(self.probe.quick_save("101", "canvas"), {
            "marker": "SDK_RUNNER_SAVE action=saved pid=101", **proof})
        self.assertEqual(self.probe.tap.call_args_list[-1], call("Resume", scroll="up"))

    def test_background_reads_previous_exact_mobile_path_before_home_and_waits_before_force_stop(self):
        for exists in (False, True):
            with self.subTest(previous_archive=exists):
                order = []
                previous = self.archive(b"previous recovery")
                expected_path = f"/data/media/0/Android/data/{PACKAGE}/files/saves/app-starter/_reload-1-LT1.save"
                self.device.pid.return_value = "101"

                def adb(*args, **options):
                    if args[0] == "exec-out":
                        self.assertEqual(args, ("exec-out", "cat", expected_path))
                        self.assertEqual(options, {"binary": True})
                        order.append("previous")
                        if not exists:
                            raise subprocess.CalledProcessError(1, list(args))
                        return previous
                    if args == ("shell", "input", "keyevent", "3"):
                        self.assertEqual(self.shell_uid, "2000")
                        order.append("home")
                    elif args == ("shell", "am", "force-stop", PACKAGE):
                        self.assertEqual(order, ["previous", "home", "archive"])
                        order.append("stop")
                        self.device.pid.return_value = None
                    else:
                        return self.adb(*args, **options)

                def saved(pid, slot, name, *, previous_sha):
                    self.assertEqual(order, ["previous", "home"])
                    self.assertEqual((pid, slot, name), ("101", "_reload-1", "rive-mobile"))
                    self.assertEqual(previous_sha, digest(previous) if exists else None)
                    order.append("archive")
                    return save_archive(self.archive(b"current recovery"))

                def start():
                    order.append("start")
                    self.device.pid.return_value = "202"
                    return "202"

                self.device.adb.side_effect = adb
                self.probe.save_bytes = Mock(side_effect=saved)
                self.probe.start = Mock(side_effect=start)
                self.probe.wait_native = Mock()
                self.probe.activity = Mock(return_value=state(202, 1, "restored"))
                pid, evidence = self.probe.background_reopen(state(), "rive")
                self.assertEqual(pid, "202")
                self.assertTrue(evidence["exact_model"])
                self.assertTrue(evidence["fresh_process"])
                self.assertEqual(order, ["previous", "home", "archive", "stop", "start"])
                self.assertEqual((self.output / "rive-source-logcat.txt").read_text(), self.logs)
                self.probe.wait_native.assert_called_once_with("SDK_RUNNER_SAVE", "loaded", "202")
                self.assertEqual(evidence["previous_mobile_read"]["sha256"], digest(previous) if exists else None)
                self.assertTrue(evidence["previous_mobile_read"]["read_scope"]["same_app_uid"])

    def test_physical_devices_are_refused_before_privilege_changes_or_reads(self):
        self.qemu = "0"
        with self.assertRaisesRegex(RuntimeError, "requires an emulator"):
            self.probe.save_bytes("101", "app-recipe-quick", "physical")
        self.device.adb.assert_called_once_with("shell", "getprop", "ro.kernel.qemu")
        self.restart.assert_not_called()
        self.assertFalse((self.output / "physical.save").exists())

    def test_reader_refuses_other_packages_slots_directories_and_forged_marker_pids(self):
        cases = (
            ("other.package", "_reload-1", self.save_directory, "101"),
            (PACKAGE, "renfletpy-quick", self.save_directory, "101"),
            (PACKAGE, "../app-recipe-quick", self.save_directory, "101"),
            (PACKAGE, "app-recipe-quick-LT1.save", self.save_directory, "101"),
            (PACKAGE, "_reload-1", self.save_directory.replace(PACKAGE, "other.package"), "101"),
            (PACKAGE, "_reload-1", self.save_directory.removesuffix("/app-starter"), "101"),
            (PACKAGE, "_reload-1", self.save_directory + "/../app-starter", "101"),
            (PACKAGE, "_reload-1", self.save_directory, "202"),
        )
        for package, slot, directory, log_pid in cases:
            with self.subTest(package=package, slot=slot, directory=directory, log_pid=log_pid):
                self.device.package = package
                self.device.logs.return_value = f"I/python ({log_pid}): SDK_RUNNER_APP_SAVE_DIR path={directory} pid=101"
                self.device.adb.reset_mock()
                with self.assertRaises(RuntimeError):
                    self.probe.save_bytes("101", slot, "confined")
                self.device.adb.assert_not_called()
                self.restart.assert_not_called()
                self.assertFalse((self.output / "confined.save").exists())

    def test_exact_internal_directories_use_app_run_as_without_root(self):
        for prefix in ("/data/data", "/data/user/0", "/data/user_de/0"):
            with self.subTest(prefix=prefix):
                directory = f"{prefix}/{PACKAGE}/files/saves/app-starter"
                self.device.logs.return_value = f"I/python (101): SDK_RUNNER_APP_SAVE_DIR path={directory} pid=101"
                self.device.adb.reset_mock()
                proof = self.probe.save_bytes("101", "_reload-1", "internal")
                self.assertEqual(self.read_calls(), [call(
                    "exec-out", "run-as", PACKAGE, "cat", directory + "/_reload-1-LT1.save", binary=True)])
                self.assertEqual(proof["read_scope"]["method"], "emulator_app_run_as")
                self.assertFalse(proof["read_scope"]["temporary_adb_root"])
                self.restart.assert_not_called()

    def test_reader_requires_the_existing_ordinary_app_and_shell_identities_before_root(self):
        for change, message in (("pid", "app PID"), ("app_uid", "ordinary app UID"), ("shell_uid", "shell UID 2000")):
            with self.subTest(change=change):
                self.device.pid.return_value = "202" if change == "pid" else "101"
                self.app_uid = "9999" if change == "app_uid" else "10123"
                self.shell_uid = "0" if change == "shell_uid" else "2000"
                with self.assertRaisesRegex(RuntimeError, message):
                    self.probe.save_bytes("101", "_reload-1", "identity")
                self.restart.assert_not_called()
                self.assertEqual(self.read_calls(), [])
                self.assertFalse((self.output / "identity.save").exists())

    def test_post_read_app_pid_or_uid_changes_unroot_and_prevent_publishing_evidence(self):
        for change, message in (("pid", "app PID"), ("uid", "app UID")):
            with self.subTest(change=change):
                self.device.pid.return_value = "101"
                self.app_uid = "10123"
                self.restart.reset_mock()

                def changed(*args, **options):
                    if change == "pid":
                        self.device.pid.return_value = "202"
                    else:
                        self.app_uid = "10124"
                    return self.archive()

                self.read_handler = changed
                with self.assertRaisesRegex(RuntimeError, message):
                    self.probe.save_bytes("101", "_reload-1", "changed")
                self.assertEqual(self.restart.call_args_list, [call(root=True), call(root=False)])
                self.assertEqual(self.shell_uid, "2000")
                self.assertFalse((self.output / "changed.save").exists())

    def test_root_setup_or_archive_wait_failures_always_restore_and_verify_shell(self):
        for failure in ("root", "wait"):
            with self.subTest(failure=failure):
                self.restart.reset_mock()

                def restart(*, root):
                    self.restart_reader(root=root)
                    if root and failure == "root":
                        raise RuntimeError("root setup failed")

                self.restart.side_effect = restart
                self.device.wait.side_effect = RuntimeError("archive wait failed")
                with self.assertRaisesRegex(RuntimeError, failure + ".*failed"):
                    self.probe.save_bytes("101", "_reload-1", "failed")
                self.assertEqual(self.restart.call_args_list, [call(root=True), call(root=False)])
                self.assertEqual(self.shell_uid, "2000")
                self.assertEqual(self.device.pid(), "101")
                self.assertEqual(self.app_uid, "10123")
                self.assertFalse((self.output / "failed.save").exists())

    def test_privilege_restoration_failure_cannot_publish_a_valid_archive(self):
        def unrestored(*, root):
            if root:
                self.shell_uid = "0"

        self.restart.side_effect = unrestored
        with self.assertRaisesRegex(RuntimeError, "left ADB privileged"):
            self.probe.save_bytes("101", "_reload-1", "privileged")
        self.assertEqual(self.restart.call_args_list, [call(root=True), call(root=False)])
        self.assertFalse((self.output / "privileged.save").exists())

    def test_shared_restart_protocol_accepts_lost_replies_without_repeating_actions(self):
        from scripts.device_smoke import restart_emulator_adbd

        def daemon(*args):
            if args in (("root",), ("unroot",)):
                self.restart_reader(root=args[0] == "root")
                raise subprocess.CalledProcessError(1, ["adb", *args], stderr="connection closed")
            return self.adb(*args)

        with patch("scripts.check_project_capabilities.restart_emulator_adbd", wraps=restart_emulator_adbd) as restart, patch(
                "scripts.device_smoke.adb", side_effect=daemon) as adb, patch("scripts.device_smoke.subprocess.run") as wait:
            proof = self.probe.save_bytes("101", "_reload-1", "lost-reply")
        self.assertEqual(restart.call_args_list, [call(root=True), call(root=False)])
        self.assertEqual([item for item in adb.call_args_list if item.args in (("root",), ("unroot",))],
                         [call("root"), call("unroot")])
        self.assertEqual(wait.call_args_list, [call(["adb", "wait-for-device"], check=True, timeout=60)] * 2)
        self.assertEqual(proof["read_scope"]["shell_uid_after"], 2000)


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
