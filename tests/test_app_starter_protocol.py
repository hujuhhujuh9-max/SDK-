"""Independent real-protocol acceptance for the optional app/story boundary."""

import asyncio
import importlib.util
import sys
import types
import unittest
from unittest import mock

from runtime import app_session, sdk_bridge
from runtime.renfletpy import story

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as ft
    from flet.controls.base_control import BaseControl
    from flet.controls.context import _context_page
    from flet.messaging.session import Session
    from test_form_list_flet import PreferencesConnection


class AppStarterPageCase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mode = mock.patch.dict(sys.modules, {
            "runtime.project_config": types.SimpleNamespace(STARTUP_TEMPLATE="app")})
        self.mode.start()
        story.reset()
        sdk_bridge._quitting.clear()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        app_session.session.restore(phase="ready", resume_kind="unavailable", showing_story=False)
        self.values = {}
        self.page = None

    async def asyncTearDown(self):
        await self.close_page()
        app_session.session.restore(phase="ready", resume_kind="unavailable", showing_story=False)
        story.reset()
        self.mode.stop()

    def prepare_page(self, route):
        self.connection = PreferencesConnection(self.values)
        self.transport = Session(self.connection)
        self.connection.session = self.transport
        self.page = self.transport.page
        self.page.route = route
        self.token = _context_page.set(self.page)
        self.connection.encode(self.transport.get_page_patch())
        self.page.push_route = self.navigate

    async def open_page(self, route="/app"):
        self.prepare_page(route)
        await sdk_bridge._page(self.page)

    async def close_page(self):
        if self.page is not None:
            await self.page.on_close(None)
            self.transport.close()
            _context_page.reset(self.token)
            self.page = None
            await asyncio.sleep(0)

    async def navigate(self, route):
        self.page.route = route
        await self.page.on_route_change(types.SimpleNamespace(route=route))

    async def settled(self):
        for _ in range(12):
            await asyncio.sleep(0)

    def all_controls(self):
        seen = set()

        def visit(value):
            if isinstance(value, BaseControl):
                if id(value) in seen:
                    return
                seen.add(id(value))
                yield value
                for child in vars(value).values():
                    yield from visit(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    yield from visit(child)
            elif isinstance(value, dict):
                for child in value.values():
                    yield from visit(child)
        return list(visit(self.page.views))

    def button(self, label):
        for control in self.all_controls():
            if isinstance(control, (ft.Button, ft.TextButton)):
                content = control.content
                if content == label or getattr(content, "value", None) == label:
                    return control
        self.fail("Missing visible button: " + label)

    def visible_text(self):
        return [control.value for control in self.all_controls() if isinstance(control, ft.Text)]

    async def click(self, label):
        await self.transport.dispatch_event(self.button(label)._i, "click", None)
        await self.settled()

    async def start_story(self):
        await self.click("Start story")
        command = app_session.session.take_request()
        self.assertIsNotNone(command)
        self.assertEqual(command["action"], "start")
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        return app_session.session.status()["revision"]

    async def add_record(self, title):
        fields = self.page.views[-1].controls[0].controls
        fields[1].value = title
        await self.transport.dispatch_event(fields[3].controls[0]._i, "click", None)
        self.assertEqual(fields[-2].value, "Record saved")


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class AppStarterProtocolTests(AppStarterPageCase):
    async def test_real_start_click_is_consumed_once_and_acknowledged_before_navigation(self):
        await self.open_page()
        revision = app_session.session.status()["revision"]
        await self.click("Start story")
        self.assertEqual(self.page.route, "/app")
        self.assertTrue(app_session.session.status()["busy"])
        self.assertFalse(sdk_bridge.request_app_story("start", revision))
        command = app_session.session.take_request()
        self.assertIsNone(app_session.session.take_request())
        self.assertEqual(command["story_id"], "app-recipe")
        self.assertTrue(app_session.session.finish(command["command_id"]))
        self.assertFalse(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/")
        self.assertEqual(app_session.session.status()["phase"], "active")

    async def test_late_start_acknowledgement_cannot_replace_a_new_records_route(self):
        await self.open_page()
        await self.click("Start story")
        command = app_session.session.take_request()
        await self.navigate("/app/records?source=newer")
        view = self.page.views[-1]
        view.controls[0].controls[1].value = "Unsubmitted draft"
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/app/records?source=newer")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(view.controls[0].controls[1].value, "Unsubmitted draft")

    async def test_restore_rejects_old_native_acknowledgement_and_old_completion(self):
        await self.open_page()
        await self.click("Start story")
        command = app_session.session.take_request()
        old = command["revision"]
        new = app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        self.assertGreater(new, old)
        self.assertFalse(app_session.session.finish(command["command_id"]))
        self.assertFalse(app_session.session.complete(old, {"choice": "stale"}))
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertIsNone(app_session.session.status()["result"])

    async def test_completion_waits_for_native_save_and_is_consumed_once(self):
        await self.open_page()
        revision = await self.start_story()
        self.assertTrue(sdk_bridge.request_save("save"))
        result = "You kept a note from the lighthouse."
        self.assertFalse(app_session.session.complete(revision, result))
        sdk_bridge.take_save_request()
        sdk_bridge.update_save_status(True, "Saved.")
        self.assertTrue(app_session.session.complete(revision, result))
        self.assertFalse(app_session.session.complete(revision, {"choice": "duplicate"}))
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(app_session.session.status()["phase"], "completed")
        self.assertIn("Story complete", self.visible_text())
        self.assertIn(result, self.visible_text())

    async def test_return_and_resume_wait_for_native_acknowledgement_with_a_pending_choice(self):
        await self.open_page()
        await self.start_story()
        story.show("The folded note", "Choose", (("keep", "Keep a copy"),))
        revision = story.current().revision
        await self.settled()
        await self.click("Menu")
        await self.click("Return to app")
        self.assertEqual(self.page.route, "/menu")
        command = app_session.session.take_request()
        self.assertEqual(command["action"], "return")
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(story.current().revision, revision)
        self.assertIsNone(story.current().selected)
        await self.click("Resume story")
        self.assertEqual(self.page.route, "/app")
        command = app_session.session.take_request()
        self.assertEqual(command["action"], "resume")
        self.assertFalse(app_session.session.status()["showing_story"])
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/")
        self.assertEqual(story.current().revision, revision)
        await self.click("Keep a copy")
        self.assertEqual(story.consume(revision), "keep")

    async def test_unknown_app_link_cannot_expose_a_returned_story_choice(self):
        await self.open_page()
        app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        story.show("The folded note", "Choose", (("keep", "Keep a copy"),))
        await self.settled()
        await self.navigate("/app/missing?probe=hidden")
        self.assertEqual(self.page.route, "/app")
        self.assertIn("App home", self.visible_text())
        self.assertNotIn("Choose", self.visible_text())
        self.assertIsNone(story.current().selected)
        self.assertIsNone(app_session.session.take_request())
