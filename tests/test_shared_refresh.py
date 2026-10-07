"""Check the real Ren'Py timer callback's idle and quit behavior."""

import sys
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from runtime.renfletpy import SaveState

SCRIPT = Path(__file__).resolve().parents[1] / "game/script.rpy"


class SharedRefreshTests(unittest.TestCase):
    def setUp(self):
        self.bridge = types.ModuleType("sdk_bridge")
        self.bridge.quitting = Mock(return_value=False)
        self.bridge.counter = Mock(return_value=0)
        self.bridge.presentation = Mock(return_value="scene")
        self.bridge.stop = Mock()
        self.bridge.take_save_request = Mock(return_value=None)
        self.bridge.update_save_status = Mock()
        self.bridge.initialize_save_status = Mock()
        self.bridge.resume_story = Mock()
        self.bridge.publish_transcript = Mock()
        self.bridge.save_status = Mock(return_value={"busy": False})
        self.bridge.reading_status = Mock(return_value={"busy": False})
        self.bridge.initialize_reading = Mock()
        self.bridge.take_reading_request = Mock(return_value=None)
        self.bridge.update_reading_status = Mock()
        self.renpy = types.SimpleNamespace(android=False, restart_interaction=Mock(),
                                          quit=Mock(side_effect=SystemExit), end_interaction=Mock(),
                                          full_restart=Mock(side_effect=SystemExit),
                                          can_load=Mock(return_value=False), take_screenshot=Mock(),
                                          unlink_save=Mock(),
                                          save=Mock(), load=Mock(), save_persistent=Mock(), retain_after_load=Mock(),
                                          filter_text_tags=Mock(side_effect=lambda text, **kwargs: text))
        self.story = types.SimpleNamespace(restarting=Mock(return_value=False),
                                           consume=Mock(return_value=None), reset=Mock(), close=Mock(),
                                           snapshot=Mock(return_value={"saved": "snapshot"}),
                                           restore=Mock(return_value=81), current=Mock(return_value=None))
        renfletpy = types.ModuleType("renfletpy")
        renfletpy.story = self.story
        renfletpy.SaveState = SaveState
        code = SCRIPT.read_text().split("init python:\n", 1)[1].split("\nscreen integration(", 1)[0]
        self.namespace = {"renpy": self.renpy, "config": types.SimpleNamespace(quit_callbacks=[],
                                                                                 after_load_callbacks=[]),
                          "scene_title": "Observatory", "_interlude_revision": 42,
                          "persistent": types.SimpleNamespace(renfletpy_large_text=False),
                          "_preferences": types.SimpleNamespace(text_cps=0),
                          "_history_list": [], "narrator": types.SimpleNamespace(add_history=Mock())}
        with patch.dict(sys.modules, {"sdk_bridge": self.bridge, "renfletpy": renfletpy}):
            exec(compile(textwrap.dedent(code), str(SCRIPT), "exec"), self.namespace)
        self.refresh = self.namespace["refresh_shared_state"]

    def test_idle_polls_do_not_restart_and_changed_counter_does(self):
        self.refresh()
        self.renpy.restart_interaction.assert_called_once()
        for _ in range(100):
            self.refresh()
        self.renpy.restart_interaction.assert_called_once()
        self.bridge.counter.return_value = 1
        self.refresh()
        self.assertEqual(self.renpy.restart_interaction.call_count, 2)

    def test_quit_is_checked_before_counter_or_render_work(self):
        self.bridge.quitting.return_value = True
        with self.assertRaises(SystemExit):
            self.refresh()
        self.bridge.counter.assert_not_called()
        self.renpy.restart_interaction.assert_not_called()

    def test_timer_does_not_force_an_update_when_callback_is_idle(self):
        line = next(line for line in SCRIPT.read_text().splitlines() if line.strip().startswith("timer "))
        function = Mock(return_value=None)
        eval(line.split("action ", 1)[1], {"Function": function,
                                         "refresh_shared_state": self.refresh})
        function.assert_called_once_with(self.refresh, _update_screens=False)

    def test_presentation_change_refreshes_without_fabricating_a_counter_change(self):
        self.refresh()
        self.bridge.presentation.return_value = "diagnostics"
        self.refresh()
        self.assertEqual(self.renpy.restart_interaction.call_count, 2)

    def test_choice_returns_to_renpy_and_is_not_polled_as_a_renderer_action(self):
        self.story.consume.return_value = "sky"
        self.story.current.return_value = types.SimpleNamespace(
            speaker="Mira", text="Where next?", choices=(("sky", "Sky"),), selected="sky")
        self.namespace["poll_story_choice"]()
        self.story.consume.assert_called_once_with(42)
        self.renpy.end_interaction.assert_called_once_with("sky")
        self.story.close.assert_called_once_with(42)
        self.namespace["narrator"].add_history.assert_called_once_with(
            "interlude", "Mira", "Where next?", renfletpy_result="Sky")

    def test_replay_restarts_on_the_story_thread_before_reading_a_choice(self):
        self.story.restarting.return_value = True
        with self.assertRaises(SystemExit):
            self.namespace["poll_story_choice"]()
        self.story.reset.assert_called_once()
        self.renpy.full_restart.assert_called_once()
        self.story.consume.assert_not_called()

    def test_pending_save_keeps_a_delayed_completion_in_the_waiting_native_context(self):
        self.bridge.save_status.return_value = {"busy": True}
        self.story.consume.return_value = "quit"
        self.namespace["poll_story_choice"]()
        self.story.consume.assert_not_called()
        self.renpy.end_interaction.assert_not_called()
        self.namespace["narrator"].add_history.assert_not_called()

    def test_menus_and_diagnostics_hold_a_completed_result_until_story_resume(self):
        self.story.consume.return_value = "sky"
        self.story.current.return_value = types.SimpleNamespace(
            speaker="Mira", text="Where next?", choices=(("sky", "Sky"),), selected="sky")
        for presentation in ("page", "diagnostics"):
            self.bridge.presentation.return_value = presentation
            self.namespace["poll_story_choice"]()
        self.story.consume.assert_not_called()
        self.renpy.end_interaction.assert_not_called()
        self.bridge.presentation.return_value = "interlude"
        self.namespace["poll_story_choice"]()
        self.renpy.end_interaction.assert_called_once_with("sky")

    def test_reading_changes_are_persisted_on_the_native_timer_and_not_in_the_save_snapshot(self):
        self.bridge.take_reading_request.return_value = ("large_text", True)
        self.refresh()
        self.assertTrue(self.namespace["persistent"].renfletpy_large_text)
        self.renpy.save_persistent.assert_called_once()
        self.renpy.save.assert_not_called()
        self.bridge.update_reading_status.assert_called_once_with(
            True, "instant", "Reading choice kept for your next visit.")
        self.bridge.take_reading_request.return_value = ("text_speed", "animated")
        self.refresh()
        self.assertEqual(self.namespace["_preferences"].text_cps, 30)

    def test_failed_reading_write_restores_live_preferences_and_releases_controls(self):
        self.bridge.take_reading_request.return_value = ("text_speed", "animated")
        self.renpy.save_persistent.side_effect = OSError("disk full")
        with self.assertLogs(level="ERROR"):
            self.refresh()
        self.assertEqual(self.namespace["_preferences"].text_cps, 0)
        self.bridge.update_reading_status.assert_called_once_with(
            False, "instant", "Could not keep that choice. Please try again.")

    def test_load_republishes_current_reading_preferences_even_when_saved_timer_is_initialized(self):
        self.namespace["_reading_initialized"] = True
        self.namespace["persistent"].renfletpy_large_text = True
        self.namespace["_preferences"].text_cps = 30
        self.namespace["_renfletpy_saved_state"] = {"saved": "snapshot"}
        self.namespace["restore_saved_interlude"]()
        self.bridge.initialize_reading.assert_called_once_with(True, "animated")
        self.refresh()
        self.bridge.initialize_reading.assert_called_once()  # No idle republishing.

    def test_replay_also_runs_during_normal_renpy_dialogue(self):
        self.story.restarting.return_value = True
        with self.assertRaises(SystemExit):
            self.refresh()
        self.renpy.full_restart.assert_called_once()
        self.story.consume.assert_not_called()

    def test_save_delegates_serialization_to_native_renpy(self):
        self.refresh()  # Discover the native save slot on the Ren'Py thread.
        self.bridge.take_save_request.return_value = "save"
        events = []
        self.renpy.take_screenshot.side_effect = lambda: events.append("screenshot")
        self.renpy.save.side_effect = lambda *args, **kwargs: events.append("save")
        self.refresh()
        self.assertEqual(events, ["screenshot", "save"])
        self.story.snapshot.assert_not_called()
        self.renpy.save.assert_called_once_with("renfletpy-quick", extra_info="Observatory")
        self.assertTrue(self.bridge.update_save_status.call_args.args[0])

    def test_successful_load_control_transfer_is_not_caught_as_a_save_failure(self):
        self.refresh()
        self.renpy.can_load.return_value = True
        self.bridge.take_save_request.return_value = "load"
        class LoadControlTransfer(BaseException):
            pass
        self.renpy.load.side_effect = LoadControlTransfer
        self.bridge.update_save_status.reset_mock()
        with self.assertRaises(LoadControlTransfer):
            self.refresh()
        self.bridge.update_save_status.assert_not_called()

    def test_load_callback_replaces_the_revision_before_the_restored_screen_polls(self):
        saved = {"progress": ["deneb"]}
        self.namespace["_renfletpy_saved_state"] = saved
        callback, = self.namespace["config"].after_load_callbacks
        callback()
        self.story.restore.assert_called_once_with(saved)
        self.namespace["poll_story_choice"]()
        self.story.consume.assert_called_once_with(81)
        self.bridge.resume_story.assert_called_once()
        self.renpy.unlink_save.assert_called_once_with("_reload-1")
        self.assertIsInstance(self.namespace["_renfletpy_saved_state"], SaveState)

    def test_native_serialized_state_restores_before_input_and_history_are_published(self):
        saved = SaveState()
        saved.data = {"active": True, "history": ["saved"]}
        self.namespace["_renfletpy_saved_state"] = saved
        self.namespace["restore_saved_interlude"]()
        self.story.restore.assert_called_once_with(saved.data)
        self.assertIs(self.namespace["_renfletpy_saved_state"], saved)
        self.bridge.publish_transcript.assert_called_once_with([])

    def test_old_background_save_without_interlude_data_restarts_instead_of_hanging(self):
        self.namespace["_renfletpy_saved_state"] = None
        with self.assertRaises(SystemExit):
            self.namespace["restore_saved_interlude"]()
        self.renpy.full_restart.assert_called_once()
        self.story.restore.assert_not_called()
        self.renpy.unlink_save.assert_called_once_with("_reload-1")

    def test_history_publishes_native_lines_and_the_pending_panel_in_order(self):
        self.namespace["_history_list"] = [
            types.SimpleNamespace(who="Mira", what="Look up."),
            types.SimpleNamespace(who="Star map", what="Connect stars.", renfletpy_result="Aligned"),
            types.SimpleNamespace(who="Mira", what="We did it."),
        ]
        self.story.current.return_value = types.SimpleNamespace(
            speaker="Journal", text="Pick a memory.", choices=(("sky", "Sky"),), selected=None)
        self.namespace["publish_story_history"]()
        self.bridge.publish_transcript.assert_called_once_with([
            ("Mira", "Look up.", ""), ("Star map", "Connect stars.", "Aligned"),
            ("Mira", "We did it.", ""), ("Journal", "Pick a memory.", ""),
        ])

    def test_failed_save_releases_busy_state_without_reporting_success(self):
        self.refresh()
        self.bridge.take_save_request.return_value = "save"
        self.renpy.save.side_effect = OSError("disk full")
        with self.assertLogs(level="ERROR"):
            self.refresh()
        available, message = self.bridge.update_save_status.call_args.args
        self.assertFalse(available)
        self.assertEqual(message, "Could not save. Please try again.")

    def test_a_missing_save_or_cancelled_load_releases_the_menu(self):
        self.refresh()
        self.bridge.take_save_request.return_value = "load"
        self.refresh()
        self.renpy.load.assert_not_called()
        self.bridge.update_save_status.assert_called_with(False, "No saved game yet.")
        self.renpy.can_load.return_value = True
        self.refresh()
        self.renpy.load.assert_called_once()
        self.bridge.update_save_status.assert_called_with(True, "Load cancelled.")
