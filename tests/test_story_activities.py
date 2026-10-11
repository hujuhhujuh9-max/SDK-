"""Exercise registered activities across threads, reconstruction and process loss."""

import copy
import importlib.util
import json
import math
import os
import pickle
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.renfletpy import SaveState, Story
from runtime.story_activities import (
    ActivityContext, ActivityRegistry, ActivityRenderError, ActivityResult,
    ActivityTransition, plain_copy,
)


ROOT = Path(__file__).resolve().parents[1]
FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as prepared_flet
spec = importlib.util.spec_from_file_location("survey_activity", ROOT / "examples/activities/survey_activity.py")
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)


def registry():
    result = ActivityRegistry()
    survey.register(SimpleNamespace(register_activity=result.register))
    return result


class RegisteredActivityTests(unittest.TestCase):
    def setUp(self):
        self.registry = registry()
        self.story = Story(self.registry)
        self.revision = self.story.start_activity("field_survey")

    def command(self, name, payload=None):
        self.assertTrue(self.story.activity_command(self.story.current().revision, name, payload))
        self.story.process_activity_commands()

    def half_save(self):
        self.command("draft", "Checked the telescope mirror")
        self.command("record")
        self.command("select", "spectrograph")
        self.command("draft", "A spectral line still needs checking")
        return self.story.snapshot()

    def test_ui_submits_detached_commands_only_native_owner_runs_reducer(self):
        threads = []
        catalog = ActivityRegistry()

        def reduce(state, name, payload):
            threads.append(threading.get_ident())
            return {"value": state["value"] + payload["increment"]}

        catalog.register("counter", version=1, create_state=lambda: {"value": 0},
                         renderer=lambda context: [], reduce=reduce)
        story = Story(catalog)
        revision = story.start_activity("counter")
        payload = {"increment": 2}
        with ThreadPoolExecutor(max_workers=1) as worker:
            self.assertTrue(worker.submit(story.activity_command, revision, "add", payload).result())
            self.assertEqual(story.current().activity["state"], {"value": 0})
            with self.assertRaises(RuntimeError):
                worker.submit(story.process_activity_commands).result()
        payload["increment"] = 100
        self.assertEqual(story.process_activity_commands(), 1)
        self.assertEqual(story.current().activity["state"], {"value": 2})
        self.assertEqual(threads, [threading.get_ident()])

    def test_half_save_reconstructs_draft_selection_and_model_in_a_new_process(self):
        saved = self.half_save()
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "half-save.json"
            source.write_text(json.dumps(saved))
            program = '''import importlib.util, json, sys
from pathlib import Path
from types import SimpleNamespace
from runtime.renfletpy import Story
from runtime.story_activities import ActivityRegistry
spec = importlib.util.spec_from_file_location("survey_activity", "examples/activities/survey_activity.py")
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)
catalog = ActivityRegistry()
survey.register(SimpleNamespace(register_activity=catalog.register))
story = Story(catalog)
revision = story.restore(json.loads(Path(sys.argv[1]).read_text()))
restored = story.current().activity["state"]
story.activity_command(revision, "record")
story.activity_command(revision, "finish")
story.process_activity_commands()
result = story.consume(revision)
assert story.consume(revision) is None
print(json.dumps({"pid": __import__("os").getpid(), "restored": restored, "result": result.snapshot()}))
'''
            finished = subprocess.run([sys.executable, "-c", program, str(source)], cwd=ROOT,
                                      capture_output=True, text=True, timeout=15, check=True)
        receipt = json.loads(finished.stdout)
        self.assertNotEqual(receipt["pid"], os.getpid())
        self.assertEqual(receipt["restored"], saved["history"][-1]["activity"]["state"])
        self.assertEqual(receipt["result"], {"status": "completed", "value": {
            "samples": ["telescope", "spectrograph"], "notes": {
                "telescope": "Checked the telescope mirror", "spectrograph": "A spectral line still needs checking"}}})

    def test_context_and_current_copies_cannot_mutate_the_live_model(self):
        context = ActivityContext(self.story, self.revision, lambda path: None)
        context.state["draft"] = "Only a detached renderer copy"
        current = self.story.current()
        current.activity["state"]["samples"].append("lens")
        self.story.history()[-1].activity["state"]["draft"] = "History copy"
        self.assertEqual(self.story.current().activity["state"], survey.create_state())
        self.assertTrue(context.command("draft", "A real command"))
        self.story.process_activity_commands()
        self.assertEqual(self.story.current().activity["state"]["draft"], "A real command")

    def test_restore_rejects_delayed_controls_and_discards_uncommitted_future_commands(self):
        saved = self.half_save()
        old_context = ActivityContext(self.story, self.revision, lambda path: None)
        self.assertTrue(old_context.command("draft", "Uncommitted future text"))
        restored = self.story.restore(saved)
        self.assertGreater(restored, self.revision)
        self.assertFalse(old_context.command("draft", "Delayed old text"))
        self.assertFalse(old_context.complete({"samples": [], "notes": {}}))
        self.assertFalse(old_context.cancel())
        self.assertEqual(self.story.process_activity_commands(), 0)
        self.assertEqual(self.story.current().activity["state"], saved["history"][-1]["activity"]["state"])

    def test_explicit_cancel_is_consumed_once_and_other_terminal_events_cannot_win(self):
        context = ActivityContext(self.story, self.revision, lambda path: None)
        with ThreadPoolExecutor(max_workers=8) as worker:
            accepted = list(worker.map(lambda ignored: context.cancel({"reason": "later"}), range(64)))
        self.assertEqual(sum(accepted), 1)
        self.assertFalse(context.command("draft", "After cancellation"))
        self.assertIsNone(self.story.consume(self.revision))
        self.story.process_activity_commands()
        self.assertFalse(context.complete(None))
        result = self.story.consume(self.revision)
        self.assertEqual(result, ActivityResult("cancelled", {"reason": "later"}))
        self.assertIsNone(self.story.consume(self.revision))
        self.assertTrue(self.story.close(self.revision))
        self.assertIsNone(self.story.current())
        self.assertEqual(self.story.history()[-1].selected, "cancelled")

    def test_completion_from_reducer_is_one_result_and_stays_pending_through_save_load(self):
        self.half_save()
        self.command("record")
        self.command("finish")
        snapshot = self.story.snapshot()
        target = Story(registry())
        revision = target.restore(snapshot)
        with ThreadPoolExecutor(max_workers=1) as worker, self.assertRaises(RuntimeError):
            worker.submit(target.consume, revision).result()
        result = target.consume(revision)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.value["samples"], ["telescope", "spectrograph"])
        result.value["samples"].clear()
        self.assertEqual(target.current().activity["result"]["value"]["samples"], ["telescope", "spectrograph"])
        self.assertIsNone(target.consume(revision))

    def test_old_state_migrates_without_overwriting_the_input_save(self):
        saved = self.story.snapshot()
        old = {"version": 1, "state": {"found": ["lens"], "note": "Older unfinished note"}, "result": None}
        saved["history"][-1]["activity"] = copy.deepcopy(old)
        restored = self.story.restore(saved)
        self.assertGreater(restored, self.revision)
        self.assertEqual(self.story.current().activity, {"version": 2, "state": {
            "samples": ["lens"], "draft": "Older unfinished note", "selected": "telescope", "notes": {"lens": ""}},
            "result": None})
        self.assertEqual(saved["history"][-1]["activity"], old)

    def test_foreign_restore_cannot_execute_project_migrations_or_validators(self):
        callbacks = []
        catalog = ActivityRegistry()

        def migrate(state):
            callbacks.append(("migration", threading.get_ident()))
            return {"draft": state["note"]}

        def validate(state):
            callbacks.append(("validation", threading.get_ident()))
            return True

        catalog.register("owned", version=2, create_state=lambda: {"draft": "Current draft"},
                         renderer=lambda context: [], reduce=lambda state, name, payload: state,
                         migrations={1: migrate}, validate_state=validate)
        story = Story(catalog)
        story.start_activity("owned")
        saved = story.snapshot()
        saved["history"][-1]["activity"] = {
            "version": 1, "state": {"note": "Older draft"}, "result": None}
        current = story.current()
        callbacks.clear()
        with ThreadPoolExecutor(max_workers=1) as worker, self.assertRaises(RuntimeError):
            worker.submit(story.restore, saved).result()
        self.assertEqual(callbacks, [])
        self.assertEqual(story.current(), current)
        story.restore(saved)
        self.assertEqual(callbacks, [("migration", threading.get_ident()),
                                    ("validation", threading.get_ident())])
        self.assertEqual(story.current().activity["state"], {"draft": "Older draft"})

    def test_combined_state_result_limit_is_atomic_and_terminal_input_can_retry(self):
        for operation in ("command", "complete"):
            with self.subTest(operation=operation):
                catalog = ActivityRegistry()
                catalog.register(
                    "large", version=1, create_state=lambda: {"draft": "x" * 700000},
                    renderer=lambda context: [], reduce=lambda state, name, payload:
                    ActivityTransition(state, ActivityResult("completed", payload)))
                story = Story(catalog)
                revision = story.start_activity("large")
                state = story.current().activity["state"]
                result = {"report": "y" * 700000}
                submit = story.activity_command if operation == "command" else story.complete_activity
                arguments = (revision, "finish", result) if operation == "command" else (revision, result)
                self.assertTrue(submit(*arguments))
                with self.assertLogs(level="ERROR"):
                    self.assertEqual(story.process_activity_commands(), 1)
                self.assertEqual(story.current().activity["state"], state)
                self.assertIsNone(story.current().activity["result"])
                self.assertIsNone(story.consume(revision))
                self.assertIn("try again", story.current().feedback)
                self.assertEqual(story.snapshot()["history"][-1]["activity"]["state"], state)
                self.assertTrue(story.cancel_activity(revision, {"reason": "retry"}))
                story.process_activity_commands()
                self.assertEqual(story.consume(revision), ActivityResult("cancelled", {"reason": "retry"}))

    def test_oversized_restored_envelope_cannot_replace_a_valid_story(self):
        catalog = ActivityRegistry()
        catalog.register("large", version=1, create_state=lambda: {"draft": "x" * 700000},
                         renderer=lambda context: [], reduce=lambda state, name, payload: state)
        story = Story(catalog)
        story.start_activity("large")
        current = story.current()
        saved = story.snapshot()
        saved["history"][-1]["activity"]["result"] = {
            "status": "completed", "value": {"report": "y" * 700000}}
        saved["history"][-1]["selected"] = "completed"
        with self.assertRaisesRegex(ValueError, "1 MiB"):
            story.restore(saved)
        self.assertEqual(story.current(), current)

    def test_bad_future_unknown_and_malformed_result_saves_leave_live_data_intact(self):
        saved = self.half_save()
        variants = []
        for version in (0, True, 3):
            data = copy.deepcopy(saved)
            data["history"][-1]["activity"]["version"] = version
            variants.append(data)
        for result in ({"status": "unknown", "value": None}, {"status": "completed", "value": {}},
                       {"status": "cancelled"}, {"status": "cancelled", "value": {"bad": math.nan}}):
            data = copy.deepcopy(saved)
            data["history"][-1]["activity"]["result"] = result
            data["history"][-1]["selected"] = "completed" if result.get("status") == "completed" else "cancelled"
            variants.append(data)
        for field, value in (("activity", None), ("kind", "missing_project"), ("selected", "completed")):
            data = copy.deepcopy(saved)
            data["history"][-1][field] = value
            variants.append(data)
        current = self.story.current()
        for data in variants:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.story.restore(data)
            self.assertEqual(self.story.current(), current)

    def test_native_save_flushes_input_but_background_serializer_never_runs_reducers(self):
        self.assertTrue(self.story.activity_command(self.revision, "draft", "Queued observation"))
        adapter = SaveState()
        with patch("runtime.renfletpy.story", self.story), ThreadPoolExecutor(max_workers=1) as worker:
            saved = worker.submit(pickle.dumps, adapter).result(timeout=5)
            self.assertEqual(pickle.loads(saved).data["history"][-1]["activity"]["state"]["draft"], "")
            native_saved = pickle.dumps(adapter)
        self.assertEqual(pickle.loads(native_saved).data["history"][-1]["activity"]["state"]["draft"], "Queued observation")
        self.assertEqual(self.story.current().activity["state"]["draft"], "Queued observation")

    def test_failed_reducer_or_result_validation_keeps_model_and_can_be_retried(self):
        state = self.story.current().activity["state"]
        with self.assertLogs(level="ERROR"):
            self.command("finish")
        self.assertEqual(self.story.current().activity["state"], state)
        self.assertIn("try again", self.story.current().feedback)
        self.assertTrue(self.story.complete_activity(self.revision, {"bad": "result"}))
        with self.assertLogs(level="ERROR"):
            self.story.process_activity_commands()
        self.assertIsNone(self.story.consume(self.revision))
        self.assertTrue(self.story.cancel_activity(self.revision))
        self.story.process_activity_commands()
        self.assertEqual(self.story.consume(self.revision), ActivityResult("cancelled"))

    def test_mailbox_is_bounded_and_no_untrusted_live_data_can_enter_it(self):
        for _ in range(256):
            self.assertTrue(self.story.activity_command(self.revision, "draft", "bounded"))
        self.assertFalse(self.story.activity_command(self.revision, "draft", "overflow"))
        for payload in (threading.Lock(), lambda: None, {"number": math.inf}, {1: "bad key"}):
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.story.activity_command(self.revision, "draft", payload)
        self.assertEqual(self.story.process_activity_commands(), 256)

    def test_old_built_in_save_formats_still_restore_without_activity_fields(self):
        self.story.show("Journal", "Existing panel")
        panel = self.story.snapshot()
        for entry in panel["history"]:
            if entry["kind"] == "panel":
                del entry["activity"]
        target = Story(registry())
        revision = target.restore(panel)
        self.assertEqual(target.current().kind, "panel")
        self.assertTrue(target.choose(revision, "continue"))
        self.assertEqual(target.consume(revision), "continue")


class ActivityRegistrationTests(unittest.TestCase):
    def definition(self, catalog, name="test", **extra):
        options = {"version": 1, "create_state": lambda: {}, "renderer": lambda context: [],
                   "reduce": lambda state, name, payload: state}
        options.update(extra)
        return catalog.register(name, **options)

    def test_registration_is_explicit_and_cannot_shadow_builtin_types(self):
        catalog = ActivityRegistry()
        for name in ("panel", "star_map", "tactics", "", "bad/name"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.definition(catalog, name)
        self.definition(catalog)
        with self.assertRaises(ValueError):
            self.definition(catalog)
        with self.assertRaises(ValueError):
            Story(catalog).start_activity("unknown")

    def test_failed_project_hook_rolls_back_only_its_registrations(self):
        catalog = ActivityRegistry()
        existing = self.definition(catalog, "existing")
        with self.assertRaises(ValueError), catalog.transaction():
            self.definition(catalog, "partial")
            self.definition(catalog, "existing")
        self.assertFalse(catalog.contains("partial"))
        self.assertIs(catalog.get("existing"), existing)
        with catalog.transaction():
            self.definition(catalog, "partial")
        self.assertTrue(catalog.contains("partial"))

    def test_renderer_failures_are_separate_from_game_data_and_result(self):
        catalog = ActivityRegistry()
        self.definition(catalog, renderer=lambda context: object())
        story = Story(catalog)
        revision = story.start_activity("test")
        with self.assertRaises(ActivityRenderError):
            catalog.render(ActivityContext(story, revision, lambda path: None))
        self.assertEqual(story.current().activity["state"], {})
        self.assertIsNone(story.consume(revision))

    def test_missing_migration_and_invalid_factory_are_errors_not_silent_state_resets(self):
        catalog = ActivityRegistry()
        definition = self.definition(catalog, version=2)
        with self.assertRaises(ValueError):
            definition.restore({"version": 1, "state": {}, "result": None})
        async def renderer(context):
            return []
        with self.assertRaises(TypeError):
            self.definition(catalog, "async-renderer", renderer=renderer)
        with self.assertRaises(ValueError):
            self.definition(catalog, "bad-model", create_state=lambda: threading.Lock()).initial()

    def test_failing_reducer_mutation_cannot_leak_and_wrapped_async_callbacks_fail_clearly(self):
        catalog = ActivityRegistry()

        def failing(state, name, payload):
            state["draft"] = "Mutated before service failure"
            raise OSError("Service unavailable")

        self.definition(catalog, create_state=lambda: {"draft": "Saved draft"}, reduce=failing)
        story = Story(catalog)
        revision = story.start_activity("test")
        story.activity_command(revision, "edit", None)
        with self.assertLogs(level="ERROR"):
            story.process_activity_commands()
        self.assertEqual(story.current().activity["state"], {"draft": "Saved draft"})

        async def create():
            return {}
        definition = self.definition(catalog, "wrapped-async", create_state=lambda: create())
        with self.assertRaisesRegex(TypeError, "synchronously"):
            definition.initial()

    def test_plain_model_limits_reject_cycles_and_nonfinite_values(self):
        cycle = []
        cycle.append(cycle)
        for value in (cycle, {"bad": math.nan}, "x" * (1024 * 1024 + 1), {"tuple": (1, 2)}):
            with self.subTest(kind=type(value)), self.assertRaises(ValueError):
                plain_copy(value)


@unittest.skipUnless(FLET_AVAILABLE, "Run with prepared pinned Flet on PYTHONPATH")
class ActivityFletTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_controls_mutate_model_refresh_and_return_completion(self):
        # Earlier fake-page tests can retain their Flet stub in sys.modules via
        # nested patch contexts. This case always uses the captured pinned API.
        self.enterContext(patch.dict(sys.modules, {"flet": prepared_flet}))
        ft = prepared_flet
        catalog = registry()
        story = Story(catalog)
        revision = story.start_activity("field_survey")
        navigated = []
        async def navigate(path):
            navigated.append(path)

        view = catalog.render(ActivityContext(story, revision, navigate))
        controls = view.controls
        self.assertIsInstance(controls[0], ft.Container)
        column = controls[0].content
        draft = column.controls[3]
        draft.value = "Draft from a genuine Flet event"
        await draft.on_change(SimpleNamespace(control=draft))
        story.process_activity_commands()
        view.refresh(ActivityContext(story, revision, navigate))
        self.assertIs(column.controls[3], draft)
        self.assertEqual(draft.value, "Draft from a genuine Flet event")
        await column.controls[5].on_click(SimpleNamespace(control=column.controls[5]))
        story.process_activity_commands()
        await column.controls[2].controls[1].on_click(None)
        story.process_activity_commands()
        story.activity_command(revision, "record")
        story.process_activity_commands()
        view.refresh(ActivityContext(story, revision, navigate))
        finish = column.controls[8].controls[0]
        self.assertFalse(finish.disabled)
        await finish.on_click(None)
        story.process_activity_commands()
        self.assertEqual(story.consume(revision).status, "completed")
        await column.controls[0].controls[1].on_click(None)
        self.assertEqual(navigated, ["/menu"])
