"""Guard the story boundary against stale UI events and concurrent selections."""

import copy
import json
import pickle
import unittest
from concurrent.futures import ThreadPoolExecutor

from unittest.mock import patch

from runtime.renfletpy import SaveState, Story


class StoryTests(unittest.TestCase):
    def setUp(self):
        self.story = Story()

    def test_a_choice_is_consumed_once_and_cannot_be_changed_by_a_second_tap(self):
        revision = self.story.show("Mira", "Where next?", (("sky", "Sky"), ("dome", "Dome")))
        self.assertTrue(self.story.choose(revision, "sky"))
        self.assertFalse(self.story.choose(revision, "dome"))
        self.assertEqual(self.story.consume(revision), "sky")
        self.assertIsNone(self.story.consume(revision))
        self.assertFalse(self.story.choose(revision, "sky"))
        self.assertEqual(self.story.history()[-1].selected, "sky")

    def test_an_old_line_or_replayed_story_cannot_accept_a_delayed_choice(self):
        first = self.story.show("", "First")
        second = self.story.show("", "Second")
        self.assertFalse(self.story.choose(first, "continue"))
        self.story.reset()
        third = self.story.show("", "First again")
        self.assertGreater(third, second)
        self.assertFalse(self.story.choose(second, "continue"))
        self.assertTrue(self.story.choose(third, "continue"))

    def test_wrong_consumer_does_not_steal_a_pending_selection(self):
        revision = self.story.show("", "Continue?")
        self.story.choose(revision, "continue")
        self.assertIsNone(self.story.consume(revision + 1))
        self.assertEqual(self.story.consume(revision), "continue")

    def test_concurrent_taps_have_exactly_one_winner(self):
        revision = self.story.show("Mira", "Pick", (("sky", "Sky"), ("dome", "Dome")))
        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda choice: self.story.choose(revision, choice),
                                        ["sky", "dome"] * 32))
        self.assertEqual(sum(results), 1)
        self.assertIn(self.story.consume(revision), ("sky", "dome"))

    def test_history_and_snapshots_are_stable_and_bounded(self):
        self.story.show("", "Old")
        old = self.story.current()
        for line in range(201):
            self.story.show("", str(line))
        self.assertEqual(old.text, "Old")
        self.assertEqual(len(self.story.history()), 200)
        self.assertEqual(self.story.history()[0].text, "1")

    def test_notifications_can_read_state_and_detach(self):
        observed = []
        detach = self.story.subscribe(lambda: observed.append(self.story.current()))
        revision = self.story.show("Mira", "Hello")
        self.story.choose(revision, "continue")
        self.assertEqual([entry.selected for entry in observed], [None, "continue"])
        detach()
        detach()
        self.story.reset()
        self.assertEqual(len(observed), 2)

    def test_replay_blocks_choices_until_the_story_owner_resets(self):
        revision = self.story.show("", "Hello")
        self.story.request_restart()
        self.assertTrue(self.story.restarting())
        self.assertFalse(self.story.choose(revision, "continue"))
        self.story.reset()
        self.assertFalse(self.story.restarting())
        self.assertEqual(self.story.history(), ())

    def test_invalid_choices_do_not_replace_the_current_line(self):
        self.story.show("", "Keep this")
        for choices in ((), (("x", "X"), ("x", "Again")), (("", "Empty ID"),), (("x",),)):
            with self.subTest(choices=choices), self.assertRaises(ValueError):
                self.story.show("", "Invalid", choices)
            self.assertEqual(self.story.current().text, "Keep this")
        self.assertFalse(self.story.choose(self.story.current().revision, "missing"))

    def test_minigame_requires_the_order_and_returns_one_result(self):
        revision = self.story.minigame("star_map")
        self.assertFalse(self.story.choose(revision, "aligned"))
        self.assertTrue(self.story.tap_star(revision, "altair"))
        self.assertEqual(self.story.current().progress, ())
        self.assertTrue(self.story.tap_star(revision, "deneb"))
        self.assertFalse(self.story.tap_star(revision, "deneb"))
        self.assertTrue(self.story.tap_star(revision, "vega"))
        self.assertEqual(self.story.current().progress, ("deneb", "vega"))
        self.assertIsNone(self.story.consume(revision))
        self.story.tap_star(revision, "altair")
        self.assertEqual(self.story.consume(revision), "aligned")
        self.assertIsNone(self.story.consume(revision))
        self.assertFalse(self.story.tap_star(revision, "altair"))
        self.assertTrue(self.story.close(revision))
        self.assertIsNone(self.story.current())
        self.assertEqual(self.story.history()[-1].selected, "aligned")

    def test_a_closed_or_old_minigame_cannot_affect_the_next_interlude(self):
        first = self.story.minigame("star_map")
        self.story.choose(first, "skipped")
        self.assertEqual(self.story.consume(first), "skipped")
        self.story.close(first)
        second = self.story.minigame("star_map")
        self.assertFalse(self.story.close(first))
        self.assertFalse(self.story.tap_star(first, "deneb"))
        self.assertFalse(self.story.tap_star(second, "missing"))
        self.assertEqual(self.story.current().progress, ())
        with self.assertRaises(ValueError):
            self.story.minigame("missing")

    def test_save_restores_progress_history_and_rejects_controls_from_both_timelines(self):
        panel = self.story.show("Mira", "First stop")
        self.story.choose(panel, "continue")
        self.story.consume(panel)
        self.story.close(panel)
        revision = self.story.minigame("star_map")
        self.story.tap_star(revision, "deneb")
        snapshot = json.loads(json.dumps(self.story.snapshot()))
        self.story.tap_star(revision, "vega")
        restored = self.story.restore(snapshot)
        self.assertGreater(restored, revision)
        self.assertEqual(self.story.current().progress, ("deneb",))
        self.assertEqual(self.story.history()[0].selected, "continue")
        self.assertFalse(self.story.tap_star(revision, "altair"))
        self.assertTrue(self.story.tap_star(restored, "vega"))
        again = self.story.restore(snapshot)
        self.assertFalse(self.story.tap_star(restored, "altair"))
        self.assertTrue(self.story.tap_star(again, "vega"))
        self.story.tap_star(again, "altair")
        self.assertEqual(self.story.consume(again), "aligned")

    def test_a_new_process_can_restore_a_panel_and_a_pending_result_once(self):
        revision = self.story.show("Journal", "Pick a route", (("tower", "Tower"),))
        self.story.choose(revision, "tower")
        restored_story = Story()
        restored = restored_story.restore(self.story.snapshot())
        self.assertEqual(restored_story.consume(restored), "tower")
        self.assertIsNone(restored_story.consume(restored))
        self.assertFalse(restored_story.choose(restored, "tower"))
        restored_story.close(restored)
        self.assertIsNone(restored_story.restore(restored_story.snapshot()))
        self.assertIsNone(restored_story.current())
        self.assertEqual(restored_story.history()[-1].selected, "tower")

    def test_saved_data_is_independent_and_restore_notifies_existing_subscribers(self):
        revision = self.story.minigame("star_map")
        snapshot = self.story.snapshot()
        snapshot["history"][0]["text"] = "Saved copy"
        self.assertNotEqual(self.story.current().text, "Saved copy")
        seen = []
        self.story.subscribe(lambda: seen.append(self.story.current()))
        self.story.request_restart()
        restored = self.story.restore(snapshot)
        self.assertGreater(restored, revision)
        self.assertFalse(self.story.restarting())
        self.assertEqual([item.text for item in seen], ["Saved copy"])

    def test_invalid_or_future_saves_leave_the_live_game_intact(self):
        self.story.minigame("star_map")
        snapshot = self.story.snapshot()
        invalid = [None, {}, {**snapshot, "version": 2}, {**snapshot, "history": []}]
        for field, value in (("selected", "aligned"), ("progress", ["vega"]),
                             ("choices", []), ("revision", 1), ("kind", "unknown")):
            bad = copy.deepcopy(snapshot)
            bad["history"][-1][field] = value
            invalid.append(bad)
        current = self.story.current()
        for saved in invalid:
            with self.subTest(saved=saved), self.assertRaises(ValueError):
                self.story.restore(saved)
            self.assertEqual(self.story.current(), current)

    def test_native_pickle_captures_live_progress_without_a_manual_save_command(self):
        adapter = SaveState()
        with patch("runtime.renfletpy.story", self.story):
            revision = self.story.minigame("star_map")
            self.story.tap_star(revision, "deneb")
            saved = pickle.dumps(adapter)
            self.story.tap_star(revision, "vega")
            loaded = pickle.loads(saved)
            self.assertEqual(loaded.data["history"][-1]["progress"], ("deneb",))
            self.assertEqual(self.story.current().progress, ("deneb", "vega"))
            # Loading a save adapter cannot change the live game before the
            # native after-load callback. Its next save captures the live game.
            again = pickle.loads(pickle.dumps(loaded))
            self.assertEqual(again.data["history"][-1]["progress"], ("deneb", "vega"))

    def test_background_serialization_contains_no_live_locks_or_pending_callbacks(self):
        self.story.show("Journal", "Remember this.")
        self.story.subscribe(lambda: None)
        with patch("runtime.renfletpy.story", self.story), ThreadPoolExecutor(max_workers=1) as executor:
            saved = executor.submit(pickle.dumps, SaveState()).result(timeout=5)
        loaded = pickle.loads(saved)
        target = Story()
        revision = target.restore(loaded.data)
        self.assertEqual(target.current().text, "Remember this.")
        self.assertTrue(target.choose(revision, "continue"))
