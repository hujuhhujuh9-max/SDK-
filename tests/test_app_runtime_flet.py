"""Verify optional app routing against the pinned Flet event/method protocol."""

import asyncio
import importlib.util
import json
import threading
import types
import unittest
from unittest.mock import AsyncMock

from runtime import sdk_bridge
from runtime.application_data import DEFAULT_STORAGE_KEY
from runtime.renfletpy import story

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    from flet.controls.context import _context_page
    from flet.messaging.session import Session
    from test_form_list_flet import PreferencesConnection


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class AppRuntimeFletTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        story.reset()
        sdk_bridge._quitting.clear()
        sdk_bridge.restore_story_status()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        self.connection = PreferencesConnection()
        self.session = Session(self.connection)
        self.connection.session = self.session
        self.page = self.session.page
        self.token = _context_page.set(self.page)
        self.connection.encode(self.session.get_page_patch())
        self.page.push_route = AsyncMock(side_effect=self.navigate)

    async def asyncTearDown(self):
        await self.page.on_close(None)
        self.session.close()
        _context_page.reset(self.token)
        sdk_bridge.restore_story_status()
        story.reset()
        await asyncio.sleep(0)

    async def open_page(self, route="/app/story"):
        self.page.route = route
        await sdk_bridge._page(self.page)

    async def navigate(self, route):
        self.page.route = route
        await self.page.on_route_change(types.SimpleNamespace(route=route))

    async def drain(self):
        for _ in range(5):
            await asyncio.sleep(0)

    async def click(self, control):
        await self.session.dispatch_event(control._i, "click", None)

    def story_button(self):
        return self.page.views[-1].controls[0].controls[-1]

    def confirm_on_native_thread(self, command):
        replies = []
        worker = threading.Thread(target=lambda: replies.append(sdk_bridge.confirm_story_command(
            command["request_id"], success=True, message="Native operation confirmed.")))
        worker.start()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(replies, [True])

    async def test_actual_start_event_and_native_confirmation_change_route_once(self):
        await self.open_page()
        button = self.story_button()
        await self.click(button)
        await self.click(button)
        await self.drain()
        self.assertTrue(self.story_button().disabled)
        self.assertEqual(sdk_bridge.story_status()["state"], "idle")
        self.page.push_route.assert_not_awaited()
        command = sdk_bridge.take_story_command()
        self.assertEqual(command["action"], "start")
        self.assertIsNone(sdk_bridge.take_story_command())
        patches = len(self.connection.patches)
        self.confirm_on_native_thread(command)
        self.assertEqual(len(self.connection.patches), patches)
        await self.drain()
        self.page.push_route.assert_awaited_once_with("/")
        self.assertEqual(self.page.route, "/")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertFalse(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        await self.drain()
        self.page.push_route.assert_awaited_once()

    async def test_back_return_and_resume_preserve_the_native_session_and_app_parent(self):
        await self.open_page("/app?workspace=1")
        await self.navigate("/app/story")
        await self.click(self.story_button())
        start = sdk_bridge.take_story_command()
        self.confirm_on_native_thread(start)
        await self.drain()
        self.assertEqual(self.page.route, "/")
        await self.page.on_view_pop(None)
        self.assertEqual(self.page.route, "/")
        returned = sdk_bridge.take_story_command()
        self.assertEqual(returned["action"], "return")
        self.confirm_on_native_thread(returned)
        await self.drain()
        self.assertEqual(self.page.route, "/app?workspace=1")
        self.assertEqual(sdk_bridge.story_status()["state"], "suspended")
        await self.navigate("/app/story")
        self.assertEqual(self.story_button().content, "Resume story")
        await self.click(self.story_button())
        resumed = sdk_bridge.take_story_command()
        self.assertEqual(resumed["action"], "resume")
        self.assertEqual(resumed["session_id"], start["session_id"])
        self.confirm_on_native_thread(resumed)
        await self.drain()
        self.assertEqual(self.page.route, "/")
        self.assertEqual(sdk_bridge.story_status()["session_id"], start["session_id"])

    async def test_late_confirmation_and_recovery_keep_real_records_and_unsubmitted_edits(self):
        revision = story.show("Mira", "Pending choice", (("sky", "Sky"),))
        await self.open_page()
        await self.click(self.story_button())
        command = sdk_bridge.take_story_command()
        await self.navigate("/app/records?edit=1")
        view = self.page.views[-1]
        fields = view.controls[0].controls
        fields[1].value = "Independent app record"
        await self.click(fields[3].controls[0])
        saved_data = self.connection.values[DEFAULT_STORAGE_KEY]
        fields[1].value = "Unsubmitted draft"
        service = self.page._runner_application_data["preferences"]
        self.confirm_on_native_thread(command)
        await self.drain()
        sdk_bridge.restore_story_status("before-the-first-light", state="suspended")
        sdk_bridge.resume_story()
        await self.drain()
        self.assertEqual(self.page.route, "/app/records?edit=1")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(fields[1].value, "Unsubmitted draft")
        self.assertEqual(self.connection.values[DEFAULT_STORAGE_KEY], saved_data)
        self.assertEqual(json.loads(saved_data)["records"][0]["values"]["title"], "Independent app record")
        self.assertEqual([item._i for item in self.page._services._services], [service._i])
        self.assertEqual(story.current().revision, revision)
        self.assertIsNone(story.consume(revision))
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.page.push_route.assert_not_awaited()

    async def test_disconnect_native_completion_and_reconnect_reconcile_without_navigation(self):
        await self.open_page("/app/story?resume=1")
        await self.click(self.story_button())
        command = sdk_bridge.take_story_command()
        await self.page.on_disconnect(None)
        self.confirm_on_native_thread(command)
        await self.page.on_connect(object())
        await self.drain()
        self.assertEqual(self.page.route, "/app/story?resume=1")
        self.assertEqual(self.story_button().content, "Resume story")
        self.assertFalse(self.story_button().disabled)
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertEqual(len(story._listeners), 1)
        self.page.push_route.assert_not_awaited()

    async def test_reading_settings_event_confirms_preferences_and_back_returns_to_app(self):
        await self.open_page("/app?workspace=reading")
        await self.navigate("/app/settings")
        controls = self.page.views[-1].controls[0].controls
        await self.click(controls[2].controls[1])
        self.assertEqual(sdk_bridge.take_reading_request(), ("large_text", True))
        sdk_bridge.update_reading_status(True, "instant", "Reading choice kept.")
        await self.drain()
        controls = self.page.views[-1].controls[0].controls
        self.assertEqual(controls[1].value, "Text size: Larger")
        await self.click(controls[0].controls[-1])
        self.assertEqual(self.page.route, "/app?workspace=reading")
        self.assertEqual([view.route for view in self.page.views], [self.page.route])

    async def test_terminal_result_refresh_preserves_records_services_and_draft(self):
        session_id = sdk_bridge.restore_story_status("before-the-first-light", state="active")
        await self.open_page("/app/records?draft=1")
        view = self.page.views[-1]
        fields = view.controls[0].controls
        fields[1].value = "Keep this draft"
        self.assertTrue(sdk_bridge.finish_story(session_id, result={"choice": "sky"}))
        await self.drain()
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(fields[1].value, "Keep this draft")
        self.assertEqual(len(self.page._services._services), 1)
        self.assertEqual(sdk_bridge.story_status()["result"], {"choice": "sky"})
        self.page.push_route.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
