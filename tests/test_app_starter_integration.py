"""Independent app route, record independence and lifecycle acceptance."""

import asyncio
import gc
import unittest

from runtime import app_session, sdk_bridge
from runtime.application_data import DEFAULT_STORAGE_KEY
from runtime.renfletpy import story
from test_app_starter_protocol import AppStarterPageCase, FLET_AVAILABLE

if FLET_AVAILABLE:
    from flet.messaging.protocol import MessageAction


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class AppStarterIntegrationTests(AppStarterPageCase):
    async def test_records_survive_story_restore_reentry_and_a_fresh_page(self):
        await self.open_page()
        revision = await self.start_story()
        story.show("Mira", "App story choice", (("keep", "Keep"),))
        old_story = story.snapshot()
        await self.navigate("/app/records?source=explicit")
        await self.add_record("Newer than the native checkpoint")
        data = self.values[DEFAULT_STORAGE_KEY]
        old_service = self.page._runner_application_data["preferences"]
        story.restore(old_story)
        app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        sdk_bridge.resume_story()
        await self.settled()
        self.assertEqual(self.page.route, "/app/records?source=explicit")
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], data)
        self.assertFalse(app_session.session.complete(revision, {"choice": "old"}))
        for _ in range(8):
            await self.navigate("/app")
            await self.navigate("/app/records?source=warm")
        gc.collect()
        await self.transport.after_event(None)
        self.assertEqual([s._i for s in self.page._services._services], [old_service._i])
        self.assertEqual(len(story._listeners), 1)
        self.assertEqual(len(app_session.session._listeners), 1)
        await self.click("Back")
        self.assertEqual(self.page.route, "/app")
        await self.close_page()
        self.assertFalse(story._listeners)
        self.assertFalse(app_session.session._listeners)
        await self.open_page("/app/records?source=cold")
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], data)
        records = self.page.views[-1].controls[0].controls[-1]
        self.assertEqual(records.controls[0].content.controls[0].value,
                         "Title: Newer than the native checkpoint")

    async def test_completion_does_not_replace_an_explicit_records_route(self):
        await self.open_page()
        revision = await self.start_story()
        await self.navigate("/app/records?source=explicit")
        self.assertTrue(app_session.session.complete(revision, {"choice": "kept"}))
        await self.settled()
        self.assertEqual(self.page.route, "/app/records?source=explicit")
        await self.click("Back")
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(app_session.session.status()["result"]["value"], {"choice": "kept"})

    async def test_initial_record_read_cannot_resurrect_disconnected_app_callbacks(self):
        self.prepare_page("/app/records?source=cold")
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
            self.assertFalse(story._listeners)
            self.assertFalse(app_session.session._listeners)
            self.connection.send_message = send
            await self.page.on_connect(object())
            self.assertEqual(self.page.route, "/app/records?source=cold")
            self.assertEqual(len(story._listeners), 1)
            self.assertEqual(len(app_session.session._listeners), 1)
        finally:
            if not opening.done():
                opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)

    async def test_initial_records_loading_has_back_and_late_read_cannot_replace_home(self):
        self.prepare_page("/app/records?source=cold")
        entered = asyncio.Event()
        pending = []
        send = self.connection.send_message

        def defer_read(message):
            if message.action == MessageAction.INVOKE_METHOD and message.body.name == "get":
                pending.append(message.body)
                entered.set()
                return
            send(message)

        self.connection.send_message = defer_read
        opening = asyncio.create_task(sdk_bridge._page(self.page))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            self.assertTrue(any("loading" in text.lower() for text in self.visible_text()))
            self.connection.send_message = send
            await self.click("Back")
            await asyncio.wait_for(opening, 3)
            self.assertEqual(self.page.route, "/app")
            for request in pending:
                self.transport.handle_invoke_method_results(request.control_id, request.call_id, None, None)
            await self.settled()
            self.assertEqual(self.page.route, "/app")
            self.assertIn("App home", self.visible_text())
        finally:
            self.connection.send_message = send
            if not opening.done():
                opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)

    async def test_reconnect_renders_native_status_without_resubmitting_a_start(self):
        await self.open_page()
        await self.page.on_disconnect(None)
        revision = app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        await self.page.on_connect(object())
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(app_session.session.status()["revision"], revision)
        self.assertIsNone(app_session.session.take_request())
        self.assertEqual(len(story._listeners), 1)
        self.assertEqual(len(app_session.session._listeners), 1)
