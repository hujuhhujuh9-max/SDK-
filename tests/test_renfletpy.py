"""Guard the story boundary against stale UI events and concurrent selections."""

import unittest
from concurrent.futures import ThreadPoolExecutor

from runtime.renfletpy import Story


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
