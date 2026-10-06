"""Check the real Ren'Py timer callback's idle and quit behavior."""

import sys
import textwrap
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "game/script.rpy"


class SharedRefreshTests(unittest.TestCase):
    def setUp(self):
        self.bridge = types.ModuleType("sdk_bridge")
        self.bridge.quitting = Mock(return_value=False)
        self.bridge.counter = Mock(return_value=0)
        self.bridge.presentation = Mock(return_value="story")
        self.bridge.stop = Mock()
        self.renpy = types.SimpleNamespace(android=False, restart_interaction=Mock(),
                                          quit=Mock(side_effect=SystemExit), end_interaction=Mock(),
                                          full_restart=Mock(side_effect=SystemExit))
        self.story = types.SimpleNamespace(restarting=Mock(return_value=False),
                                           consume=Mock(return_value=None), reset=Mock())
        renfletpy = types.ModuleType("renfletpy")
        renfletpy.story = self.story
        code = SCRIPT.read_text().split("init python:\n", 1)[1].split("\nscreen integration(", 1)[0]
        self.namespace = {"renpy": self.renpy, "config": types.SimpleNamespace(quit_callbacks=[])}
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
        self.namespace["poll_story_choice"](42)
        self.story.consume.assert_called_once_with(42)
        self.renpy.end_interaction.assert_called_once_with("sky")

    def test_replay_restarts_on_the_story_thread_before_reading_a_choice(self):
        self.story.restarting.return_value = True
        with self.assertRaises(SystemExit):
            self.namespace["poll_story_choice"](42)
        self.story.reset.assert_called_once()
        self.renpy.full_restart.assert_called_once()
        self.story.consume.assert_not_called()
