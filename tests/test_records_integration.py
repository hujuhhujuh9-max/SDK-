"""Exercise D's route seam with prepared Flet and its native method protocol."""

import asyncio
import gc
import importlib.util
import types
import unittest

from runtime import sdk_bridge
from runtime.application_data import DEFAULT_STORAGE_KEY, get_application_data_store
from runtime.renfletpy import story

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    from flet.controls.context import _context_page
    from flet.messaging.session import Session
    from flet.messaging.protocol import MessageAction
    from test_form_list_flet import PreferencesConnection


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class RecordsIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        story.reset()
        sdk_bridge._quitting.clear()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        self.values = {}
        self.page = None

    async def close_page(self):
        if self.page is not None:
            await self.page.on_close(None)
            self.session.close()
            _context_page.reset(self.token)
            self.page = None
            await asyncio.sleep(0)

    async def asyncTearDown(self):
        await self.close_page()
        story.reset()

    def prepare_page(self, route):
        self.connection = PreferencesConnection()
        self.connection.values = self.values
        self.session = Session(self.connection)
        self.connection.session = self.session
        self.page = self.session.page
        self.page.route = route
        self.token = _context_page.set(self.page)
        self.connection.encode(self.session.get_page_patch())
        self.page.push_route = self.navigate

    async def open_page(self, route="/records?source=cold"):
        self.prepare_page(route)
        await sdk_bridge._page(self.page)
        return self.page.views[-1]

    async def navigate(self, route):
        self.page.route = route
        await self.page.on_route_change(types.SimpleNamespace(route=route))

    async def add_record(self, title):
        fields = self.page.views[-1].controls[0].controls
        fields[1].value = title
        await fields[3].controls[0]._trigger_event("click", None)
        self.assertEqual(fields[-2].value, "Record saved")

    async def test_initial_native_read_cannot_reconnect_a_disconnected_page(self):
        self.prepare_page("/records?source=cold")
        entered = asyncio.Event()
        send = self.connection.send_message

        def defer_read(message):
            if message.action == MessageAction.INVOKE_METHOD and message.body.name == "get":
                entered.set()
                return
            send(message)

        self.connection.send_message = defer_read
        opening = asyncio.create_task(sdk_bridge._page(self.page))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            await self.page.on_disconnect(None)
            await asyncio.wait_for(opening, 3)
            self.assertEqual(len(story._listeners), 0)
            for name in ("_story_detach", "_menu_request", "_resume_request",
                         "_save_refresh", "_history_refresh", "_reading_refresh"):
                self.assertIsNone(getattr(sdk_bridge, name), name)
            self.connection.send_message = send
            await self.page.on_connect(object())
            self.assertEqual(len(story._listeners), 1)
            self.assertEqual(self.page.views[-1].route, "/records?source=cold")
        finally:
            if not opening.done():
                opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)

    async def test_real_route_reentry_keeps_one_service_and_reloads_saved_records(self):
        view = await self.open_page()
        fields = view.controls[0].controls
        fields[1].value = "Unsubmitted draft"
        await self.navigate("/records?source=query")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(fields[1].value, "Unsubmitted draft")
        await self.add_record("Persisted record")
        service = self.page._runner_application_data["preferences"]
        for _ in range(10):
            await self.navigate("/diagnostics")
            await self.navigate("/records?source=reentry")
        gc.collect()
        await self.session.after_event(None)
        self.assertEqual([item._i for item in self.page._services._services], [service._i])
        self.assertEqual(len(story._listeners), 1)
        self.assertEqual(len(self.page.views), 2)
        records = self.page.views[-1].controls[0].controls[-1]
        self.assertEqual(records.controls[0].content.controls[0].value,
                         "Title: Persisted record")
        heading = self.page.views[-1].controls[0].controls[0]
        await heading.controls[-1]._trigger_event("click", None)
        self.assertEqual(self.page.route, "/diagnostics")
        self.assertEqual(sdk_bridge.presentation(), "diagnostics")

    async def test_story_restore_replay_and_new_page_keep_current_application_data(self):
        revision = story.show("Mira", "Pending choice", (("sky", "Sky"),))
        older_story = story.snapshot()
        await self.open_page()
        await self.add_record("Newer than the story save")
        saved_data = self.values[DEFAULT_STORAGE_KEY]
        restored = story.restore(older_story)
        sdk_bridge.resume_story()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        self.assertEqual(self.page.route, "/records?source=cold")
        self.assertGreater(restored, revision)
        self.assertFalse(story.choose(revision, "sky"))
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertEqual((await get_application_data_store(self.page).load())[0]["values"]["title"],
                         "Newer than the story save")
        story.reset()
        await asyncio.sleep(0)
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], saved_data)
        await self.close_page()
        reopened = await self.open_page()
        self.assertEqual(reopened.controls[0].controls[-1].controls[0].content.controls[0].value,
                         "Title: Newer than the story save")
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], saved_data)
        await self.navigate("/")
        self.assertEqual(sdk_bridge.presentation(), "scene")
