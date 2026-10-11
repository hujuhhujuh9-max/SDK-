"""Retained activity lifetimes through the SDK's real page and route assembly."""

import importlib.util
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

