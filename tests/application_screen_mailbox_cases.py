"""Combined A/C cases, run by the C checker's explicit --with-mailbox gate.

This filename is outside ordinary test discovery because A's bridge is not yet
on main. The combined gate requires the real bridge and rejects missing APIs;
it never replaces the mailbox with a fake or treats these cases as skips.
"""

import asyncio
import threading
import unittest

import test_application_screens_flet as fixtures
from runtime import application_screens as screens, sdk_bridge
from runtime.application_data import DEFAULT_STORAGE_KEY
from scripts.flet_protocol import walk


class ApplicationScreenMailboxCases(unittest.IsolatedAsyncioTestCase):
    def reset_bridge(self):
        sdk_bridge.story.reset()
        sdk_bridge._quitting.clear()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        sdk_bridge.restore_story_status()

    async def asyncSetUp(self):
        self.reset_bridge()
        self.ui = fixtures.ApplicationScreensFletTests()
        await self.ui.asyncSetUp()
        self.adapter = screens.StoryMailboxAdapter(
            sdk_bridge.story_status,
            lambda action: sdk_bridge.request_story(action, "lantern", return_route="/app"),
            read_busy=lambda: (sdk_bridge.save_status()["busy"] or sdk_bridge.reading_status()["busy"]
                               or sdk_bridge.quitting() or sdk_bridge.story.restarting()),
            story_title="The Last Lantern",
        )
        self.ui.read_status = self.adapter.read_status
        self.ui.request_story = self.adapter.request_story
        await self.ui.navigate(screens.APP_ROUTE)

    async def asyncTearDown(self):
        if self.ui.page.on_close is not None:
            await self.ui.page.on_close(None)
        await self.ui.asyncTearDown()
        self.reset_bridge()

    def native_confirm(self, command, *, success=True, message="Native operation confirmed."):
        replies = []
        worker = threading.Thread(target=lambda: replies.append(sdk_bridge.confirm_story_command(
            command["request_id"], success=success, message=message)))
        worker.start()
        worker.join(timeout=3)
        self.assertFalse(worker.is_alive())
        self.assertEqual(replies, [True])

    async def test_real_start_request_is_consumed_and_confirmed_once(self):
        await self.ui.click("Start story")
        await self.ui.click("Start story")
        self.assertEqual(sdk_bridge.story_status()["state"], "idle")
        self.assertTrue(sdk_bridge.story_status()["busy"])
        self.assertEqual(self.ui.page.route, screens.APP_ROUTE)
        command = sdk_bridge.take_story_command()
        self.assertEqual(command["action"], "start")
        self.assertIsNone(sdk_bridge.take_story_command())
        self.native_confirm(command)
        self.assertEqual(sdk_bridge.story_status()["state"], "active")
        self.assertFalse(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        await self.ui.refresh_status()
        self.assertTrue(self.ui.button("Start story").disabled)
        self.assertFalse(self.ui.button("Resume story").disabled)

    async def test_real_return_resume_keep_session_identity_and_do_not_request_a_save_load(self):
        session_id = sdk_bridge.restore_story_status("lantern", state="active")
        await self.ui.navigate(screens.STORY_ROUTE)
        await self.ui.click("Return to app")
        self.assertEqual(self.ui.page.route, screens.STORY_ROUTE)
        command = sdk_bridge.take_story_command()
        self.assertEqual((command["action"], command["session_id"]), ("return", session_id))
        self.native_confirm(command)
        await self.ui.navigate(screens.APP_ROUTE)
        self.assertEqual(sdk_bridge.story_status()["state"], "suspended")
        await self.ui.click("Resume story")
        command = sdk_bridge.take_story_command()
        self.assertEqual((command["action"], command["session_id"]), ("resume", session_id))
        self.assertIsNone(sdk_bridge.take_save_request())
        self.native_confirm(command)
        self.assertEqual(sdk_bridge.story_status()["session_id"], session_id)
        self.assertEqual(sdk_bridge.story_status()["state"], "active")

    async def test_native_failure_preserves_confirmed_state_and_allows_a_new_request(self):
        await self.ui.click("Start story")
        failed = sdk_bridge.take_story_command()
        self.native_confirm(failed, success=False, message="The story could not be opened. Try again.")
        await self.ui.refresh_status()
        self.assertIn("The story could not be opened. Try again.", walk(self.ui.encoded()))
        self.assertEqual(sdk_bridge.story_status()["state"], "idle")
        self.assertFalse(self.ui.button("Start story").disabled)
        await self.ui.click("Start story")
        command = sdk_bridge.take_story_command()
        self.assertGreater(command["request_id"], failed["request_id"])
        self.assertFalse(sdk_bridge.confirm_story_command(failed["request_id"], success=True))
        self.native_confirm(command)

    async def test_native_recovery_retires_stale_controls_and_old_pending_confirmation(self):
        first = sdk_bridge.restore_story_status("lantern", state="suspended")
        await self.ui.refresh_status()
        restored = sdk_bridge.restore_story_status("lantern", state="suspended")
        self.assertNotEqual(first, restored)
        await self.ui.click("Resume story")
        self.assertIsNone(sdk_bridge.take_story_command())
        self.ui.assert_patch_contains("Story status changed. Reload before continuing.")
        await self.ui.click("Reload story status")
        await self.ui.click("Resume story")
        command = sdk_bridge.take_story_command()
        sdk_bridge.restore_story_status("lantern", state="suspended")
        self.assertFalse(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        self.assertFalse(sdk_bridge.story_status()["busy"])
        await self.ui.refresh_status()
        self.assertFalse(self.ui.button("Resume story").disabled)

    async def test_terminal_native_result_keeps_records_draft_and_preferences(self):
        session_id = sdk_bridge.restore_story_status("lantern", state="active")
        await self.ui.navigate(screens.RECORDS_ROUTE)
        title = self.ui.control("TextField", "label", "Title")
        self.ui.session.apply_patch(title._i, {"value": "Independent application record"})
        await self.ui.click("Add record")
        persisted = self.ui.connection.values[DEFAULT_STORAGE_KEY]
        view = self.ui.page.views[-1]
        self.ui.session.apply_patch(title._i, {"value": "Unsubmitted draft"})
        result = {"story_id": "lantern", "run_id": "native-run-id", "status": "completed",
                  "phase": "done", "result": "tower"}
        self.assertTrue(sdk_bridge.finish_story(session_id, result=result, message="The harbor answers."))
        self.assertIs(self.ui.page.views[-1], view)
        self.assertEqual(title.value, "Unsubmitted draft")
        self.assertEqual(self.ui.page.route, screens.RECORDS_ROUTE)
        self.ui.status["result"] = self.adapter.read_status()["result"]
        await self.ui.navigate(screens.RESULT_ROUTE)
        self.assertIn("Result: tower", walk(self.ui.encoded()))
        self.assertNotIn("native-run-id", walk(self.ui.encoded()))
        self.assertEqual(self.ui.connection.values[DEFAULT_STORAGE_KEY], persisted)
        self.assertEqual(sum(call.name == "set" for call in self.ui.connection.calls), 1)
        self.assertFalse(sdk_bridge.finish_story(session_id, result="duplicate"))

    async def test_unsupported_cancel_and_restart_never_reach_the_real_mailbox(self):
        sdk_bridge.restore_story_status("lantern", state="active")
        await self.ui.navigate(screens.STORY_ROUTE)
        self.assertNotIn("Cancel story", walk(self.ui.encoded()))
        await self.ui.click("Start from beginning")
        await self.ui.navigate(screens.START_ROUTE)
        await self.ui.click("Start again")
        await self.ui.navigate(screens.CANCEL_ROUTE)
        await self.ui.click("Confirm cancellation")
        status = self.adapter.read_status()
        self.assertFalse(self.adapter.request_story("cancel", status["revision"]))
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertEqual(sdk_bridge.story_status()["state"], "active")

    async def test_real_reading_operation_blocks_story_controls_until_native_confirmation(self):
        self.assertTrue(sdk_bridge.request_reading("large_text", True))
        await self.ui.refresh_status()
        self.assertTrue(self.ui.button("Start story").disabled)
        await self.ui.click("Start story")
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertEqual(sdk_bridge.take_reading_request(), ("large_text", True))
        sdk_bridge.update_reading_status(True, "instant", "Reading choice kept.")
        await self.ui.refresh_status()
        await self.ui.click("Start story")
        self.assertEqual(sdk_bridge.take_story_command()["action"], "start")

    async def test_actual_a_runner_menu_uses_cs_return_callback_without_signature_conflict(self):
        session_id = sdk_bridge.restore_story_status("lantern", state="active", return_route="/app?workspace=1")
        arrived = asyncio.Event()

        async def client_navigation(route):
            await self.ui.navigate(route)
            if route == "/app?workspace=1":
                arrived.set()

        # Native route replies are emulated through the actual Flet dispatcher;
        # the registered A page/connection/navigation guards remain unchanged.
        self.ui.page.push_route = client_navigation
        self.ui.page.route = "/menu"
        await sdk_bridge._page(self.ui.page)
        await self.ui.click("Return to app")
        command = sdk_bridge.take_story_command()
        self.assertEqual((command["action"], command["session_id"]), ("return", session_id))
        self.native_confirm(command)
        await asyncio.wait_for(arrived.wait(), 3)
        self.assertEqual(self.ui.page.route, "/app?workspace=1")
        self.assertEqual(sdk_bridge.story_status()["state"], "suspended")


if __name__ == "__main__":
    unittest.main()
