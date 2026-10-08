"""Failure-oriented checks of the app/native mailbox and operation boundary."""

import concurrent.futures
import threading
import types
import unittest
from unittest.mock import patch

from runtime.app_session import AppSession, STORY_ID
from runtime import sdk_bridge
from runtime.renfletpy import story


class AppSessionTests(unittest.TestCase):
    def setUp(self):
        self.session = AppSession()

    def start(self):
        self.assertTrue(self.session.request("start", self.session.status()["revision"]))
        command = self.session.take_request()
        self.assertTrue(self.session.finish(command["command_id"]))
        return self.session.status()["revision"]

    def test_command_is_consumed_once_and_remains_busy_until_native_ack(self):
        self.assertTrue(self.session.request("start", 0))
        self.assertFalse(self.session.request("start", 0))
        command = self.session.take_request()
        self.assertEqual(command["story_id"], STORY_ID)
        self.assertIsNone(self.session.take_request())
        self.assertTrue(self.session.status()["busy"])
        self.assertFalse(self.session.finish(command["command_id"] + 1))
        self.assertTrue(self.session.status()["busy"])
        self.assertTrue(self.session.finish(command["command_id"]))
        self.assertFalse(self.session.finish(command["command_id"]))
        self.assertFalse(self.session.status()["busy"])

    def test_an_ack_cannot_finish_an_unconsumed_command(self):
        self.session.request("start", 0)
        self.assertFalse(self.session.finish(self.session.status()["command_id"]))
        self.assertTrue(self.session.status()["busy"])

    def test_return_and_resume_retain_live_generation_without_claiming_a_save(self):
        revision = self.start()
        for action, visible in (("return", False), ("resume", True)):
            self.assertTrue(self.session.request(action, revision))
            command = self.session.take_request()
            self.assertTrue(self.session.finish(command["command_id"]))
            self.assertEqual(self.session.status()["revision"], revision)
            self.assertEqual(self.session.status()["resume_kind"], "live")
            self.assertEqual(self.session.status()["showing_story"], visible)
        self.session.request("return", revision)
        self.session.finish(self.session.take_request()["command_id"])
        self.assertFalse(self.session.request("return", revision))

    def test_native_failure_releases_busy_and_preserves_existing_live_story(self):
        revision = self.start()
        self.session.request("return", revision)
        command = self.session.take_request()
        self.assertTrue(self.session.finish(command["command_id"], success=False, message="Native failed"))
        status = self.session.status()
        self.assertFalse(status["busy"])
        self.assertTrue(status["showing_story"])
        self.assertEqual(status["revision"], revision)
        self.assertEqual(status["message"], "Native failed")
        self.assertTrue(self.session.request("return", revision))

    def test_start_over_requires_confirmation_and_rejects_old_native_results(self):
        old = self.start()
        self.assertFalse(self.session.request("start", old))
        self.assertTrue(self.session.request("start", old, replace=True))
        command = self.session.take_request()
        self.assertFalse(self.session.complete(old, "Late old completion"))
        self.session.finish(command["command_id"])
        self.assertGreater(self.session.status()["revision"], old)
        self.assertFalse(self.session.complete(old, "Late old completion"))
        self.assertFalse(self.session.request("return", old))

    def test_completion_is_single_and_result_mutation_cannot_change_native_status(self):
        revision = self.start()
        value = {"note": ["Kept"]}
        self.assertTrue(self.session.complete(revision, value))
        value["note"].append("Changed")
        result = self.session.status()["result"]
        self.assertEqual(result, {"story_id": STORY_ID, "outcome": "completed", "value": {"note": ["Kept"]}})
        result["value"]["note"].clear()
        self.assertEqual(self.session.status()["result"]["value"]["note"], ["Kept"])
        self.assertFalse(self.session.complete(revision, "Duplicate"))
        self.assertFalse(self.session.status()["resume_available"])

    def test_initial_saved_discovery_preserves_an_early_command(self):
        self.session.request("start", 0)
        command_id = self.session.status()["command_id"]
        self.assertFalse(self.session.initialize_saved(False))
        self.assertEqual(self.session.status()["command_id"], command_id)
        self.assertTrue(self.session.status()["busy"])
        self.assertEqual(self.session.take_request()["command_id"], command_id)

    def test_completion_preserves_confirmed_bookmark_and_saved_resume_gets_a_fresh_generation(self):
        old = self.start()
        self.assertTrue(self.session.complete(old, "Finished note", saved_available=True))
        status = self.session.status()
        self.assertEqual(status["phase"], "completed")
        self.assertEqual(status["result"]["value"], "Finished note")
        self.assertEqual(status["resume_kind"], "saved")
        self.assertTrue(status["resume_available"])
        self.assertFalse(self.session.request("start", old))
        self.assertTrue(self.session.request("resume", old))
        command = self.session.take_request()
        restored = self.session.restore(command_id=command["command_id"])
        self.assertGreater(restored, old)
        self.assertIsNone(self.session.status()["result"])
        self.assertFalse(self.session.complete(old, "Late prior ending", saved_available=True))
        self.assertEqual(self.session.status()["phase"], "active")
        self.assertTrue(self.session.complete(restored, "New ending"))

    def test_late_saved_discovery_prevents_an_unconfirmed_destructive_start(self):
        self.session.request("start", 0)
        command_id = self.session.status()["command_id"]
        self.session.initialize_saved(True)
        self.assertEqual(self.session.status()["command_id"], command_id)
        self.assertTrue(self.session.status()["busy"])
        self.assertIsNone(self.session.take_request())
        self.assertFalse(self.session.status()["busy"])
        self.assertEqual(self.session.status()["resume_kind"], "saved")
        self.assertIn("Confirm", self.session.status()["message"])
        self.assertFalse(self.session.request("start", 0))
        self.assertTrue(self.session.request("start", 0, replace=True))

    def test_saved_resume_restoration_acknowledges_only_its_taken_command(self):
        self.session.initialize_saved(True)
        self.session.request("resume", 0)
        old_id = self.session.status()["command_id"]
        self.assertIsNone(self.session.restore(command_id=old_id))
        self.session.take_request()
        revision = self.session.restore(command_id=old_id)
        self.assertGreater(revision, 0)
        self.assertEqual(self.session.status()["event"], "finished")
        self.assertEqual(self.session.status()["action"], "resume")
        self.assertEqual(self.session.status()["command_id"], old_id)
        self.assertEqual(self.session.status()["resume_kind"], "live")
        self.assertIsNone(self.session.restore(command_id=old_id))

    def test_recovery_invalidates_inflight_ids_and_revisions_before_a_new_command(self):
        revision = self.start()
        self.session.request("return", revision)
        old = self.session.take_request()
        restored = self.session.restore(showing_story=False)
        self.assertTrue(self.session.request("resume", restored))
        new = self.session.take_request()
        self.assertGreater(new["command_id"], old["command_id"])
        self.assertFalse(self.session.finish(old["command_id"]))
        self.assertFalse(self.session.complete(revision, "Old save continuation"))
        self.assertTrue(self.session.status()["busy"])
        self.assertTrue(self.session.finish(new["command_id"]))

    def test_listener_is_detachable_and_cannot_modify_other_snapshots(self):
        snapshots = []
        detach = self.session.subscribe(snapshots.append)
        self.session.request("start", 0)
        snapshots[0]["phase"] = "completed"
        self.assertEqual(self.session.status()["phase"], "ready")
        detach()
        detach()
        self.session.finish(self.session.take_request()["command_id"])
        self.assertEqual(len(snapshots), 1)
        self.assertFalse(self.session._listeners)

    def test_blocked_native_consumption_and_completion_are_retryable(self):
        revision = self.start()
        blocked = False
        self.session.bind_gate(lambda: blocked)
        self.session.request("return", revision)
        blocked = True
        self.assertIsNone(self.session.take_request())
        self.assertFalse(self.session.complete(revision, "Premature"))
        blocked = False
        self.session.finish(self.session.take_request()["command_id"])
        blocked = True
        self.assertFalse(self.session.complete(revision, "Premature"))
        self.assertFalse(self.session.request("resume", revision))
        blocked = False
        self.assertTrue(self.session.complete(revision, "Kept"))

    def test_unavailable_actions_bad_revisions_and_live_objects_are_rejected(self):
        self.assertFalse(self.session.request("resume", 0))
        self.assertFalse(self.session.request("return", 0))
        self.assertFalse(self.session.request("start", False))
        with self.assertRaises(ValueError):
            self.session.request("unknown", 0)
        revision = self.start()
        with self.assertRaises(TypeError):
            self.session.complete(revision, object())
        with self.assertRaises(ValueError):
            self.session.complete(revision, "Kept", saved_available=1)
        self.assertEqual(self.session.status()["phase"], "active")


class SharedAppOperationTests(unittest.TestCase):
    def setUp(self):
        self.config = patch.dict("sys.modules", {"runtime.project_config": types.SimpleNamespace(STARTUP_TEMPLATE="app")})
        self.config.start()
        story.reset()
        sdk_bridge._quitting.clear()
        sdk_bridge.update_save_status(True, "Saved story available")
        sdk_bridge.update_reading_status(False, "instant", "Ready")
        self.session = sdk_bridge.app_session
        self.session.restore(phase="ready", resume_kind="unavailable", showing_story=False)

    def tearDown(self):
        self.session.restore(phase="ready", resume_kind="unavailable", showing_story=False)
        sdk_bridge.update_save_status(False, "Ready")
        sdk_bridge.update_reading_status(False, "instant", "Ready")
        sdk_bridge._quitting.clear()
        story.reset()
        self.config.stop()

    def test_pending_app_command_blocks_save_reading_replay_and_quit(self):
        revision = self.session.status()["revision"]
        self.assertTrue(sdk_bridge.request_app_story("start", revision))
        self.assertFalse(sdk_bridge.request_save("save"))
        self.assertFalse(sdk_bridge.request_reading("large_text", True))
        self.assertFalse(sdk_bridge.request_restart())
        self.assertFalse(sdk_bridge.request_quit())
        command = self.session.take_request()
        self.session.finish(command["command_id"], success=False)
        self.assertTrue(sdk_bridge.request_save("save"))

    def test_save_reading_and_quit_block_new_app_commands_and_native_completion(self):
        self.session.request("start", self.session.status()["revision"])
        self.session.finish(self.session.take_request()["command_id"])
        revision = self.session.status()["revision"]
        for operation, release in (
                (lambda: sdk_bridge.request_save("save"), lambda: sdk_bridge.update_save_status(True, "Saved")),
                (lambda: sdk_bridge.request_reading("large_text", True),
                 lambda: sdk_bridge.update_reading_status(False, "instant", "Ready")),
                (sdk_bridge.request_quit, sdk_bridge._quitting.clear)):
            self.assertTrue(operation())
            self.assertFalse(sdk_bridge.request_app_story("return", revision))
            self.assertFalse(self.session.complete(revision, "Too soon"))
            release()
        self.assertTrue(self.session.complete(revision, "Done"))

    def test_simultaneous_save_and_start_accept_only_one_operation(self):
        barrier = threading.Barrier(2)
        revision = self.session.status()["revision"]
        def accept(action):
            barrier.wait(timeout=3)
            return action()
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            futures = [pool.submit(accept, lambda: sdk_bridge.request_save("save")),
                       pool.submit(accept, lambda: sdk_bridge.request_app_story("start", revision))]
            self.assertEqual(sum(future.result(timeout=3) for future in futures), 1)

    def test_default_installation_cannot_submit_app_commands(self):
        with patch.dict("sys.modules", {"runtime.project_config": types.SimpleNamespace(STARTUP_TEMPLATE="story")}):
            self.assertFalse(self.session.status()["app_mode"])
            self.assertFalse(sdk_bridge.request_app_story("start", self.session.status()["revision"]))

    def test_native_replay_discards_live_session_and_invalidates_its_completion(self):
        self.session.request("start", self.session.status()["revision"])
        self.session.finish(self.session.take_request()["command_id"])
        old = self.session.status()["revision"]
        self.assertTrue(sdk_bridge.request_restart())
        story.reset()  # The existing native full_restart handles the script.
        status = self.session.status()
        self.assertEqual(status["phase"], "ready")
        self.assertFalse(status["resume_available"])
        self.assertGreater(status["revision"], old)
        self.assertFalse(self.session.complete(old, "Old completion"))


if __name__ == "__main__":
    unittest.main()
