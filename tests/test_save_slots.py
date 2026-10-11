"""Native save isolation and stale/destructive command regression checks."""

import copy
import re
import threading
import unittest
from unittest.mock import Mock

from runtime import sdk_bridge
from runtime.save_slots import NativeSaveSlots, named_slot, save_name


class NativeFixture:
    def __init__(self):
        self.files = {name: {"_save_name": name, "mtime": 1} for name in
                      ("renfletpy-quick", "auto-1", "_reload-1", "1-1")}
        self.deleted = []
        self.saved = []
        self.take_screenshot = Mock()
        self.load = Mock()
        self.clock = 10

    def list_slots(self, pattern):
        return [name for name in self.files if re.match(pattern, name)]

    def slot_json(self, name):
        return copy.deepcopy(self.files.get(name))

    def slot_mtime(self, name):
        return self.files[name]["mtime"] if name in self.files else None

    def can_load(self, name):
        return name in self.files

    def save(self, slot, *, extra_info, extra_json=None):
        self.clock += 1
        self.files[slot] = {"_save_name": extra_info, "mtime": self.clock, **(extra_json or {})}
        self.saved.append(slot)

    def unlink_save(self, slot):
        self.deleted.append(slot)
        self.files.pop(slot, None)


class NamedSaveTests(unittest.TestCase):
    def setUp(self):
        self.renpy = NativeFixture()
        self.library = NativeSaveSlots(self.renpy)
        self.bridge = Mock()
        self.token = object()
        self.bridge.begin_save_load.return_value = self.token
        self.original = copy.deepcopy(self.renpy.files)

    def run_command(self, command):
        self.library.run(self.bridge, command, "The lighthouse", "renfletpy-quick")

    def create(self, name="Chapter one"):
        self.run_command({"action": "create", "name": name})
        return next(row for row in self.library.catalog() if row["slot"] == self.renpy.saved[-1])

    def command(self, action, row):
        return {"action": action, "slot": row["slot"], "expected": row["fingerprint"]}

    def test_multiple_named_native_files_keep_quick_autosave_and_recovery_untouched(self):
        first = self.create("Before the choice")
        second = self.create("After the choice")
        self.assertNotEqual(first["slot"], second["slot"])
        self.assertTrue(all(named_slot(row["slot"]) for row in self.library.catalog()))
        self.assertEqual([row["name"] for row in self.library.catalog()],
                         ["After the choice", "Before the choice"])
        for slot, contents in self.original.items():
            self.assertEqual(self.renpy.files[slot], contents)
        self.run_command(self.command("overwrite", first))
        self.assertEqual(len(self.library.catalog()), 2)
        self.assertEqual(self.renpy.files[first["slot"]]["_save_name"], "Before the choice")
        updated = next(row for row in self.library.catalog() if row["slot"] == first["slot"])
        self.run_command(self.command("delete", updated))
        self.assertEqual([row["slot"] for row in self.library.catalog()], [second["slot"]])
        self.assertEqual(self.renpy.deleted, [first["slot"]])

    def test_changed_native_save_rejects_old_load_overwrite_and_delete(self):
        row = self.create()
        self.renpy.files[row["slot"]]["mtime"] += 1
        changed = copy.deepcopy(self.renpy.files)
        for action in ("load", "overwrite", "delete"):
            self.run_command(self.command(action, row))
            self.assertIn("That save changed", self.bridge.update_save_status.call_args.args[1])
            self.assertEqual(self.renpy.files, changed)
        self.renpy.load.assert_not_called()

    def test_declined_native_signature_prompt_releases_only_its_load_owner(self):
        row = self.create()
        self.run_command(self.command("load", row))
        self.renpy.load.assert_called_once_with(row["slot"])
        self.bridge.end_save_load.assert_called_once_with(self.token)
        self.assertEqual(self.bridge.update_save_status.call_args.args, (True, "Load cancelled."))

    def test_successful_nonreturning_load_releases_native_input_without_fake_success(self):
        class Loaded(BaseException):
            pass
        row = self.create()
        self.bridge.reset_mock()
        self.renpy.load.side_effect = Loaded
        with self.assertRaises(Loaded):
            self.run_command(self.command("load", row))
        self.bridge.end_save_load.assert_called_once_with(self.token)
        self.bridge.update_save_status.assert_not_called()

    def test_failed_native_save_keeps_original_files_and_releases_busy_state(self):
        row = self.create()
        before = copy.deepcopy(self.renpy.files)
        self.renpy.save = Mock(side_effect=OSError("fixture write failure"))
        with self.assertLogs(level="ERROR"):
            self.run_command(self.command("overwrite", row))
        self.assertEqual(before, self.renpy.files)
        self.assertIn("Could not overwrite", self.bridge.update_save_status.call_args.args[1])

    def test_native_worker_is_rejected_and_names_never_select_paths(self):
        self.assertEqual(save_name("  Mira’s lighthouse  "), "Mira’s lighthouse")
        for name in ("", "x" * 81, "a\nb", None):
            with self.assertRaises(ValueError):
                save_name(name)
        for slot in ("renfletpy-quick", "_reload-1", "../save", "renfletpy-manual-" + "a" * 32 + "/x"):
            self.assertFalse(named_slot(slot))
        failures = []
        def worker():
            try:
                self.library.catalog()
            except RuntimeError as error:
                failures.append(str(error))
        thread = threading.Thread(target=worker)
        thread.start()
        thread.join()
        self.assertEqual(failures, ["Save operations belong to Ren'Py's thread"])


class NamedSaveBridgeTests(unittest.TestCase):
    def setUp(self):
        sdk_bridge._quitting.clear()
        sdk_bridge._stopping.clear()
        sdk_bridge.update_reading_status(False, "instant", "Ready")
        sdk_bridge.update_save_status(False, "Ready")
        sdk_bridge.app_session.restore(phase="active", resume_kind="live", showing_story=True)
        self.row = {"slot": "renfletpy-manual-" + "a" * 32, "name": "First",
                    "fingerprint": "a" * 64, "mtime": 1, "scene": "Opening", "loadable": True}
        sdk_bridge.publish_save_slots((self.row,))
        self.revision = sdk_bridge.save_browser_status()["revision"]

    def tearDown(self):
        sdk_bridge.update_save_status(False, "Ready")
        sdk_bridge.app_session.restore(phase="ready", resume_kind="unavailable", showing_story=False)

    def test_named_commands_bind_current_catalog_and_are_consumed_once(self):
        self.assertFalse(sdk_bridge.request_save("delete", slot=self.row["slot"], revision=self.revision - 1))
        self.assertTrue(sdk_bridge.request_save("load", slot=self.row["slot"], revision=self.revision))
        self.assertFalse(sdk_bridge.request_save("save"))
        self.assertEqual(sdk_bridge.take_save_request(), {"action": "load", "slot": self.row["slot"],
                                                        "expected": self.row["fingerprint"]})
        self.assertIsNone(sdk_bridge.take_save_request())
        self.assertTrue(sdk_bridge.mark_save_restored())
        sdk_bridge.update_save_status(False, "Loaded")
        self.assertTrue(sdk_bridge.manual_save_restored())
        self.assertFalse(sdk_bridge.mark_save_restored())

    def test_reserved_and_arbitrary_slots_cannot_be_deleted_or_overwritten(self):
        for slot in ("auto-1", "_reload-1", "renfletpy-quick", "app-recipe-quick", "../save"):
            for action in ("delete", "overwrite", "load"):
                with self.assertRaises(ValueError):
                    sdk_bridge.request_save(action, slot=slot, revision=self.revision)
        with self.assertRaises(ValueError):
            sdk_bridge.request_save("delete")
        self.assertFalse(sdk_bridge.save_status()["busy"])

    def test_catalog_snapshots_and_commands_do_not_share_mutable_rows(self):
        snapshot = sdk_bridge.save_browser_status()
        snapshot["slots"][0]["name"] = "Changed elsewhere"
        self.row["fingerprint"] = "b" * 64
        self.assertEqual(sdk_bridge.save_browser_status()["slots"][0]["name"], "First")
        self.assertEqual(sdk_bridge.save_browser_status()["slots"][0]["fingerprint"], "a" * 64)


if __name__ == "__main__":
    unittest.main()
