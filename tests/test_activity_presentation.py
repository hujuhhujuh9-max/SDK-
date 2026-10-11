"""Retained activity lifetimes through the SDK's real page and route assembly."""

import asyncio
import importlib.util
import queue
import sys
import threading
from concurrent.futures import Future
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from runtime import app_session, sdk_bridge, story_ui
from runtime.renfletpy import Story, story
from runtime.story_activities import ActivityContext, ActivityRegistry, ActivityView
from test_app_starter_protocol import AppStarterPageCase, FLET_AVAILABLE

if FLET_AVAILABLE:
    import flet as ft
    from flet.controls.context import _context_page

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "sdk_presentation_survey", ROOT / "examples/activities/survey_activity.py")
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)


@unittest.skipUnless(FLET_AVAILABLE, "Requires prepared pinned Flet")
class ActivityPresentationTests(unittest.TestCase):
    def setUp(self):
        self.registry = ActivityRegistry()
        self.host = Story(self.registry)
        self.created = []
        self.refreshed = []
        self.disposed = []

        def renderer(context):
            field = ft.TextField(value=context.state["draft"])
            self.created.append(field)

            def refresh(current):
                self.refreshed.append(current)
                field.value = current.state["draft"]

            return ActivityView([field], refresh, lambda: self.disposed.append(field))

        self.registry.register("retained", version=1,
                               create_state=lambda: {"draft": "half"}, renderer=renderer,
                               reduce=lambda state, name, payload: {"draft": payload})
        self.host.start_activity("retained")
        self.presentation = story_ui.ActivityPresentation(self.host)
        self.navigate = lambda route: None
        self.addCleanup(self.presentation.dispose)

    def controls(self, **kwargs):
        return self.presentation.controls(self.navigate, self.host.current(), **kwargs)

    def test_entire_ancestry_is_retained_and_fresh_context_reaches_the_owned_registry(self):
        first = self.controls()
        self.host.activity_command(self.host.current().revision, "draft", "new draft")
        self.host.process_activity_commands()
        self.assertIs(self.controls(), first)
        self.assertIs(first[0].content.controls[-1], self.created[0])
        self.assertEqual(self.created[0].value, "new draft")
        self.assertIs(self.refreshed[-1].story, self.host)
        self.assertEqual(len(self.created), 1)
        self.assertEqual(self.disposed, [])

    def test_load_reading_change_and_story_removal_dispose_each_presentation_once(self):
        first = self.controls()
        snapshot = self.host.snapshot()
        self.host.restore(snapshot)
        second = self.controls()
        self.assertIsNot(second, first)
        third = self.controls(large_text=True)
        self.assertIsNot(third, second)
        self.host.close(self.host.current().revision)
        self.assertEqual(self.controls(), [])
        self.presentation.dispose()
        self.assertEqual(self.disposed, self.created)
        self.assertEqual(len(self.created), 3)
        self.assertEqual(snapshot["history"][-1]["activity"]["state"], {"draft": "half"})

    def test_legacy_list_renderer_rebuilds_without_acquiring_a_retained_lifetime(self):
        self.registry.register("legacy", version=1, create_state=lambda: {},
                               renderer=lambda context: [ft.Text("Legacy")],
                               reduce=lambda state, name, payload: state)
        self.host.start_activity("legacy")
        first = self.controls()
        self.assertIsNot(self.controls(), first)
        self.assertIsNone(self.presentation._view)

    def test_failed_assembly_cleans_up_the_new_presentation(self):
        def broken(navigate, dialogue, large_text, *, activity_renderer, activity_story):
            activity_renderer(ActivityContext(activity_story, dialogue.revision, navigate))
            raise ValueError("Assembly failed")

        with patch.object(story_ui, "dialogue_controls", broken), self.assertRaisesRegex(
                ValueError, "Assembly failed"):
            self.controls()
        self.assertEqual(self.disposed, self.created)
        self.assertIsNone(self.presentation._view)
        self.controls()
        self.assertEqual(len(self.created), 2)


@unittest.skipUnless(FLET_AVAILABLE, "Requires prepared pinned Flet")
class ActivityPageProtocolTests(AppStarterPageCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.registry = ActivityRegistry()
        survey.register(SimpleNamespace(register_activity=self.registry.register))
        self.enterContext(patch.object(story, "activities", self.registry))
        await self.open_page()
        await self.start_story()
        story.start_activity("field_survey")
        await self.settled()

    def field(self):
        return next(control for control in self.all_controls()
                    if isinstance(control, ft.TextField) and control.label == "Unfinished observation")

    def ancestry(self):
        root = self.page.views[0]
        frame = root.controls[0]
        wrapper = frame.content
        survey_frame = wrapper.controls[-1]
        return [root, frame, wrapper, survey_frame, survey_frame.content, self.field()]

    async def edit(self, value):
        field = self.field()
        # The client updates the control before dispatching TextField.onChange.
        field.value = value
        await self.transport.dispatch_event(field._i, "change", value)

    async def commit(self):
        self.assertGreater(story.process_activity_commands(), 0)
        await self.settled()

    async def test_typing_retains_every_ancestor_through_native_commits_and_menu(self):
        ancestry = self.ancestry()
        ids = [control._i for control in ancestry]
        for value in ("N", "Ni", "Night", "Night sky"):
            await self.edit(value)
            await self.commit()
            self.assertEqual(self.field().value, value)
            self.assertEqual(self.ancestry(), ancestry)
            self.assertEqual([control._i for control in self.ancestry()], ids)
        await self.click("Menu")
        self.assertEqual(self.page.route, "/menu")
        self.assertEqual(self.ancestry(), ancestry)
        await self.click("Resume")
        self.assertEqual(self.ancestry(), ancestry)
        self.assertEqual(story.current().activity["state"]["draft"], "Night sky")

    async def test_half_load_replaces_controls_and_old_callbacks_cannot_submit(self):
        await self.edit("halfway note")
        await self.commit()
        snapshot = story.snapshot()
        old = self.field()
        old_edit = old.on_change
        await self.edit("future note")
        await self.commit()
        story.restore(snapshot)
        await self.settled()
        self.assertNotEqual(self.field()._i, old._i)
        self.assertEqual(self.field().value, "halfway note")
        old.value = "late detached edit"
        await old_edit(SimpleNamespace(control=old))
        self.assertEqual(story.process_activity_commands(), 0)
        self.assertEqual(story.current().activity["state"]["draft"], "halfway note")

    async def test_return_reconstructs_from_model_and_disconnect_disposes_only_once(self):
        disposed = []
        definition = self.registry.get("field_survey")

        def render(context):
            view = survey.render(context)

            def dispose():
                disposed.append(context.revision)
                view.dispose()

            return ActivityView(view.controls, view.refresh, dispose)

        # Replace only this test's catalog before constructing its next activity.
        from dataclasses import replace
        self.registry._definitions["field_survey"] = replace(definition, renderer=render)
        story.start_activity("field_survey")
        await self.settled()
        await self.edit("returning draft")
        await self.commit()
        old_id = self.field()._i
        await self.click("Menu")
        await self.click("Return to app")
        command = app_session.session.take_request()
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(len(disposed), 1)
        await self.click("Resume story")
        command = app_session.session.take_request()
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertNotEqual(self.field()._i, old_id)
        self.assertEqual(self.field().value, "returning draft")
        await self.close_page()
        self.assertEqual(len(disposed), 2)

    async def test_story_canvas_gesture_survives_actual_sdk_parent_updates(self):
        from runtime.scale_activity import register_scale_activity
        register_scale_activity(SimpleNamespace(register_activity=self.registry.register))
        story.start_activity("scale_canvas")
        await self.settled()
        root = self.page.views[0]
        frame = root.controls[0]
        wrapper = frame.content
        gestures = next(control for control in self.all_controls() if isinstance(control, ft.GestureDetector))
        ids = [control._i for control in (root, frame, wrapper, gestures)]
        origin = SimpleNamespace(x=0, y=0)
        gestures.on_scale_start(SimpleNamespace())
        for scale, expected in ((2, 0.6), (3, 0.9), (4, 1.2)):
            gestures.on_scale_update(SimpleNamespace(
                scale=scale, local_focal_point=origin, focal_point_delta=origin))
            await self.commit()
            self.assertAlmostEqual(story.current().activity["state"]["camera"]["scale"], expected)
            self.assertIs(self.page.views[0].controls[0], frame)
            self.assertEqual([control._i for control in (root, frame, wrapper, gestures)], ids)
            self.assertIs(self.transport.index.get(gestures._i), gestures)

    async def test_explicit_reconnect_reconstructs_even_without_a_disconnect_callback(self):
        await self.edit("reconnected draft")
        await self.commit()
        old = self.field()
        await self.page.on_connect(SimpleNamespace())
        await self.settled()
        self.assertNotEqual(self.field()._i, old._i)
        self.assertEqual(self.field().value, "reconnected draft")
        old.value = "late old-session edit"
        await old.on_change(SimpleNamespace(control=old))
        self.assertEqual(story.process_activity_commands(), 0)


@unittest.skipUnless(FLET_AVAILABLE, "Requires prepared pinned Flet")
class NativeActivityPageContextTests(AppStarterPageCase):
    """A native owner thread has no inherited Flet page ContextVar."""

    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.ui_thread = threading.get_ident()
        self.calls = []
        self.created = []
        self.service_ids = []
        self.native_contexts = []
        self.reducer_threads = []
        self.callback_errors = []
        self.commands = queue.Queue()
        self.registry = ActivityRegistry()
        self.host = Story(self.registry)
        self.enterContext(patch.object(sdk_bridge, "story", self.host))
        self.enterContext(patch.object(story_ui, "story", self.host))
        self.enterContext(patch.dict(sys.modules, {"flet": ft}))

        def owner():
            while (request := self.commands.get()) is not None:
                future, callback = request
                try:
                    current_page = _context_page.get()
                    self.native_contexts.append((threading.get_ident(), current_page))
                    self.assertIsNone(current_page)
                    self.assertNotEqual(threading.get_ident(), self.ui_thread)
                    result = callback()
                except BaseException as error:
                    future.set_exception(error)
                else:
                    future.set_result(result)

        # asyncio.to_thread copies the caller's ContextVars and would mask this
        # regression. A normal dedicated thread owns every native operation.
        self.native_thread = threading.Thread(target=owner, name="native-story-context-probe")
        self.native_thread.start()
        loop = asyncio.get_running_loop()
        previous_handler = loop.get_exception_handler()
        loop.set_exception_handler(lambda loop, error: self.callback_errors.append(error))
        self.addCleanup(loop.set_exception_handler, previous_handler)
        test = self

        class ContextService(ft.HapticFeedback):
            def did_mount(self):
                test.observe("service_mount")

            def will_unmount(self):
                test.observe("service_unmount")

        def renderer(context):
            self.observe("render", context.revision)
            # Service construction actually registers it on ft.context.page.
            service = ContextService()
            self.service_ids.append(service._i)
            self.assertIs(self.transport.index[service._i], service)
            field = ft.TextField(value=context.state["draft"], label="Native context draft")
            self.created.append(field)
            current = context

            async def edit(event):
                current.command("draft", event.control.value)

            def refresh(updated):
                nonlocal current
                self.observe("refresh", updated.revision)
                current = updated
                field.value = current.state["draft"]
                self.assertIs(field.page, ft.context.page)
                self.assertIs(service.page, ft.context.page)
                field.update()
                service.update()

            def dispose():
                self.observe("dispose", current.revision)
                self.assertIs(field.page, ft.context.page)
                self.assertIs(service.page, ft.context.page)
                field.update()
                service.update()

            field.on_change = edit
            return ActivityView([field], refresh, dispose)

        def reducer(state, name, payload):
            self.assertEqual(name, "draft")
            self.assertIsNone(_context_page.get())
            self.reducer_threads.append(threading.get_ident())
            return {"draft": payload}

        self.registry.register("native_context_probe", version=1,
                               create_state=lambda: {"draft": "half"}, renderer=renderer, reduce=reducer)
        await self.open_page()
        self.context_page = self.page
        original_error = self.transport.error

        def session_failed(message):
            self.callback_errors.append({"message": message})
            original_error(message)

        self.enterContext(patch.object(self.transport, "error", session_failed))

    async def asyncTearDown(self):
        try:
            await super().asyncTearDown()
        finally:
            self.commands.put(None)
            self.native_thread.join(timeout=5)
            self.assertFalse(self.native_thread.is_alive(), "Native test owner did not stop")

    def observe(self, phase, revision=None):
        # Session.close dispatches final service cleanup after close_page clears
        # its convenience attribute; the session's actual page remains bound.
        self.assertIs(ft.context.page, self.context_page)
        self.assertEqual(threading.get_ident(), self.ui_thread)
        self.calls.append((phase, revision))

    async def native(self, callback):
        future = Future()
        self.commands.put((future, callback))
        result = await asyncio.wait_for(asyncio.wrap_future(future), timeout=5)
        await self.settled()
        self.assertEqual(self.callback_errors, [], "Native-origin UI callback failed")
        return result

    async def start_native_activity(self):
        await self.click("Start story")
        command = await self.native(app_session.session.take_request)
        self.assertEqual(command["action"], "start")
        self.assertTrue(await self.native(lambda: app_session.session.finish(command["command_id"])))
        self.assertEqual(self.page.route, "/")
        revision = await self.native(lambda: self.host.start_activity("native_context_probe"))
        self.assertEqual(len(self.created), 1)
        self.assertIn(("render", revision), self.calls)
        self.assertIn(("service_mount", None), self.calls)
        return revision

    async def type_draft(self, value):
        field = self.created[-1]
        self.transport.apply_patch(field._i, {"value": value})
        await self.transport.dispatch_event(field._i, "change", value)
        self.assertEqual(await self.native(self.host.process_activity_commands), 1)
        return field

    async def test_native_start_commit_restore_and_close_keep_real_page_and_native_ownership(self):
        revision = await self.start_native_activity()
        field = self.created[0]
        ancestry = self.page.views[0].controls
        await self.type_draft("saved on the native owner")
        self.assertEqual(self.created, [field])
        self.assertIs(self.page.views[0].controls, ancestry)
        self.assertEqual(field.value, "saved on the native owner")
        self.assertIn(("refresh", revision), self.calls)
        self.assertEqual(self.reducer_threads, [self.native_thread.ident])
        with self.assertRaisesRegex(RuntimeError, "owner thread"):
            self.host.process_activity_commands()
        saved = await self.native(self.host.snapshot)
        self.assertEqual(saved["history"][-1]["activity"]["state"], {"draft": "saved on the native owner"})
        restored_revision = await self.native(lambda: self.host.restore(saved))
        restored = self.created[-1]
        self.assertNotEqual(restored._i, field._i)
        self.assertEqual(restored.value, "saved on the native owner")
        self.assertIn(("dispose", revision), self.calls)
        self.assertIn(("render", restored_revision), self.calls)
        self.assertNotIn(field._i, self.transport.index)
        await self.native(lambda: self.host.close(restored_revision))
        self.assertIn(("dispose", restored_revision), self.calls)
        self.assertNotIn(restored._i, self.transport.index)
        self.assertEqual(len([phase for phase, _ in self.calls if phase == "dispose"]), 2)
        self.assertTrue(all(thread == self.native_thread.ident and page is None
                            for thread, page in self.native_contexts))
        await self.close_page()
        await self.settled()
        self.assertEqual(self.callback_errors, [])

    async def test_native_reading_and_app_return_refresh_and_dispose_with_the_real_page(self):
        revision = await self.start_native_activity()
        first = self.created[0]
        await self.native(lambda: sdk_bridge.update_reading_status(True, "instant", "Native reading preference"))
        self.assertEqual(len(self.created), 2)
        self.assertNotEqual(self.created[-1]._i, first._i)
        self.assertIn(("dispose", revision), self.calls)
        self.assertEqual(self.host.current().revision, revision)
        await self.native(sdk_bridge.open_menu)
        self.assertEqual(self.page.route, "/menu")
        await self.type_draft("draft while the native menu is open")
        await self.click("Return to app")
        command = await self.native(app_session.session.take_request)
        self.assertEqual(command["action"], "return")
        self.assertTrue(await self.native(lambda: app_session.session.finish(command["command_id"])))
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(len([phase for phase, _ in self.calls if phase == "dispose"]), 2)
        await self.click("Resume story")
        command = await self.native(app_session.session.take_request)
        self.assertEqual(command["action"], "resume")
        self.assertTrue(await self.native(lambda: app_session.session.finish(command["command_id"])))
        self.assertEqual(self.page.route, "/")
        self.assertEqual(len(self.created), 3)
        self.assertEqual(self.created[-1].value, "draft while the native menu is open")
        await self.close_page()
        await self.settled()
        self.assertEqual(len([phase for phase, _ in self.calls if phase == "dispose"]), 3)
        self.assertEqual(self.callback_errors, [])
        self.assertTrue(all(thread == self.native_thread.ident and page is None
                            for thread, page in self.native_contexts))

