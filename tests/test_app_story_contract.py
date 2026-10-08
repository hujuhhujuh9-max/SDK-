"""C's status adapter preserves the native mailbox's confirmed-state contract."""

from concurrent.futures import ThreadPoolExecutor
import json
import threading
import unittest

from runtime import sdk_bridge
from runtime.renfletpy import story


STORY_ID = "lantern"
STORY_TITLE = "The Last Lantern"
COMMAND_KEYS = {"request_id", "session_id", "action", "story_id", "return_route"}


class AppStoryContractTests(unittest.TestCase):
    def setUp(self):
        self.previous_config = dict(sdk_bridge._story_config)
        self.addCleanup(self.cleanup_bridge)
        self.reset_bridge()
        sdk_bridge.configure_app_story(STORY_ID, STORY_TITLE)

    def reset_bridge(self):
        story.reset()
        sdk_bridge._quitting.clear()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        sdk_bridge.restore_story_status(None)

    def cleanup_bridge(self):
        self.reset_bridge()
        sdk_bridge.configure_app_story(self.previous_config["story_id"],
                                       self.previous_config["story_title"])

    def revision(self):
        return sdk_bridge.app_story_status()["revision"]

    def request_and_take(self, action="start", **options):
        options.setdefault("expected_revision", self.revision())
        request_id = sdk_bridge.request_story(action, STORY_ID, **options)
        self.assertIs(type(request_id), int)
        self.assertGreater(request_id, 0)
        command = sdk_bridge.take_story_command()
        self.assertIs(type(command), dict)
        self.assertEqual(set(command), COMMAND_KEYS)
        self.assertEqual(command["request_id"], request_id)
        self.assertEqual(command["story_id"], STORY_ID)
        self.assertEqual(command["action"], action)
        return command

    def start_story(self, **options):
        command = self.request_and_take(**options)
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        return command

    def test_adapter_exposes_plain_status_and_the_configured_title(self):
        status = sdk_bridge.app_story_status()
        self.assertIs(type(status), dict)
        self.assertTrue({"revision", "loading", "busy", "active", "resume_available",
                         "message", "error", "result"}.issubset(status))
        self.assertIs(type(status["revision"]), int)
        self.assertGreater(status["revision"], 0)
        for name in ("loading", "busy", "active", "resume_available"):
            self.assertIs(status[name], False)
        self.assertEqual(status["story_title"], STORY_TITLE)
        self.assertIsNone(status["result"])
        self.assertIsNone(status["error"])
        status.update(active=True, story_title="Foreign title", revision=-1)
        self.assertEqual(sdk_bridge.app_story_status()["story_title"], STORY_TITLE)
        self.assertFalse(sdk_bridge.app_story_status()["active"])

    def test_legacy_mailbox_still_returns_ids_and_rejects_duplicates_with_none(self):
        request_id = sdk_bridge.request_story("start")
        self.assertIs(type(request_id), int)
        self.assertGreater(request_id, 0)
        self.assertIsNone(sdk_bridge.request_story("start"))
        command = sdk_bridge.take_story_command()
        self.assertEqual(set(command), COMMAND_KEYS)
        self.assertEqual(command["story_id"], "before-the-first-light")
        self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=True))

    def test_stale_and_noninteger_revisions_leave_the_mailbox_unchanged(self):
        revision = self.revision()
        raw, displayed = sdk_bridge.story_status(), sdk_bridge.app_story_status()
        for stale in (revision - 1, revision + 1, True, str(revision), float(revision)):
            with self.subTest(revision=stale):
                self.assertIsNone(sdk_bridge.request_story("start", STORY_ID, expected_revision=stale))
                self.assertEqual(sdk_bridge.story_status(), raw)
                self.assertEqual(sdk_bridge.app_story_status(), displayed)
                self.assertIsNone(sdk_bridge.take_story_command())
        self.request_and_take(expected_revision=revision)

    def test_submission_and_confirmation_retire_revisions_but_consumption_does_not(self):
        displayed_revision = self.revision()
        request_id = sdk_bridge.request_story("start", STORY_ID, expected_revision=displayed_revision)
        pending_revision = self.revision()
        self.assertGreater(pending_revision, displayed_revision)
        self.assertTrue(sdk_bridge.app_story_status()["busy"])
        self.assertFalse(sdk_bridge.app_story_status()["active"])
        self.assertIsNone(sdk_bridge.request_story("start", STORY_ID,
                                                   expected_revision=displayed_revision))
        self.assertEqual(sdk_bridge.take_story_command()["request_id"], request_id)
        self.assertEqual(self.revision(), pending_revision)
        self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=True))
        confirmed_revision = self.revision()
        self.assertGreater(confirmed_revision, pending_revision)
        confirmed = sdk_bridge.app_story_status()
        self.assertTrue(confirmed["active"])
        self.assertTrue(confirmed["resume_available"])
        self.assertFalse(sdk_bridge.confirm_story_command(request_id, success=False))
        self.assertEqual(sdk_bridge.app_story_status(), confirmed)
        self.assertIsNone(sdk_bridge.request_story("resume", STORY_ID, expected_revision=pending_revision))
        self.request_and_take("resume", expected_revision=confirmed_revision)

    def test_concurrent_submissions_cannot_share_one_displayed_revision(self):
        displayed_revision = self.revision()
        barrier = threading.Barrier(4)

        def submit():
            barrier.wait(timeout=5)
            return sdk_bridge.request_story("start", STORY_ID, expected_revision=displayed_revision)

        with ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(submit) for _ in range(4)]
            replies = [future.result(timeout=5) for future in futures]
        accepted = [reply for reply in replies if reply is not None]
        self.assertEqual(len(accepted), 1)
        self.assertEqual(sdk_bridge.take_story_command()["request_id"], accepted[0])
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertTrue(sdk_bridge.confirm_story_command(accepted[0], success=True))

    def test_save_and_reading_busy_periods_retire_preexisting_and_busy_revisions(self):
        for kind in ("save", "reading"):
            with self.subTest(kind=kind):
                self.reset_bridge()
                before = self.revision()
                if kind == "save":
                    self.assertTrue(sdk_bridge.request_save("save"))
                    take = sdk_bridge.take_save_request
                else:
                    self.assertTrue(sdk_bridge.request_reading("large_text", True))
                    take = sdk_bridge.take_reading_request
                busy_revision = self.revision()
                self.assertGreater(busy_revision, before)
                self.assertTrue(sdk_bridge.app_story_status()["busy"])
                self.assertFalse(sdk_bridge.story_status()["busy"])
                self.assertIsNone(sdk_bridge.request_story("start", STORY_ID, expected_revision=busy_revision))
                self.assertIsNotNone(take())
                self.assertEqual(self.revision(), busy_revision)
                self.assertTrue(sdk_bridge.app_story_status()["busy"])
                if kind == "save":
                    sdk_bridge.update_save_status(True, "Saved.")
                else:
                    sdk_bridge.update_reading_status(True, "instant", "Kept.")
                released_revision = self.revision()
                self.assertGreater(released_revision, busy_revision)
                self.assertFalse(sdk_bridge.app_story_status()["busy"])
                for retired in (before, busy_revision):
                    self.assertIsNone(sdk_bridge.request_story("start", STORY_ID, expected_revision=retired))
                self.request_and_take(expected_revision=released_revision)

    def test_recovery_and_configuration_changes_retire_displayed_generations(self):
        before_configuration = self.revision()
        sdk_bridge.configure_app_story(STORY_ID, STORY_TITLE)
        configured = self.revision()
        self.assertGreater(configured, before_configuration)
        self.assertIsNone(sdk_bridge.request_story("start", STORY_ID,
                                                   expected_revision=before_configuration))
        session_id = sdk_bridge.restore_story_status(STORY_ID, state="suspended")
        recovered = self.revision()
        self.assertGreater(recovered, configured)
        self.assertIsNone(sdk_bridge.request_story("resume", STORY_ID, expected_revision=configured))
        command = self.request_and_take("resume", expected_revision=recovered)
        self.assertEqual(command["session_id"], session_id)

    def test_configuration_cannot_redirect_a_pending_or_live_session(self):
        command = self.request_and_take()
        for pending in (True, False):
            with self.subTest(pending=pending):
                if not pending:
                    self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))
                before = sdk_bridge.app_story_status()
                with self.assertRaises(ValueError):
                    sdk_bridge.configure_app_story("foreign", "Foreign title")
                self.assertEqual(sdk_bridge.app_story_status(), before)
        self.assertEqual(sdk_bridge.story_status()["story_id"], STORY_ID)

    def test_replacement_requires_explicit_start_authorization_and_current_revision(self):
        self.start_story()
        before = sdk_bridge.app_story_status()
        self.assertIsNone(sdk_bridge.request_story("start", STORY_ID, expected_revision=before["revision"]))
        for action, arguments in (("start", {"replace": True}),
                                  ("resume", {"replace": True, "expected_revision": before["revision"]}),
                                  ("start", {"replace": 1, "expected_revision": before["revision"]})):
            with self.subTest(action=action, arguments=arguments):
                with self.assertRaises(ValueError):
                    sdk_bridge.request_story(action, STORY_ID, **arguments)
                self.assertEqual(sdk_bridge.app_story_status(), before)
        self.assertIsNone(sdk_bridge.request_story("start", STORY_ID, replace=True,
                                                   expected_revision=before["revision"] - 1))
        self.assertEqual(sdk_bridge.app_story_status(), before)
        self.request_and_take(replace=True)

    def test_failed_replacement_retains_confirmed_progress_and_permits_a_fresh_retry(self):
        original = self.start_story(return_route="/app/records?source=lantern")
        before = sdk_bridge.story_status()
        displayed_revision = self.revision()
        replacement = self.request_and_take(replace=True)
        self.assertNotEqual(replacement["session_id"], original["session_id"])
        self.assertEqual(sdk_bridge.story_status()["session_id"], original["session_id"])
        self.assertTrue(sdk_bridge.confirm_story_command(
            replacement["request_id"], success=False, message="Native replacement failed."))
        failed = sdk_bridge.story_status()
        for name in ("state", "story_id", "session_id", "return_route", "result"):
            self.assertEqual(failed[name], before[name])
        displayed = sdk_bridge.app_story_status()
        self.assertEqual(displayed["error"], "Native replacement failed.")
        self.assertTrue(displayed["resume_available"])
        self.assertFalse(displayed["busy"])
        self.assertIsNone(sdk_bridge.request_story("start", STORY_ID, replace=True,
                                                   expected_revision=displayed_revision))
        retry = self.request_and_take(replace=True)
        self.assertNotEqual(retry["session_id"], replacement["session_id"])
        self.assertTrue(sdk_bridge.confirm_story_command(retry["request_id"], success=True))
        self.assertEqual(sdk_bridge.story_status()["session_id"], retry["session_id"])
        self.assertIsNone(sdk_bridge.app_story_status()["error"])

    def test_old_completion_cannot_retire_a_queued_or_taken_replacement(self):
        for take in (False, True):
            with self.subTest(taken=take):
                self.reset_bridge()
                old_session = self.start_story()["session_id"]
                request_id = sdk_bridge.request_story("start", STORY_ID,
                                                       expected_revision=self.revision(), replace=True)
                self.assertIs(type(request_id), int)
                if take:
                    command = sdk_bridge.take_story_command()
                pending, displayed = sdk_bridge.story_status(), sdk_bridge.app_story_status()
                self.assertFalse(sdk_bridge.finish_story(old_session, result={"old": True}))
                self.assertEqual(sdk_bridge.story_status(), pending)
                self.assertEqual(sdk_bridge.app_story_status(), displayed)
                if not take:
                    command = sdk_bridge.take_story_command()
                self.assertEqual(command["request_id"], request_id)
                self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=True))
                self.assertFalse(sdk_bridge.finish_story(old_session))
                self.assertTrue(sdk_bridge.finish_story(command["session_id"]))

    def test_cancel_waits_for_native_confirmation_and_finishes_the_same_session_once(self):
        session_id = self.start_story()["session_id"]
        command = self.request_and_take("cancel")
        self.assertEqual(command["session_id"], session_id)
        self.assertEqual(sdk_bridge.story_status()["state"], "active")
        self.assertTrue(sdk_bridge.app_story_status()["active"])
        self.assertTrue(sdk_bridge.app_story_status()["busy"])
        self.assertTrue(sdk_bridge.confirm_story_command(
            command["request_id"], success=True, message="Story cancelled."))
        status = sdk_bridge.app_story_status()
        self.assertEqual(sdk_bridge.story_status()["state"], "cancelled")
        self.assertEqual(sdk_bridge.story_status()["session_id"], session_id)
        self.assertFalse(status["active"])
        self.assertFalse(status["resume_available"])
        self.assertFalse(status["busy"])
        self.assertEqual(status["result"]["status"], "cancelled")
        self.assertEqual(status["result"]["story_title"], STORY_TITLE)
        self.assertFalse(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        self.assertFalse(sdk_bridge.finish_story(session_id))
        self.assertEqual(sdk_bridge.app_story_status(), status)

    def test_failed_cancel_reports_error_and_keeps_the_session_resumable(self):
        session_id = self.start_story()["session_id"]
        command = self.request_and_take("cancel")
        self.assertTrue(sdk_bridge.confirm_story_command(
            command["request_id"], success=False, message="Native cancellation failed."))
        status = sdk_bridge.app_story_status()
        self.assertEqual(sdk_bridge.story_status()["session_id"], session_id)
        self.assertEqual(sdk_bridge.story_status()["state"], "active")
        self.assertTrue(status["active"])
        self.assertTrue(status["resume_available"])
        self.assertFalse(status["busy"])
        self.assertIsNone(status["result"])
        self.assertEqual(status["error"], "Native cancellation failed.")
        retry = self.request_and_take("cancel")
        self.assertEqual(retry["session_id"], session_id)
        self.assertTrue(sdk_bridge.confirm_story_command(retry["request_id"], success=True))

    def test_failed_outcome_remains_invalid_without_releasing_a_cancel_command(self):
        session_id = self.start_story()["session_id"]
        command = self.request_and_take("cancel")
        raw, displayed = sdk_bridge.story_status(), sdk_bridge.app_story_status()
        with self.assertRaises(ValueError):
            sdk_bridge.finish_story(session_id, outcome="failed", result={"error": "Native error"})
        self.assertEqual(sdk_bridge.story_status(), raw)
        self.assertEqual(sdk_bridge.app_story_status(), displayed)
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=False))

    def test_scalar_list_and_mapping_results_are_normalized_without_losing_zero_or_false(self):
        results = (0, False, None, "Dawn", [0, False, {"path": "庭"}],
                   {"Score": 0, "Skipped": False, "Choices": ["庭", "tower"], "Detail": {"phase": 2}})
        for raw in results:
            with self.subTest(result=raw):
                session_id = sdk_bridge.restore_story_status(STORY_ID, state="active")
                self.assertTrue(sdk_bridge.finish_story(session_id, result=raw, message="The morning is yours."))
                normalized = sdk_bridge.app_story_status()["result"]
                self.assertEqual(normalized["status"], "completed")
                self.assertEqual(normalized["story_title"], STORY_TITLE)
                self.assertEqual(normalized["summary"], "The morning is yours.")
                self.assertEqual(sdk_bridge.story_status()["result"], raw)
                expected_values = raw if type(raw) is dict else {} if raw is None else {"Result": raw}
                self.assertEqual(set(normalized["values"]), set(expected_values))
                for label, value in expected_values.items():
                    rendered = normalized["values"][label]
                    if type(value) in (list, dict):
                        self.assertIs(type(rendered), str)
                        self.assertEqual(json.loads(rendered), value)
                    else:
                        self.assertIs(type(rendered), type(value))
                        self.assertEqual(rendered, value)

    def test_normalized_result_is_detached_from_raw_input_and_other_snapshots(self):
        session_id = self.start_story()["session_id"]
        raw = {"Score": 0, "Skipped": False, "Choices": ["garden"]}
        self.assertTrue(sdk_bridge.finish_story(session_id, result=raw))
        first = sdk_bridge.app_story_status()["result"]
        raw["Choices"].append("tower")
        first["values"].update(Score=99, Skipped=True, Choices="changed")
        again = sdk_bridge.app_story_status()["result"]
        self.assertEqual(again["values"]["Score"], 0)
        self.assertIs(again["values"]["Skipped"], False)
        self.assertEqual(json.loads(again["values"]["Choices"]), ["garden"])
        self.assertEqual(sdk_bridge.story_status()["result"]["Choices"], ["garden"])

    def test_native_return_preserves_identity_route_and_resume_with_a_fresh_revision(self):
        route = "/app/records?from=lantern"
        command = self.start_story(return_route=route)
        before = self.revision()
        self.assertTrue(sdk_bridge.return_from_story(command["session_id"], message="Native checkpoint reached."))
        status = sdk_bridge.story_status()
        self.assertEqual(status["state"], "suspended")
        self.assertEqual(status["session_id"], command["session_id"])
        self.assertEqual(status["story_id"], STORY_ID)
        self.assertEqual(status["return_route"], route)
        self.assertEqual(status["message"], "Native checkpoint reached.")
        displayed = sdk_bridge.app_story_status()
        self.assertGreater(displayed["revision"], before)
        self.assertFalse(displayed["active"])
        self.assertTrue(displayed["resume_available"])
        self.assertFalse(sdk_bridge.return_from_story(command["session_id"]))
        self.assertEqual(sdk_bridge.app_story_status(), displayed)
        self.assertIsNone(sdk_bridge.request_story("resume", STORY_ID, expected_revision=before))
        resumed = self.request_and_take("resume", return_route=route)
        self.assertEqual(resumed["session_id"], command["session_id"])
        self.assertTrue(sdk_bridge.confirm_story_command(resumed["request_id"], success=True))

    def test_native_return_rejects_stale_ids_and_pending_commands_without_retiring_them(self):
        for action in ("return", "resume", "cancel", "start"):
            for take in (False, True):
                with self.subTest(action=action, taken=take):
                    self.reset_bridge()
                    session_id = self.start_story()["session_id"]
                    request_id = sdk_bridge.request_story(action, STORY_ID, expected_revision=self.revision(),
                                                           replace=action == "start")
                    self.assertIs(type(request_id), int)
                    if take:
                        sdk_bridge.take_story_command()
                    raw, displayed = sdk_bridge.story_status(), sdk_bridge.app_story_status()
                    for value in (session_id, session_id - 1, None, True, str(session_id)):
                        self.assertFalse(sdk_bridge.return_from_story(value))
                        self.assertEqual(sdk_bridge.story_status(), raw)
                        self.assertEqual(sdk_bridge.app_story_status(), displayed)
                    if not take:
                        self.assertEqual(sdk_bridge.take_story_command()["request_id"], request_id)
                    self.assertTrue(sdk_bridge.confirm_story_command(request_id, success=False))

    def test_native_return_rejects_pre_recovery_sessions_and_invalid_messages(self):
        original_id = self.start_story()["session_id"]
        current_id = sdk_bridge.restore_story_status(STORY_ID, state="active")
        raw, displayed = sdk_bridge.story_status(), sdk_bridge.app_story_status()
        self.assertFalse(sdk_bridge.return_from_story(original_id))
        with self.assertRaises(ValueError):
            sdk_bridge.return_from_story(current_id, message=None)
        self.assertEqual(sdk_bridge.story_status(), raw)
        self.assertEqual(sdk_bridge.app_story_status(), displayed)
        self.assertTrue(sdk_bridge.return_from_story(current_id))


if __name__ == "__main__":
    unittest.main()
