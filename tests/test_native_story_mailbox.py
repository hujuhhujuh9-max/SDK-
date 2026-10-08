"""Behavioral checks for the optional native-thread mailbox adapter."""

import importlib.util
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / "examples/renpy/lifecycle/app/native_story_mailbox.py"
SPEC = importlib.util.spec_from_file_location("native_story_mailbox_example", SOURCE)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def status(state="running", run="live-1"):
    return {"story_id": "lantern", "status": state, "run_id": run, "phase": "arrival", "result": None}


def command(action="start", request=3, session=3, story="lantern"):
    return {"action": action, "request_id": request, "session_id": session,
            "story_id": story, "return_route": "/app?from=story"}


class NativeStoryMailboxTests(unittest.TestCase):
    def setUp(self):
        self.bridge = Mock()
        self.bridge.confirm_story_command.return_value = True
        self.bridge.restore_story_status.return_value = 9
        self.bridge.story_status.return_value = {"return_route": "/app?from=story"}
        self.bridge.take_story_command.return_value = None
        self.adapter = MODULE.NativeStoryMailbox(self.bridge, "lantern")

    def begin(self):
        self.bridge.take_story_command.return_value = command()
        self.assertEqual(self.adapter.take(status("unavailable", None), scene_shown=False), "start")
        self.assertTrue(self.adapter.entered(status()))
        self.bridge.reset_mock()

    def test_submission_is_consumed_once_and_confirmed_only_after_native_entry(self):
        self.bridge.take_story_command.return_value = command()
        self.assertEqual(self.adapter.take(status("unavailable", None), scene_shown=False), "start")
        self.bridge.confirm_story_command.assert_not_called()
        self.assertIsNone(self.adapter.take(status("unavailable", None), scene_shown=False))
        self.bridge.take_story_command.assert_called_once()
        self.assertFalse(self.adapter.entered(status("unavailable", None)))
        self.assertTrue(self.adapter.entered(status()))
        self.bridge.confirm_story_command.assert_called_once_with(3, success=True)
        self.assertFalse(self.adapter.entered(status()))

    def test_active_resume_needs_no_native_reentry_and_retains_the_live_run(self):
        self.begin()
        self.bridge.take_story_command.return_value = command("resume", request=4)
        self.assertIsNone(self.adapter.take(status(), scene_shown=True))
        self.bridge.confirm_story_command.assert_called_once_with(4, success=True)
        self.assertIsNone(self.adapter.pending)
        self.assertEqual((self.adapter.session_id, self.adapter.run_id), (3, "live-1"))

    def test_suspended_resume_reenters_then_confirms_matching_live_state(self):
        self.begin()
        self.bridge.take_story_command.return_value = command("resume", request=4)
        self.assertEqual(self.adapter.take(status("returned"), scene_shown=False), "resume")
        self.bridge.confirm_story_command.assert_not_called()
        self.assertTrue(self.adapter.entered(status()))
        self.bridge.confirm_story_command.assert_called_once_with(4, success=True)

    def test_resume_rejects_changed_native_run_and_stale_bridge_session(self):
        self.begin()
        for native, request in ((status(run="replacement"), command("resume", request=4)),
                                (status(), command("resume", request=5, session=2))):
            with self.subTest(native=native, request=request):
                self.bridge.take_story_command.return_value = request
                self.assertIsNone(self.adapter.take(native, scene_shown=True))
                self.assertFalse(self.bridge.confirm_story_command.call_args.kwargs["success"])
                self.assertIsNone(self.adapter.pending)

    def test_wrong_story_is_rejected_without_dispatch_or_changing_run(self):
        self.bridge.take_story_command.return_value = command(story="before-the-first-light")
        self.assertIsNone(self.adapter.take(status("unavailable", None), scene_shown=False))
        self.assertFalse(self.bridge.confirm_story_command.call_args.kwargs["success"])
        self.assertIsNone(self.adapter.run_id)

    def test_return_is_confirmed_after_native_return_not_when_taken(self):
        self.begin()
        self.bridge.take_story_command.return_value = command("return", request=4)
        self.assertEqual(self.adapter.take(status(), scene_shown=True), "return")
        self.bridge.confirm_story_command.assert_not_called()
        self.assertTrue(self.adapter.handoff(status("returned")))
        self.bridge.confirm_story_command.assert_called_once_with(4, success=True,
            message="Story returned. Resume continues this live progress.")
        self.assertFalse(self.adapter.handoff(status("returned")))

    def test_native_return_stages_a_matching_mailbox_request(self):
        self.begin()
        self.bridge.request_story.return_value = 4
        self.bridge.take_story_command.return_value = command("return", request=4)
        self.assertTrue(self.adapter.prepare_return())
        self.bridge.request_story.assert_called_once_with("return", "lantern", return_route="/app?from=story")
        self.bridge.confirm_story_command.assert_not_called()

    def test_rejected_native_return_does_not_take_another_command(self):
        self.bridge.request_story.return_value = None
        self.assertFalse(self.adapter.prepare_return())
        self.bridge.take_story_command.assert_not_called()

    def test_completion_wins_a_pending_return_without_confirming_a_suspension(self):
        self.begin()
        self.bridge.take_story_command.return_value = command("return", request=4)
        self.adapter.take(status(), scene_shown=True)
        completed = dict(status("completed"), result="garden", phase="done")
        self.adapter.handoff(completed)
        self.bridge.finish_story.assert_called_once_with(3, result=completed)
        self.bridge.confirm_story_command.assert_not_called()
        self.assertIsNone(self.adapter.pending)

    def test_recovery_issues_new_runtime_ids_and_does_not_route_or_replay_completion(self):
        self.begin()
        self.bridge.take_story_command.return_value = command("return", request=4)
        self.adapter.take(status(), scene_shown=True)
        self.adapter.restore(status("completed"))
        self.assertEqual(self.adapter.session_id, 9)
        self.assertIsNone(self.adapter.pending)
        self.bridge.restore_story_status.assert_called_once_with("lantern", state="completed",
            return_route="/app?from=story")
        self.bridge.finish_story.assert_not_called()
        self.bridge.set_presentation.assert_not_called()
        self.bridge.confirm_story_command.assert_not_called()
        self.assertFalse(self.adapter.handoff(status("completed")))
        self.bridge.finish_story.assert_not_called()

    def test_unknown_recovery_clears_optional_session(self):
        self.adapter.restore(status("unavailable", None))
        self.bridge.restore_story_status.assert_called_once_with(None, state="suspended", return_route="/app?from=story")
        self.assertIsNone(self.adapter.run_id)

    def test_duplicate_completion_is_not_republished(self):
        self.begin()
        self.bridge.finish_story.return_value = True
        completed = dict(status("completed"), result="garden", phase="done")
        self.assertTrue(self.adapter.handoff(completed))
        self.assertFalse(self.adapter.handoff(completed))
        self.bridge.finish_story.assert_called_once_with(3, result=completed)

    def test_stale_entry_confirmation_does_not_bind_a_new_session(self):
        self.bridge.take_story_command.return_value = command()
        self.adapter.take(status("unavailable", None), scene_shown=False)
        self.bridge.confirm_story_command.return_value = False
        self.assertFalse(self.adapter.entered(status()))
        self.assertIsNone(self.adapter.session_id)
        self.assertIsNone(self.adapter.run_id)

    def test_native_owner_rejects_execution_on_a_worker_thread(self):
        failures = []

        def worker():
            for action in (lambda: self.adapter.take(status(), scene_shown=True),
                           lambda: self.adapter.entered(status()), self.adapter.prepare_return,
                           lambda: self.adapter.handoff(status()), lambda: self.adapter.restore(status())):
                try:
                    action()
                except RuntimeError as error:
                    failures.append(str(error))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(failures, ["Story mailbox must run on the native story thread"] * 5)
        self.bridge.take_story_command.assert_not_called()
