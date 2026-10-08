"""Check the native recipe's thread, save, failure and recovery boundaries."""

import os
import pickle
import sys
import textwrap
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from runtime.app_story import (
    NativeStory, SAVE_SLOT, STORY_ID, configure_save_location, saved_state, validate_state,
)

ROOT = Path(__file__).resolve().parents[1]


class Jump(BaseException):
    """A native flow transfer is not an operation failure."""


class Loaded(BaseException):
    """Match pinned Ren'Py's successful UnfreezeException control transfer."""


class SavedStateTests(unittest.TestCase):
    def test_saved_state_is_plain_and_contains_no_live_revision_or_route(self):
        for state in (saved_state(), saved_state("active"), saved_state("completed", "Kept the note.")):
            with self.subTest(phase=state["phase"]):
                self.assertEqual(pickle.loads(pickle.dumps(state)), state)
                self.assertEqual(set(state), {"version", "story_id", "phase", "value"})
                self.assertEqual(validate_state(state), state)
                self.assertIsNot(validate_state(state), state)

    def test_invalid_missing_future_or_foreign_state_is_rejected(self):
        valid = saved_state("active")
        bad = (None, {}, {**valid, "version": 2}, {**valid, "version": True},
               {**valid, "story_id": "observatory"}, {**valid, "phase": "paused"},
               {**valid, "value": []}, {**valid, "value": "Not complete"},
               {**valid, "revision": 8}, {**valid, "phase": "completed"},
               {**valid, "phase": "completed", "value": ""})
        for state in bad:
            with self.subTest(state=state), self.assertRaises(ValueError):
                validate_state(state)

    def test_native_selected_save_root_is_namespaced_once(self):
        resolver = Mock(return_value="/selected/native/saves")
        renpy = types.SimpleNamespace(config=types.SimpleNamespace(savedir=None, gamedir="/project/game"),
                                      __main__=types.SimpleNamespace(path_to_saves=resolver))
        self.assertEqual(configure_save_location(renpy), "/selected/native/saves/app-starter")
        resolver.assert_called_once_with("/project/game", "sdk-runner-integration")
        self.assertEqual(configure_save_location(renpy), "/selected/native/saves/app-starter")
        resolver.assert_called_once()

    def test_early_custom_native_save_root_is_kept_as_namespace_parent(self):
        resolver = Mock()
        renpy = types.SimpleNamespace(config=types.SimpleNamespace(savedir="/custom/saves", gamedir="/game"),
                                      __main__=types.SimpleNamespace(path_to_saves=resolver))
        self.assertEqual(configure_save_location(renpy), "/custom/saves/app-starter")
        resolver.assert_not_called()


class NativeStoryTests(unittest.TestCase):
    def setUp(self):
        self.status = {"phase": "ready", "revision": 1, "resume_kind": "unavailable",
                       "showing_story": False, "busy": False, "result": None}
        self.session = Mock()
        self.session.status.side_effect = lambda: dict(self.status)
        self.session.take_request.return_value = None
        self.session.finish.return_value = True
        self.session.restore.return_value = 10
        self.session.complete.return_value = True
        self.store = types.SimpleNamespace(_app_recipe_state=saved_state(),
                                           _interlude_revision=42, _tactics_view=object())
        self.renpy = types.SimpleNamespace(store=self.store, can_load=Mock(return_value=False),
                                          slot_json=Mock(return_value={}), load=Mock(),
                                          unlink_save=Mock(), set_return_stack=Mock(),
                                          jump=Mock(side_effect=Jump), end_interaction=Mock())
        self.bridge = Mock()
        self.bridge.save_status.return_value = {"available": True}
        self.bridge.begin_app_story_load.return_value = True
        self.bridge.end_app_story_load.return_value = True
        self.story = Mock()
        self.original_poll_choice = Mock()
        self.native = NativeStory(self.renpy, self.session, self.bridge, self.story,
                                  self.original_poll_choice)
        self.native.revision = 1

    def command(self, action, replace=False):
        value = {"story_id": STORY_ID, "revision": 1, "action": action, "command_id": 15,
                 "replace": replace}
        self.session.take_request.side_effect = [value, None]
        return value

    def checkpoint(self, phase="active"):
        self.renpy.can_load.return_value = True
        self.renpy.slot_json.return_value = {"app_story": saved_state(phase)}

    def test_checkpoint_requires_native_availability_and_matching_active_metadata(self):
        self.assertFalse(self.native.checkpoint_available())
        self.renpy.slot_json.assert_not_called()
        self.checkpoint()
        self.assertTrue(self.native.checkpoint_available())
        self.renpy.can_load.assert_called_with(SAVE_SLOT)
        for metadata in ({}, {"app_story": saved_state()},
                         {"app_story": saved_state("completed", "Done")},
                         {"app_story": {**saved_state("active"), "version": 2}}):
            self.renpy.slot_json.return_value = metadata
            self.assertFalse(self.native.checkpoint_available())

    def test_startup_discovery_does_not_restore_or_cancel_an_early_command(self):
        self.checkpoint()
        self.native.enter_home()
        self.session.initialize_saved.assert_called_once_with(True)
        self.session.restore.assert_not_called()
        self.session.take_request.assert_not_called()
        self.renpy.jump.assert_not_called()

    def test_failed_discovery_can_still_publish_native_readiness(self):
        self.renpy.can_load.side_effect = OSError("Unavailable")
        with self.assertLogs(level="ERROR"), patch("builtins.print") as output:
            self.native.enter_home()
        self.session.initialize_saved.assert_not_called()
        self.assertTrue(any("SDK_RUNNER_RENPY_READY" in call.args[0] for call in output.call_args_list))

    def test_start_runs_native_flow_once_with_a_fresh_generation_and_plain_state(self):
        self.command("start")
        self.status.update(phase="active", revision=2, resume_kind="live", showing_story=True)
        with self.assertRaises(Jump):
            self.native.poll()
        self.assertEqual(self.native.revision, 2)
        self.assertEqual(self.store._app_recipe_state, saved_state("active"))
        self.assertIsNone(self.store._interlude_revision)
        self.assertIsNone(self.store._tactics_view)
        self.story.reset.assert_called_once()
        self.renpy.set_return_stack.assert_called_once_with([])
        self.renpy.jump.assert_called_once_with("app_recipe_start")
        self.native.poll()
        self.renpy.jump.assert_called_once()

    def test_checkpoint_found_after_early_start_requires_replacement_confirmation(self):
        self.checkpoint()
        self.command("start")
        self.native.poll()
        self.session.finish.assert_called_once_with(
            15, success=False, message="A saved story exists. Confirm before starting again.")
        self.renpy.jump.assert_not_called()
        self.renpy.unlink_save.assert_not_called()
        self.story.reset.assert_not_called()
        self.assertEqual(self.store._app_recipe_state, saved_state())

    def test_confirmed_start_can_replace_the_recoverable_story(self):
        self.checkpoint()
        self.command("start", replace=True)
        with self.assertRaises(Jump):
            self.native.poll()
        self.session.finish.assert_called_once_with(15, message="Story started.")
        self.renpy.unlink_save.assert_called_once_with("_reload-1")

    def test_failed_native_checkpoint_check_releases_start_without_changing_progress(self):
        self.command("start")
        self.renpy.slot_json.side_effect = OSError("Unreadable")
        self.renpy.can_load.return_value = True
        with self.assertLogs(level="ERROR"):
            self.native.poll()
        self.assertFalse(self.session.finish.call_args.kwargs["success"])
        self.story.reset.assert_not_called()
        self.renpy.jump.assert_not_called()

    def test_failed_recovery_cleanup_preserves_current_story_and_releases_start(self):
        self.command("start")
        self.renpy.unlink_save.side_effect = OSError("Read only")
        with self.assertLogs(level="ERROR"):
            self.native.poll()
        self.assertFalse(self.session.finish.call_args.kwargs["success"])
        self.story.reset.assert_not_called()
        self.renpy.set_return_stack.assert_not_called()

    def test_stale_finish_cannot_replace_native_flow_or_interlude(self):
        self.command("start")
        self.session.finish.return_value = False
        self.native.poll()
        self.renpy.jump.assert_not_called()
        self.story.reset.assert_not_called()
        self.assertEqual(self.store._interlude_revision, 42)

    def test_return_and_live_resume_only_acknowledge_the_existing_interaction(self):
        self.status.update(phase="active", resume_kind="live", showing_story=True)
        for action in ("return", "resume"):
            with self.subTest(action=action):
                self.session.take_request.side_effect = None
                self.session.take_request.return_value = self.command(action)
                self.native.poll()
        self.renpy.load.assert_not_called()
        self.renpy.jump.assert_not_called()
        self.renpy.end_interaction.assert_not_called()
        self.renpy.unlink_save.assert_not_called()
        self.bridge.assert_not_called()
        self.story.consume.assert_not_called()
        self.story.reset.assert_not_called()

    def test_saved_resume_keeps_pending_id_until_native_after_load(self):
        self.status["resume_kind"] = "saved"
        self.checkpoint()
        self.command("resume")
        self.renpy.load.side_effect = Loaded
        with self.assertRaises(Loaded):
            self.native.poll()
        self.assertEqual(self.native.resume_command_id, 15)
        self.session.finish.assert_not_called()
        self.renpy.load.assert_called_once_with(SAVE_SLOT)
        self.bridge.begin_app_story_load.assert_called_once_with(15)
        self.bridge.end_app_story_load.assert_called_once_with(15)
        self.store._app_recipe_state = saved_state("active")
        self.native.restore()
        self.assertEqual(self.native.revision, 10)
        self.assertIsNone(self.native.resume_command_id)
        self.session.restore.assert_called_once_with(
            phase="active", resume_kind="live", showing_story=True, result=None,
            message="Loaded the native story checkpoint.", command_id=15)

    def test_saved_resume_keeps_native_prompt_visible_until_the_user_declines(self):
        self.status["resume_kind"] = "saved"
        self.checkpoint()
        self.command("resume")
        self.bridge.presentation.return_value = "page"
        entered, declined = threading.Event(), threading.Event()
        errors = []

        def begin(command_id):
            self.bridge.presentation.return_value = "scene"
            return True

        def end(command_id):
            self.bridge.presentation.return_value = "page"
            return True

        def native_prompt(slot):
            self.assertEqual(threading.get_ident(), self.native.thread_id)
            entered.set()
            self.assertTrue(declined.wait(5), "The prompt observer did not respond")

        def observe_prompt():
            try:
                self.assertTrue(entered.wait(5), "The native prompt did not open")
                self.assertEqual(self.bridge.presentation(), "scene")
                self.assertEqual(self.native.resume_command_id, 15)
                self.bridge.end_app_story_load.assert_not_called()
                self.session.finish.assert_not_called()
            except BaseException as error:
                errors.append(error)
            finally:
                declined.set()

        self.bridge.begin_app_story_load.side_effect = begin
        self.bridge.end_app_story_load.side_effect = end
        self.renpy.load.side_effect = native_prompt
        observer = threading.Thread(target=observe_prompt)
        observer.start()
        try:
            self.native.poll()
        finally:
            declined.set()
            observer.join(timeout=5)
        self.assertFalse(observer.is_alive())
        self.assertFalse(errors, errors)
        self.assertEqual(self.bridge.presentation(), "page")
        self.session.finish.assert_called_once_with(15, success=False, message="Resume cancelled.")
        self.bridge.end_app_story_load.assert_called_once_with(15)
        self.session.restore.assert_not_called()

    def test_denied_load_presentation_never_opens_or_releases_someone_elses_prompt(self):
        self.status["resume_kind"] = "saved"
        self.checkpoint()
        self.command("resume")
        self.bridge.begin_app_story_load.return_value = False
        self.native.poll()
        self.bridge.begin_app_story_load.assert_called_once_with(15)
        self.bridge.end_app_story_load.assert_not_called()
        self.renpy.load.assert_not_called()
        self.session.finish.assert_called_once_with(
            15, success=False, message="Could not show the saved story. Please try again.")
        self.assertIsNone(self.native.resume_command_id)

    def test_successful_load_releases_presentation_after_the_pending_ack_is_consumed(self):
        self.status["resume_kind"] = "saved"
        self.checkpoint()
        self.command("resume")

        def loaded(slot):
            self.store._app_recipe_state = saved_state("active")
            self.native.restore()
            raise Loaded()

        def end(command_id):
            self.assertEqual(self.native.revision, 10)
            self.assertIsNone(self.native.resume_command_id)
            self.session.restore.assert_called_once()
            return True

        self.renpy.load.side_effect = loaded
        self.bridge.end_app_story_load.side_effect = end
        with self.assertRaises(Loaded):
            self.native.poll()
        self.session.finish.assert_not_called()
        self.bridge.end_app_story_load.assert_called_once_with(15)

    def test_declined_native_load_releases_resume_without_claiming_restore(self):
        self.status["resume_kind"] = "saved"
        self.checkpoint()
        self.command("resume")
        self.native.poll()
        self.session.finish.assert_called_once_with(15, success=False, message="Resume cancelled.")
        self.assertIsNone(self.native.resume_command_id)
        self.session.restore.assert_not_called()
        self.bridge.end_app_story_load.assert_called_once_with(15)

    def test_failed_native_load_releases_resume_without_claiming_restore(self):
        self.status["resume_kind"] = "saved"
        self.checkpoint()
        self.command("resume")
        self.renpy.load.side_effect = OSError("Corrupt save")
        with self.assertLogs(level="ERROR"):
            self.native.poll()
        self.assertFalse(self.session.finish.call_args.kwargs["success"])
        self.assertIsNone(self.native.resume_command_id)
        self.session.restore.assert_not_called()
        self.bridge.end_app_story_load.assert_called_once_with(15)

    def test_unconfirmed_saved_checkpoint_never_calls_native_load(self):
        self.status["resume_kind"] = "saved"
        self.command("resume")
        with self.assertLogs(level="ERROR"):
            self.native.poll()
        self.renpy.load.assert_not_called()
        self.assertFalse(self.session.finish.call_args.kwargs["success"])
        self.bridge.begin_app_story_load.assert_not_called()
        self.bridge.end_app_story_load.assert_not_called()

    def test_automatic_restore_keeps_app_navigation_intent_outside_the_snapshot(self):
        self.store._app_recipe_state = saved_state("active")
        self.native.restore()
        options = self.session.restore.call_args.kwargs
        self.assertIsNone(options["command_id"])
        self.assertFalse(options["showing_story"])
        self.status["showing_story"] = True
        self.native.restore()
        self.assertTrue(self.session.restore.call_args.kwargs["showing_story"])
        self.assertEqual(self.store._app_recipe_state, saved_state("active"))

    def test_completed_recovery_publishes_plain_result_with_fresh_revision(self):
        self.store._app_recipe_state = saved_state("completed", "Kept the note.")
        self.native.restore()
        options = self.session.restore.call_args.kwargs
        self.assertEqual(options["phase"], "completed")
        self.assertEqual(options["result"], {"story_id": STORY_ID, "outcome": "completed", "value": "Kept the note."})
        self.assertEqual(options["resume_kind"], "unavailable")
        self.assertFalse(options["showing_story"])

    def test_unsupported_native_recovery_returns_home_with_released_controls(self):
        self.store._app_recipe_state = {**saved_state("active"), "version": 2}
        self.native.resume_command_id = 15
        with self.assertLogs(level="ERROR"), self.assertRaises(Jump):
            self.native.restore()
        self.session.finish.assert_called_once_with(
            15, success=False, message="This saved story is unsupported. Your app data is kept.")
        self.assertEqual(self.session.restore.call_args.kwargs["phase"], "ready")
        self.assertEqual(self.store._app_recipe_state, saved_state())
        self.assertIsNone(self.store._interlude_revision)
        self.story.reset.assert_called_once()
        self.renpy.jump.assert_called_once_with("app_recipe_home")

    def test_save_metadata_contains_only_validated_replace_only_plain_state(self):
        self.store._app_recipe_state = saved_state("active")
        metadata = {"scene_title": "The Lighthouse Note"}
        self.native.save_metadata(metadata)
        self.assertEqual(metadata["app_story"], saved_state("active"))
        self.assertIsNot(metadata["app_story"], self.store._app_recipe_state)
        self.session.status.assert_not_called()
        self.renpy.can_load.assert_not_called()

    def test_return_holds_selected_interlude_before_android_surface_changes(self):
        self.status.update(phase="active", showing_story=False, busy=False)
        self.native.poll_choice()
        self.original_poll_choice.assert_not_called()
        self.status.update(showing_story=True, busy=True)
        self.native.poll_choice()
        self.original_poll_choice.assert_not_called()
        self.status["busy"] = False
        self.native.poll_choice()
        self.original_poll_choice.assert_called_once()

    def test_pending_or_stale_completion_keeps_the_native_waiting_context(self):
        self.native.prepare_completion("Kept the note.")
        self.session.complete.return_value = False
        self.native.finish_completion()
        self.renpy.end_interaction.assert_not_called()
        self.bridge.update_save_status.assert_not_called()
        self.renpy.unlink_save.assert_not_called()

    def test_confirmed_completion_returns_to_home_and_keeps_the_manual_bookmark(self):
        self.native.prepare_completion("Shared the note.")
        self.renpy.can_load.return_value = True
        self.native.finish_completion()
        self.session.complete.assert_called_once_with(1, "Shared the note.", saved_available=False)
        self.renpy.end_interaction.assert_called_once_with(True)
        self.renpy.unlink_save.assert_not_called()
        self.bridge.update_save_status.assert_called_once_with(
            True, "Story complete. Your manual bookmark is kept.")
        self.native.finish_completion()
        self.renpy.end_interaction.assert_called_once()

    def test_completion_exposes_only_a_confirmed_active_manual_checkpoint(self):
        self.native.prepare_completion("Kept the note.")
        self.checkpoint()
        self.native.finish_completion()
        self.session.complete.assert_called_once_with(
            1, "Kept the note.", saved_available=True)

    def test_completed_recovery_keeps_immediate_saved_resume_when_confirmed(self):
        self.store._app_recipe_state = saved_state("completed", "Kept the note.")
        self.checkpoint()
        self.native.restore()
        self.assertEqual(self.session.restore.call_args.kwargs["resume_kind"], "saved")

    def test_home_recovery_keeps_confirmed_manual_resume_without_forcing_story(self):
        self.store._app_recipe_state = saved_state()
        self.checkpoint()
        self.native.restore()
        options = self.session.restore.call_args.kwargs
        self.assertEqual(options["phase"], "ready")
        self.assertEqual(options["resume_kind"], "saved")
        self.assertFalse(options["showing_story"])

    def test_completed_native_recovery_releases_wait_without_republishing_result(self):
        value = "Kept the note."
        self.native.prepare_completion(value)
        self.session.complete.return_value = False
        self.status.update(phase="completed", result={"story_id": STORY_ID, "outcome": "completed", "value": value})
        self.native.finish_completion()
        self.renpy.end_interaction.assert_called_once_with(True)
        self.native.finish_completion()
        self.renpy.end_interaction.assert_called_once()

    def test_old_completed_generation_cannot_release_the_new_wait(self):
        value = "Kept the note."
        self.native.prepare_completion(value)
        self.session.complete.return_value = False
        self.status.update(phase="completed", revision=2,
                           result={"story_id": STORY_ID, "outcome": "completed", "value": value})
        self.native.finish_completion()
        self.renpy.end_interaction.assert_not_called()

    def test_bookmark_check_failure_does_not_trap_a_confirmed_completion(self):
        self.native.prepare_completion("Kept the note.")
        self.renpy.can_load.side_effect = OSError("Unreadable")
        with self.assertLogs(level="ERROR"):
            self.native.finish_completion()
        self.renpy.end_interaction.assert_called_once_with(True)
        self.bridge.update_save_status.assert_called_once_with(
            True, "Story complete. Could not check the manual bookmark.")

    def test_ui_worker_cannot_execute_native_flow_or_restore(self):
        errors = []

        def worker():
            for method in (self.native.poll, self.native.restore, self.native.enter_home,
                           self.native.checkpoint_available, self.native.finish_completion):
                try:
                    method()
                except RuntimeError as error:
                    errors.append(str(error))

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=5)
        self.assertEqual(len(errors), 5)
        self.session.take_request.assert_not_called()
        self.renpy.can_load.assert_not_called()


class OptionalEntryTests(unittest.TestCase):
    def test_story_mode_does_not_configure_recipe_paths_callbacks_or_entry(self):
        script = (ROOT / "game/app_starter.rpy").read_text()
        early = textwrap.dedent(script.split("python early:\n", 1)[1].split("\ninit 1 python:", 1)[0])
        init = textwrap.dedent(script.split("init 1 python:\n", 1)[1].split("\ndefault ", 1)[0])
        config = types.SimpleNamespace(savedir="/observatory/saves", label_overrides={},
                                       save_json_callbacks=[], after_load_callbacks=[])
        layout = Mock()
        namespace = {"renpy": types.SimpleNamespace(config=config), "config": config, "os": os,
                     "layout": layout}
        with patch.dict(sys.modules, {"project_config": types.SimpleNamespace(STARTUP_TEMPLATE="story")}):
            exec(compile(early, "app_starter early", "exec"), namespace)
            exec(compile(init, "app_starter init", "exec"), namespace)
        self.assertEqual(config.savedir, "/observatory/saves")
        self.assertEqual(config.label_overrides, {})
        self.assertEqual(config.save_json_callbacks, [])
        self.assertEqual(config.after_load_callbacks, [])
        layout.screen_yesno_prompt.assert_not_called()

    def test_app_mode_installs_the_sdk_native_confirmation_adapter(self):
        script = (ROOT / "game/app_starter.rpy").read_text()
        init = textwrap.dedent(script.split("init 1 python:\n", 1)[1].split("\ndefault ", 1)[0])
        config = types.SimpleNamespace(savedir="/app/saves", label_overrides={},
                                       save_json_callbacks=[], after_load_callbacks=[])
        layout = Mock()
        app = types.SimpleNamespace(bind=Mock(), native=Mock(), SAVE_SLOT=SAVE_SLOT)
        session = object()
        namespace = {"renpy": types.SimpleNamespace(config=config), "config": config, "os": os,
                     "layout": layout, "sdk_bridge": object(), "story": object(),
                     "poll_story_choice": Mock()}
        with patch.dict(sys.modules, {
                "project_config": types.SimpleNamespace(STARTUP_TEMPLATE="app"),
                "app_story": app, "app_session": types.SimpleNamespace(session=session)}):
            # The early block normally imports the build-selected configuration.
            exec("import project_config", namespace)
            exec(compile(init, "app_starter init", "exec"), namespace)
        layout.screen_yesno_prompt.assert_called_once_with()
        self.assertEqual(config.label_overrides, {"start": "app_recipe_entry"})
        self.assertEqual(config.after_load_callbacks, [app.native.restore])


if __name__ == "__main__":
    unittest.main()
