"""Native observer must report real committed/closed state without consuming it."""

import contextlib
import importlib.util
import io
import json
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from runtime.renfletpy import Story
from runtime.story_activities import ActivityRegistry, ActivityResult, ActivityTransition


SOURCE = Path(__file__).resolve().parents[1] / "examples/capabilities/app/capabilities_observer.py"


class ObserverTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("observer_fixture", SOURCE)
        self.observer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.observer)
        catalog = ActivityRegistry()
        catalog.register("fixture", version=1, create_state=lambda: {"progress": 25},
                         renderer=lambda context: [], reduce=lambda state, name, value:
                         ActivityTransition({"progress": value}, ActivityResult("completed", {"progress": value})))
        self.story = Story(catalog)
        self.observer.story = self.story
        self.observer.sdk_bridge = SimpleNamespace(app_session=SimpleNamespace(status=lambda: {
            "revision": 1, "phase": "active", "resume_kind": "live", "showing_story": True, "result": None}))
        self.native = SimpleNamespace(config=SimpleNamespace(after_load_callbacks=[]))
        self.output = io.StringIO()
        self.capture = contextlib.redirect_stdout(self.output)
        self.capture.__enter__()
        self.addCleanup(lambda: self.capture.__exit__(None, None, None))
        self.observer.install(self.native)

    def events(self, marker):
        return [json.loads(line.split(" ", 1)[1]) for line in self.output.getvalue().splitlines()
                if line.startswith(marker + " ")]

    def test_menu_held_completion_is_not_reported_as_a_native_return(self):
        revision = self.story.start_activity("fixture")
        self.observer.tick()
        self.story.activity_command(revision, "finish", 100)
        self.story.process_activity_commands()
        self.observer.tick()
        self.assertEqual(self.events("SDK_CAP_ACTIVITY_RESULT"), [])
        result = self.story.consume(revision)
        self.assertEqual(result, ActivityResult("completed", {"progress": 100}))
        self.observer.tick()
        self.assertEqual(self.events("SDK_CAP_ACTIVITY_RESULT"), [])
        self.story.close(revision)
        self.observer.tick()
        self.observer.tick()
        self.assertEqual(len(self.events("SDK_CAP_ACTIVITY_RESULT")), 1)
        self.assertEqual(self.events("SDK_CAP_ACTIVITY_RESULT")[0]["result"], result.snapshot())

    def test_restore_reports_exact_plain_model_and_does_not_repeat_historical_results(self):
        revision = self.story.start_activity("fixture")
        self.story.activity_command(revision, "finish", 100)
        self.story.process_activity_commands()
        self.story.consume(revision)
        self.story.close(revision)
        self.story.start_activity("fixture", {"progress": 50})
        saved = self.story.snapshot()
        restored = self.story.restore(saved)
        self.native.config.after_load_callbacks[0]()
        self.observer.tick()
        events = self.events("SDK_CAP_ACTIVITY_STATE")
        self.assertEqual(events[-1]["phase"], "restored")
        self.assertEqual(events[-1]["revision"], restored)
        self.assertEqual(events[-1]["state"], {"progress": 50})
        self.assertEqual(self.events("SDK_CAP_ACTIVITY_RESULT"), [])
        self.assertEqual(self.story.current().activity["state"], {"progress": 50})

    def test_callbacks_are_native_owner_only_and_install_is_idempotent(self):
        self.observer.install(self.native)
        self.assertEqual(len(self.native.config.after_load_callbacks), 1)
        with ThreadPoolExecutor(max_workers=1) as worker:
            for callback in (self.observer.tick, self.observer.after_load):
                with self.assertRaises(RuntimeError):
                    worker.submit(callback).result(timeout=5)
        observer, = self.events("SDK_CAP_OBSERVER")
        self.assertEqual(observer["owner_thread"], threading.get_ident())
        self.assertRegex(observer["source_sha256"], r"^[0-9a-f]{64}$")
