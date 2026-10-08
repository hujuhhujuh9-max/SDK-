"""Real Flet routing during the native saved-story confirmation visibility scope.

The native producer is represented by the taken command and its acknowledgement.
These cases exercise actual Flet controls, client events and preference messages;
the native/Android probes separately establish prompt rendering and save loading.
"""

import unittest

from runtime import app_session, sdk_bridge
from test_app_starter_protocol import AppStarterPageCase, FLET_AVAILABLE

if FLET_AVAILABLE:
    import flet as ft


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class AppConfirmationProtocolTests(AppStarterPageCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.scope_command_id = None

    async def asyncTearDown(self):
        if self.scope_command_id is not None:
            sdk_bridge.end_app_story_load(self.scope_command_id)
        await super().asyncTearDown()

    async def saved_resume(self):
        self.assertTrue(app_session.session.initialize_saved(True))
        await self.open_page()
        self.assertFalse(self.button("Resume story").disabled)
        self.assertIn("Resume from your saved place.", self.visible_text())
        await self.click("Resume story")
        command = app_session.session.take_request()
        self.assertIsNotNone(command)
        self.assertEqual(command["action"], "resume")
        self.assertTrue(app_session.session.status()["busy"])
        self.assertEqual(app_session.session.status()["resume_kind"], "saved")
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(sdk_bridge.presentation(), "page")
        return command

    def begin_load(self, command):
        self.assertTrue(sdk_bridge.begin_app_story_load(command["command_id"]))
        self.scope_command_id = command["command_id"]
        self.assertEqual(sdk_bridge.presentation(), "scene")

    def end_load(self, command):
        self.assertTrue(sdk_bridge.end_app_story_load(command["command_id"]))
        if self.scope_command_id == command["command_id"]:
            self.scope_command_id = None

    def title_field(self):
        return next(control for control in self.all_controls()
                    if isinstance(control, ft.TextField) and control.label == "Title")

    async def records_draft(self, route, value):
        await self.navigate(route)
        view = self.page.views[-1]
        field = self.title_field()
        self.transport.apply_patch(field._i, {"value": value})
        await self.transport.dispatch_event(field._i, "change", None)
        self.assertEqual(field.value, value)
        self.assertEqual([call.name for call in self.connection.calls], ["get"])
        return view, field

    async def test_saved_resume_shows_native_confirmation_without_completing_home_navigation(self):
        command = await self.saved_resume()
        self.begin_load(command)
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertTrue(self.button("Resume story").disabled)
        self.assertTrue(self.button("Start story").disabled)
        self.assertFalse(sdk_bridge.request_quit())

        # A declined native load acknowledges failure before its finally block
        # releases visibility. A queued Flet status refresh cannot hide the prompt.
        self.assertTrue(app_session.session.finish(command["command_id"], success=False,
                                                  message="Resume cancelled."))
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.end_load(command)
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertEqual(self.page.route, "/app")
        self.assertFalse(app_session.session.status()["busy"])
        self.assertEqual(app_session.session.status()["resume_kind"], "saved")
        self.assertFalse(self.button("Resume story").disabled)
        self.assertIn("Resume cancelled.", self.visible_text())
        self.assertIsNone(app_session.session.take_request())

    async def test_new_records_link_and_draft_survive_native_load_cancellation(self):
        command = await self.saved_resume()
        # A newer deep link can arrive before the native timer opens its prompt.
        view, field = await self.records_draft("/app/records?source=before-prompt", "Keep this draft")
        self.begin_load(command)
        await self.navigate("/app/records?source=during-prompt")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(field.value, "Keep this draft")
        self.assertEqual([call.name for call in self.connection.calls], ["get"])

        self.assertTrue(app_session.session.finish(command["command_id"], success=False,
                                                  message="Resume cancelled."))
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.end_load(command)
        await self.settled()
        self.assertEqual(self.page.route, "/app/records?source=during-prompt")
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(field.value, "Keep this draft")
        self.assertFalse(app_session.session.status()["busy"])
        self.assertFalse(self.button("Add record").disabled)
        self.assertEqual(self.values, {})
        self.assertIsNone(app_session.session.take_request())
        await self.click("Back")
        self.assertEqual(self.page.route, "/app")
        self.assertFalse(self.button("Resume story").disabled)
        self.assertIn("Resume cancelled.", self.visible_text())

    async def test_saved_resume_acknowledgement_does_not_hijack_new_records_during_scope(self):
        command = await self.saved_resume()
        self.begin_load(command)
        view, field = await self.records_draft("/app/records?source=after-prompt", "Newer app draft")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        old_revision = command["revision"]
        restored = app_session.session.restore(command_id=command["command_id"])
        self.assertGreater(restored, old_revision)
        await self.settled()
        self.assertEqual(self.page.route, "/app/records?source=after-prompt")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        # Ownership outlives the mailbox acknowledgement, so finally can release
        # this scope even after native restoration advances the story revision.
        self.end_load(command)
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertEqual(self.page.route, "/app/records?source=after-prompt")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(field.value, "Newer app draft")
        self.assertFalse(app_session.session.status()["busy"])
        self.assertEqual(app_session.session.status()["resume_kind"], "live")
        self.assertIsNone(app_session.session.take_request())

    async def test_stale_scope_release_after_reconnect_cannot_hide_a_new_native_prompt(self):
        old_command = await self.saved_resume()
        self.begin_load(old_command)
        await self.page.on_disconnect(None)
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertFalse(sdk_bridge.end_app_story_load(old_command["command_id"]))
        self.assertTrue(app_session.session.finish(old_command["command_id"], success=False,
                                                  message="Resume cancelled."))
        await self.page.on_connect(object())
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertFalse(self.button("Resume story").disabled)

        await self.click("Resume story")
        new_command = app_session.session.take_request()
        self.assertIsNotNone(new_command)
        self.assertNotEqual(new_command["command_id"], old_command["command_id"])
        self.begin_load(new_command)
        self.assertFalse(sdk_bridge.end_app_story_load(old_command["command_id"]))
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertTrue(app_session.session.status()["busy"])
        self.assertEqual(self.page.route, "/app")
        self.assertTrue(app_session.session.finish(new_command["command_id"], success=False,
                                                  message="Resume cancelled."))
        self.end_load(new_command)
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertFalse(self.button("Resume story").disabled)
        self.assertEqual(len(app_session.session._listeners), 1)


if __name__ == "__main__":
    unittest.main()
