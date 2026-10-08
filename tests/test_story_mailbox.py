"""Shared story commands stay plain, exclusive and owned by native confirmation."""

from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from runtime import sdk_bridge
from runtime.renfletpy import story


STORY_ID = "before-the-first-light"
COMMAND_KEYS = {"request_id", "session_id", "action", "story_id", "return_route"}
STATUS_KEYS = COMMAND_KEYS | {"state", "busy", "message", "result"}


class StoryMailboxTests(unittest.TestCase):
    def setUp(self):
        self.reset_bridge()
        self.addCleanup(self.reset_bridge)

    def reset_bridge(self):
        story.reset()
        sdk_bridge._quitting.clear()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        sdk_bridge.restore_story_status(None)

    def request_and_take(self, action="start", *, story_id=STORY_ID, return_route="/app"):
        request_id = sdk_bridge.request_story(action, story_id, return_route=return_route)
        self.assertIs(type(request_id), int)
        self.assertGreater(request_id, 0)
        command = sdk_bridge.take_story_command()
        self.assertIs(type(command), dict)
        self.assertEqual(set(command), COMMAND_KEYS)
        self.assertEqual(command["request_id"], request_id)
        self.assertEqual(command["action"], action)
        self.assertEqual(command["story_id"], story_id)
        self.assertEqual(command["return_route"], return_route)
        self.assertIs(type(command["session_id"]), int)
        self.assertGreater(command["session_id"], 0)
        return command

    def start_story(self, *, story_id=STORY_ID, return_route="/app"):
        command = self.request_and_take(story_id=story_id, return_route=return_route)
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        self.assertEqual(sdk_bridge.story_status()["state"], "active")
        return command

    def race(self, calls):
        """Release independent callers together, without timing-based sleeps."""
        barrier = threading.Barrier(len(calls))

        def run(call):
            barrier.wait(timeout=5)
            return call()

        with ThreadPoolExecutor(max_workers=len(calls)) as executor:
            futures = [executor.submit(run, call) for call in calls]
            return [future.result(timeout=5) for future in futures]

    def test_idle_status_is_plain_and_detached(self):
        status = sdk_bridge.story_status()
        self.assertIs(type(status), dict)
        self.assertTrue(STATUS_KEYS.issubset(status))
        self.assertEqual(status["state"], "idle")
        self.assertIsNone(status["story_id"])
        self.assertIsNone(status["session_id"])
        self.assertIsNone(status["request_id"])
        self.assertIsNone(status["action"])
        self.assertIsNone(status["result"])
        self.assertFalse(status["busy"])
        status.update(state="active", busy=True, story_id="foreign")
        self.assertEqual(sdk_bridge.story_status()["state"], "idle")
        self.assertFalse(sdk_bridge.story_status()["busy"])
        self.assertIsNone(sdk_bridge.take_story_command())

    def test_start_submission_does_not_invent_confirmed_native_state(self):
        request_id = sdk_bridge.request_story("start")
        self.assertIs(type(request_id), int)
        self.assertGreater(request_id, 0)
        status = sdk_bridge.story_status()
        self.assertEqual(status["state"], "idle")
        self.assertIsNone(status["story_id"])
        self.assertIsNone(status["session_id"])
        self.assertTrue(status["busy"])
        self.assertEqual(status["request_id"], request_id)
        self.assertEqual(status["action"], "start")
        command = sdk_bridge.take_story_command()
        self.assertEqual(command, {"request_id": request_id, "session_id": command["session_id"],
                                   "action": "start", "story_id": STORY_ID,
                                   "return_route": "/app"})
        self.assertIs(type(command["session_id"]), int)
        self.assertGreater(command["session_id"], 0)
        self.assertEqual(sdk_bridge.story_status(), status)
        self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=True, message="Started."))
        confirmed = sdk_bridge.story_status()
        self.assertEqual(confirmed["state"], "active")
        self.assertEqual(confirmed["story_id"], STORY_ID)
        self.assertEqual(confirmed["session_id"], command["session_id"])
        self.assertEqual(confirmed["message"], "Started.")
        self.assertFalse(confirmed["busy"])

    def test_command_is_consumed_once_and_remains_busy_until_confirmation(self):
        command = self.request_and_take()
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertTrue(sdk_bridge.story_status()["busy"])
        self.assertIsNone(sdk_bridge.request_story("start"))
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        self.assertFalse(sdk_bridge.story_status()["busy"])

    def test_untaken_confirmation_cannot_release_or_execute_the_command(self):
        request_id = sdk_bridge.request_story("start")
        pending = sdk_bridge.story_status()
        for success in (True, False):
            with self.subTest(success=success):
                self.assertFalse(sdk_bridge.confirm_story_command(request_id, success=success))
                self.assertEqual(sdk_bridge.story_status(), pending)
        command = sdk_bridge.take_story_command()
        self.assertEqual(command["request_id"], request_id)
        self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=True))

    def test_unrelated_and_noninteger_confirmations_preserve_the_pending_command(self):
        command = self.request_and_take()
        pending = sdk_bridge.story_status()
        for request_id in (command["request_id"] + 1, 0, -1, None, True,
                           str(command["request_id"]), float(command["request_id"])):
            with self.subTest(request_id=request_id):
                self.assertFalse(sdk_bridge.confirm_story_command(request_id, success=True))
                self.assertEqual(sdk_bridge.story_status(), pending)
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))

    def test_duplicate_confirmation_cannot_overwrite_confirmed_state_or_message(self):
        command = self.start_story()
        confirmed = sdk_bridge.story_status()
        for success in (True, False):
            with self.subTest(success=success):
                self.assertFalse(sdk_bridge.confirm_story_command(
                    command["request_id"], success=success, message="Late reply."))
                self.assertEqual(sdk_bridge.story_status(), confirmed)

    def test_failed_start_keeps_idle_and_allows_a_fresh_retry(self):
        command = self.request_and_take()
        self.assertTrue(sdk_bridge.confirm_story_command(
            command["request_id"], success=False, message="Native start failed."))
        status = sdk_bridge.story_status()
        self.assertEqual(status["state"], "idle")
        self.assertIsNone(status["session_id"])
        self.assertEqual(status["message"], "Native start failed.")
        self.assertFalse(status["busy"])
        self.assertFalse(sdk_bridge.finish_story(command["session_id"]))
        retry = self.request_and_take()
        self.assertNotEqual(retry["request_id"], command["request_id"])
        self.assertNotEqual(retry["session_id"], command["session_id"])
        pending = sdk_bridge.story_status()
        self.assertFalse(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        self.assertEqual(sdk_bridge.story_status(), pending)
        self.assertTrue(sdk_bridge.confirm_story_command(retry["request_id"], success=True))

    def test_return_and_resume_keep_the_same_session_and_query_route(self):
        route = "/app/story?source=story-menu"
        started = self.start_story(return_route=route)
        returned = self.request_and_take("return", return_route=route)
        self.assertEqual(returned["session_id"], started["session_id"])
        self.assertEqual(sdk_bridge.story_status()["state"], "active")
        self.assertTrue(sdk_bridge.confirm_story_command(returned["request_id"], success=True))
        self.assertEqual(sdk_bridge.story_status()["state"], "suspended")
        self.assertEqual(sdk_bridge.story_status()["return_route"], route)
        resumed = self.request_and_take("resume", return_route=route)
        self.assertEqual(resumed["session_id"], started["session_id"])
        self.assertEqual(sdk_bridge.story_status()["state"], "suspended")
        self.assertTrue(sdk_bridge.confirm_story_command(resumed["request_id"], success=True))
        self.assertEqual(sdk_bridge.story_status()["state"], "active")
        self.assertEqual(sdk_bridge.story_status()["session_id"], started["session_id"])

    def test_failed_return_and_resume_preserve_prior_confirmed_session(self):
        for action, state in (("return", "active"), ("resume", "suspended")):
            with self.subTest(action=action):
                session_id = sdk_bridge.restore_story_status(STORY_ID, state=state)
                command = self.request_and_take(action)
                self.assertTrue(sdk_bridge.confirm_story_command(
                    command["request_id"], success=False, message="Native operation failed."))
                status = sdk_bridge.story_status()
                self.assertEqual(status["state"], state)
                self.assertEqual(status["story_id"], STORY_ID)
                self.assertEqual(status["session_id"], session_id)
                self.assertEqual(status["message"], "Native operation failed.")
                self.assertFalse(status["busy"])
                retry = self.request_and_take(action)
                self.assertEqual(retry["session_id"], session_id)
                self.assertNotEqual(retry["request_id"], command["request_id"])
                self.assertTrue(sdk_bridge.confirm_story_command(retry["request_id"], success=True))

    def test_active_and_suspended_sessions_reject_new_starts_and_foreign_stories(self):
        for state in ("active", "suspended"):
            with self.subTest(state=state):
                sdk_bridge.restore_story_status(STORY_ID, state=state)
                before = sdk_bridge.story_status()
                self.assertIsNone(sdk_bridge.request_story("start"))
                self.assertIsNone(sdk_bridge.request_story("start", "other-story"))
                self.assertIsNone(sdk_bridge.request_story("resume", "other-story"))
                self.assertIsNone(sdk_bridge.request_story("return", "other-story"))
                self.assertEqual(sdk_bridge.story_status(), before)
                self.assertIsNone(sdk_bridge.take_story_command())

    def test_resume_requires_a_session_and_return_requires_an_active_session(self):
        for state in (None, "suspended", "completed", "cancelled"):
            with self.subTest(state=state):
                sdk_bridge.restore_story_status(STORY_ID if state else None,
                                                state=state or "suspended")
                before = sdk_bridge.story_status()
                self.assertIsNone(sdk_bridge.request_story("return"))
                if state != "suspended":
                    self.assertIsNone(sdk_bridge.request_story("resume"))
                self.assertEqual(sdk_bridge.story_status(), before)
                self.assertIsNone(sdk_bridge.take_story_command())

    def test_resuming_an_active_session_uses_its_existing_identity(self):
        started = self.start_story()
        resumed = self.request_and_take("resume")
        self.assertEqual(resumed["session_id"], started["session_id"])
        self.assertTrue(sdk_bridge.confirm_story_command(resumed["request_id"], success=True))
        self.assertEqual(sdk_bridge.story_status()["session_id"], started["session_id"])

    def test_command_copy_cannot_change_the_native_confirmation(self):
        command = self.request_and_take(return_route="/app/records?source=story")
        request_id, session_id = command["request_id"], command["session_id"]
        command.update(request_id=-1, session_id=-1, action="return",
                       story_id="foreign", return_route="/foreign")
        self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=True))
        status = sdk_bridge.story_status()
        self.assertEqual(status["state"], "active")
        self.assertEqual(status["story_id"], STORY_ID)
        self.assertEqual(status["session_id"], session_id)
        self.assertEqual(status["return_route"], "/app/records?source=story")

    def test_terminal_results_are_accepted_once_for_the_current_session(self):
        for outcome in ("completed", "cancelled"):
            with self.subTest(outcome=outcome):
                session_id = sdk_bridge.restore_story_status(STORY_ID, state="active")
                result = {"outcome": outcome, "scores": [1, 2]}
                self.assertTrue(sdk_bridge.finish_story(
                    session_id, outcome=outcome, result=result, message="Native ending."))
                status = sdk_bridge.story_status()
                self.assertEqual(status["state"], outcome)
                self.assertEqual(status["session_id"], session_id)
                self.assertEqual(status["result"], result)
                self.assertEqual(status["message"], "Native ending.")
                self.assertFalse(status["busy"])
                self.assertFalse(sdk_bridge.finish_story(
                    session_id, outcome="cancelled", result={"late": True}, message="Late ending."))
                self.assertEqual(sdk_bridge.story_status(), status)

    def test_unconfirmed_start_cannot_publish_a_terminal_result(self):
        command = self.request_and_take()
        pending = sdk_bridge.story_status()
        self.assertFalse(sdk_bridge.finish_story(command["session_id"], result={"late": True}))
        self.assertEqual(sdk_bridge.story_status(), pending)
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))

    def test_session_result_and_status_are_detached_at_every_nested_level(self):
        session_id = self.start_story()["session_id"]
        result = {"chapters": [{"choices": ["sky", {"score": 3}]}], "flags": [True, None]}
        self.assertTrue(sdk_bridge.finish_story(session_id, result=result))
        result["chapters"][0]["choices"][1]["score"] = 99
        result["flags"].append(False)
        status = sdk_bridge.story_status()
        self.assertEqual(status["result"]["chapters"][0]["choices"][1]["score"], 3)
        self.assertEqual(status["result"]["flags"], [True, None])
        status["result"]["chapters"][0]["choices"].clear()
        status["result"]["flags"][0] = False
        again = sdk_bridge.story_status()
        self.assertEqual(again["result"]["chapters"][0]["choices"], ["sky", {"score": 3}])
        self.assertEqual(again["result"]["flags"], [True, None])

    def test_plain_json_scalar_and_collection_results_are_supported(self):
        for result in (None, False, True, 12, -3.5, "ending", [], {},
                       {"items": [0, "one", None, {"ok": True}]}):
            with self.subTest(result=result):
                session_id = sdk_bridge.restore_story_status(STORY_ID, state="active")
                self.assertTrue(sdk_bridge.finish_story(session_id, result=result))
                self.assertEqual(sdk_bridge.story_status()["result"], result)

    def test_invalid_result_data_cannot_release_a_taken_story_command(self):
        class CustomList(list):
            pass

        class CustomDict(dict):
            pass

        cyclic = []
        cyclic.append(cyclic)
        invalid = [object(), ("tuple",), {"set"}, b"bytes", {1: "non-string key"},
                   {"nested": [("tuple",)]}, float("nan"), float("inf"), float("-inf"),
                   cyclic, CustomList([1]), CustomDict(ok=True)]
        session_id = self.start_story()["session_id"]
        command = self.request_and_take("return")
        pending = sdk_bridge.story_status()
        for index, result in enumerate(invalid):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    sdk_bridge.finish_story(session_id, result=result)
                self.assertEqual(sdk_bridge.story_status(), pending)
                self.assertIsNone(sdk_bridge.request_story("resume"))
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))

    def test_invalid_confirmations_do_not_release_the_pending_command(self):
        command = self.request_and_take()
        pending = sdk_bridge.story_status()
        for arguments in ({"success": 1}, {"success": None},
                          {"success": True, "message": {"text": "bad"}}):
            with self.subTest(arguments=arguments):
                with self.assertRaises(ValueError):
                    sdk_bridge.confirm_story_command(command["request_id"], **arguments)
                self.assertEqual(sdk_bridge.story_status(), pending)
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))

    def test_invalid_requests_do_not_replace_an_existing_command(self):
        request_id = sdk_bridge.request_story("start")
        pending = sdk_bridge.story_status()
        invalid = [{"action": "unknown"}, {"action": "start", "story_id": ""},
                   {"action": "start", "story_id": "  "},
                   {"action": "start", "story_id": None},
                   {"action": "start", "story_id": 42},
                   *({"action": "start", "return_route": route} for route in (
                       "/", "/settings", "/app/unknown", "https://example.com/app",
                       "//example.com/app", None, 42, object()))]
        for index, arguments in enumerate(invalid):
            with self.subTest(index=index):
                with self.assertRaises(ValueError):
                    sdk_bridge.request_story(**arguments)
                self.assertEqual(sdk_bridge.story_status(), pending)
        self.assertEqual(sdk_bridge.take_story_command()["request_id"], request_id)
        self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=True))

    def test_invalid_finish_and_recovery_arguments_preserve_pending_native_work(self):
        session_id = self.start_story()["session_id"]
        command = self.request_and_take("return")
        pending = sdk_bridge.story_status()
        invalid_finish = ({"outcome": "active"}, {"outcome": "failed"}, {"message": 1})
        for arguments in invalid_finish:
            with self.subTest(finish=arguments):
                with self.assertRaises(ValueError):
                    sdk_bridge.finish_story(session_id, **arguments)
                self.assertEqual(sdk_bridge.story_status(), pending)
        invalid_recovery = ({"story_id": ""}, {"story_id": 1}, {"state": "pending"},
                            {"state": "idle"}, {"message": None})
        for arguments in invalid_recovery:
            with self.subTest(recovery=arguments):
                with self.assertRaises(ValueError):
                    sdk_bridge.restore_story_status(**arguments)
                self.assertEqual(sdk_bridge.story_status(), pending)
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))

    def test_new_start_preserves_a_terminal_result_until_native_success(self):
        previous = self.start_story()
        self.assertTrue(sdk_bridge.finish_story(previous["session_id"], result={"ending": "dawn"}))
        for success in (False, True):
            with self.subTest(success=success):
                command = self.request_and_take()
                pending = sdk_bridge.story_status()
                self.assertEqual(pending["state"], "completed")
                self.assertEqual(pending["session_id"], previous["session_id"])
                self.assertEqual(pending["result"], {"ending": "dawn"})
                self.assertNotEqual(command["session_id"], previous["session_id"])
                self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=success))
                status = sdk_bridge.story_status()
                self.assertEqual(status["state"], "active" if success else "completed")
                self.assertEqual(status["result"], None if success else {"ending": "dawn"})

    def test_stale_session_end_cannot_release_or_complete_a_newer_start(self):
        previous = self.start_story()
        self.assertTrue(sdk_bridge.finish_story(previous["session_id"], result={"old": True}))
        newer = self.request_and_take()
        pending = sdk_bridge.story_status()
        self.assertFalse(sdk_bridge.finish_story(previous["session_id"], result={"stale": True}))
        self.assertEqual(sdk_bridge.story_status(), pending)
        self.assertTrue(sdk_bridge.confirm_story_command(newer["request_id"], success=True))
        active = sdk_bridge.story_status()
        self.assertFalse(sdk_bridge.finish_story(previous["session_id"], outcome="cancelled"))
        self.assertEqual(sdk_bridge.story_status(), active)
        self.assertTrue(sdk_bridge.finish_story(newer["session_id"]))

    def test_current_session_end_invalidates_queued_and_taken_commands(self):
        for action, state in (("return", "active"), ("resume", "suspended")):
            for take in (False, True):
                with self.subTest(action=action, taken=take):
                    session_id = sdk_bridge.restore_story_status(STORY_ID, state=state)
                    request_id = sdk_bridge.request_story(action)
                    self.assertIs(type(request_id), int)
                    if take:
                        self.assertEqual(sdk_bridge.take_story_command()["request_id"], request_id)
                    self.assertTrue(sdk_bridge.finish_story(session_id, result={"ending": "dawn"}))
                    completed = sdk_bridge.story_status()
                    self.assertEqual(completed["state"], "completed")
                    self.assertFalse(completed["busy"])
                    self.assertIsNone(completed["action"])
                    self.assertIsNone(sdk_bridge.take_story_command())
                    self.assertFalse(sdk_bridge.confirm_story_command(request_id, success=True))
                    self.assertEqual(sdk_bridge.story_status(), completed)
                    self.assertFalse(sdk_bridge.finish_story(session_id))

    def test_recovery_invalidates_queued_taken_commands_and_old_session_results(self):
        for take in (False, True):
            with self.subTest(taken=take):
                sdk_bridge.restore_story_status(None)
                started = self.start_story()
                request_id = sdk_bridge.request_story("return")
                if take:
                    self.assertEqual(sdk_bridge.take_story_command()["request_id"], request_id)
                recovered_id = sdk_bridge.restore_story_status(
                    STORY_ID, state="suspended", message="Recovered from a native save.")
                self.assertIs(type(recovered_id), int)
                self.assertGreater(recovered_id, 0)
                self.assertNotEqual(recovered_id, started["session_id"])
                recovered = sdk_bridge.story_status()
                self.assertEqual(recovered["state"], "suspended")
                self.assertEqual(recovered["session_id"], recovered_id)
                self.assertEqual(recovered["message"], "Recovered from a native save.")
                self.assertFalse(recovered["busy"])
                self.assertIsNone(recovered["request_id"])
                self.assertIsNone(sdk_bridge.take_story_command())
                self.assertFalse(sdk_bridge.confirm_story_command(request_id, success=True))
                self.assertFalse(sdk_bridge.finish_story(started["session_id"], result={"stale": True}))
                self.assertEqual(sdk_bridge.story_status(), recovered)
                resumed = self.request_and_take("resume")
                self.assertEqual(resumed["session_id"], recovered_id)
                self.assertTrue(sdk_bridge.confirm_story_command(resumed["request_id"], success=True))

    def test_clearing_recovery_invalidates_start_without_reusing_its_ids(self):
        command = self.request_and_take()
        self.assertIsNone(sdk_bridge.restore_story_status(None))
        idle = sdk_bridge.story_status()
        self.assertEqual(idle["state"], "idle")
        self.assertIsNone(idle["story_id"])
        self.assertIsNone(idle["session_id"])
        self.assertFalse(idle["busy"])
        self.assertFalse(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        self.assertFalse(sdk_bridge.finish_story(command["session_id"]))
        self.assertEqual(sdk_bridge.story_status(), idle)
        newer = self.request_and_take()
        self.assertGreater(newer["request_id"], command["request_id"])
        self.assertGreater(newer["session_id"], command["session_id"])

    def test_invalid_session_identifiers_cannot_end_current_story(self):
        session_id = self.start_story()["session_id"]
        active = sdk_bridge.story_status()
        for value in (None, True, 0, -1, session_id + 1, str(session_id), float(session_id)):
            with self.subTest(session_id=value):
                self.assertFalse(sdk_bridge.finish_story(value))
                self.assertEqual(sdk_bridge.story_status(), active)

    def test_story_command_blocks_save_reading_restart_and_quit_even_after_take(self):
        for take in (False, True):
            with self.subTest(taken=take):
                self.reset_bridge()
                sdk_bridge.initialize_save_status(True)
                request_id = sdk_bridge.request_story("start")
                if take:
                    sdk_bridge.take_story_command()
                pending = sdk_bridge.story_status()
                self.assertFalse(sdk_bridge.request_save("save"))
                self.assertFalse(sdk_bridge.request_save("load"))
                self.assertFalse(sdk_bridge.request_reading("large_text", True))
                self.assertFalse(sdk_bridge.request_reading("text_speed", "animated"))
                self.assertFalse(sdk_bridge.request_restart())
                self.assertFalse(sdk_bridge.request_quit())
                self.assertFalse(story.restarting())
                self.assertFalse(sdk_bridge.quitting())
                self.assertIsNone(sdk_bridge.take_save_request())
                self.assertIsNone(sdk_bridge.take_reading_request())
                self.assertEqual(sdk_bridge.story_status(), pending)
                if not take:
                    self.assertEqual(sdk_bridge.take_story_command()["request_id"], request_id)
                self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=False))
                self.assertTrue(sdk_bridge.request_save("save"))

    def test_pending_save_and_reading_block_story_until_their_native_result(self):
        for kind in ("save", "reading"):
            for take in (False, True):
                with self.subTest(kind=kind, taken=take):
                    self.reset_bridge()
                    if kind == "save":
                        self.assertTrue(sdk_bridge.request_save("save"))
                        if take:
                            self.assertEqual(sdk_bridge.take_save_request(), "save")
                    else:
                        self.assertTrue(sdk_bridge.request_reading("large_text", True))
                        if take:
                            self.assertEqual(sdk_bridge.take_reading_request(), ("large_text", True))
                    idle = sdk_bridge.story_status()
                    self.assertIsNone(sdk_bridge.request_story("start"))
                    self.assertEqual(sdk_bridge.story_status(), idle)
                    self.assertIsNone(sdk_bridge.take_story_command())
                    if kind == "save":
                        self.assertEqual(sdk_bridge.take_save_request(), None if take else "save")
                        sdk_bridge.update_save_status(True, "Saved.")
                    else:
                        self.assertEqual(sdk_bridge.take_reading_request(),
                                         None if take else ("large_text", True))
                        sdk_bridge.update_reading_status(True, "instant", "Kept.")
                    command = self.request_and_take()
                    self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))

    def test_restart_and_quit_block_story_submission(self):
        for kind, request in (("restart", sdk_bridge.request_restart), ("quit", sdk_bridge.request_quit)):
            with self.subTest(kind=kind):
                self.reset_bridge()
                self.assertTrue(request())
                idle = sdk_bridge.story_status()
                self.assertIsNone(sdk_bridge.request_story("start"))
                self.assertIsNone(sdk_bridge.take_story_command())
                self.assertEqual(sdk_bridge.story_status(), idle)

    def test_other_status_updates_cannot_release_a_pending_story_operation(self):
        command = self.request_and_take()
        pending = sdk_bridge.story_status()
        sdk_bridge.update_save_status(True, "Native slot scan.")
        sdk_bridge.update_reading_status(True, "animated", "Native preferences scan.")
        self.assertEqual(sdk_bridge.story_status(), pending)
        self.assertFalse(sdk_bridge.request_save("save"))
        self.assertFalse(sdk_bridge.request_reading("large_text", False))
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))

    def test_failed_story_command_releases_every_competing_request(self):
        competitors = {"save": lambda: sdk_bridge.request_save("save"),
                       "reading": lambda: sdk_bridge.request_reading("large_text", True),
                       "restart": sdk_bridge.request_restart, "quit": sdk_bridge.request_quit}
        for name, request in competitors.items():
            with self.subTest(kind=name):
                self.reset_bridge()
                command = self.request_and_take()
                self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=False))
                self.assertTrue(request())

    def test_concurrent_duplicate_submissions_create_one_command(self):
        requests = self.race([lambda: sdk_bridge.request_story("start") for _ in range(8)])
        accepted = [request_id for request_id in requests if request_id is not None]
        self.assertEqual(len(accepted), 1)
        self.assertIs(type(accepted[0]), int)
        command = sdk_bridge.take_story_command()
        self.assertEqual(command["request_id"], accepted[0])
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertTrue(sdk_bridge.story_status()["busy"])
        self.assertTrue(sdk_bridge.confirm_story_command(accepted[0], success=True))

    def test_concurrent_native_consumers_receive_the_command_once(self):
        request_id = sdk_bridge.request_story("start")
        commands = self.race([sdk_bridge.take_story_command for _ in range(8)])
        taken = [command for command in commands if command is not None]
        self.assertEqual(len(taken), 1)
        self.assertEqual(taken[0]["request_id"], request_id)
        self.assertTrue(sdk_bridge.story_status()["busy"])
        self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=True))

    def test_concurrent_duplicate_confirmations_apply_once(self):
        command = self.request_and_take()
        confirmations = self.race([
            lambda: sdk_bridge.confirm_story_command(command["request_id"], success=True)
            for _ in range(8)])
        self.assertEqual(confirmations.count(True), 1)
        self.assertEqual(confirmations.count(False), 7)
        status = sdk_bridge.story_status()
        self.assertEqual(status["state"], "active")
        self.assertEqual(status["session_id"], command["session_id"])
        self.assertFalse(status["busy"])

    def test_concurrent_terminal_results_accept_and_retain_only_one_winner(self):
        session_id = self.start_story()["session_id"]
        replies = self.race([
            lambda index=index: sdk_bridge.finish_story(session_id, result={"winner": index})
            for index in range(8)])
        self.assertEqual(replies.count(True), 1)
        self.assertEqual(replies.count(False), 7)
        status = sdk_bridge.story_status()
        self.assertEqual(status["state"], "completed")
        self.assertEqual(status["result"], {"winner": replies.index(True)})

    def test_concurrent_story_and_other_native_requests_have_one_owner(self):
        competitors = {"save": lambda: sdk_bridge.request_save("save"),
                       "reading": lambda: sdk_bridge.request_reading("large_text", True),
                       "restart": sdk_bridge.request_restart, "quit": sdk_bridge.request_quit}
        for name, competitor in competitors.items():
            with self.subTest(kind=name):
                self.reset_bridge()
                request_id, accepted = self.race([lambda: sdk_bridge.request_story("start"), competitor])
                self.assertEqual(int(request_id is not None) + int(accepted), 1)
                status = sdk_bridge.story_status()
                if request_id is not None:
                    self.assertTrue(status["busy"])
                    self.assertEqual(sdk_bridge.take_story_command()["request_id"], request_id)
                    self.assertFalse(sdk_bridge.save_status()["busy"])
                    self.assertFalse(sdk_bridge.reading_status()["busy"])
                    self.assertFalse(story.restarting())
                    self.assertFalse(sdk_bridge.quitting())
                else:
                    self.assertFalse(status["busy"])
                    self.assertIsNone(sdk_bridge.take_story_command())
                    if name == "save":
                        self.assertEqual(sdk_bridge.take_save_request(), "save")
                    elif name == "reading":
                        self.assertEqual(sdk_bridge.take_reading_request(), ("large_text", True))
                    elif name == "restart":
                        self.assertTrue(story.restarting())
                    else:
                        self.assertTrue(sdk_bridge.quitting())

    def test_concurrent_recovery_and_old_completion_leave_the_recovered_session(self):
        previous_id = self.start_story()["session_id"]
        recovered_id, old_result = self.race([
            lambda: sdk_bridge.restore_story_status(STORY_ID, state="suspended"),
            lambda: sdk_bridge.finish_story(previous_id, result={"old": True})])
        self.assertIs(type(old_result), bool)
        self.assertNotEqual(recovered_id, previous_id)
        status = sdk_bridge.story_status()
        self.assertEqual(status["state"], "suspended")
        self.assertEqual(status["session_id"], recovered_id)
        self.assertIsNone(status["result"])
        self.assertFalse(sdk_bridge.finish_story(previous_id))
        self.assertEqual(sdk_bridge.story_status(), status)


if __name__ == "__main__":
    unittest.main()
