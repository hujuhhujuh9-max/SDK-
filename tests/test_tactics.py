"""Exercise stacked surfaces, legal paths, and native-interlude save boundaries."""

import copy
import json
import pickle
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from runtime.renfletpy import SaveState, Story
from runtime.tactics import Board, Cell, GOAL, TacticsState, build_draw_items, compute_movement_field


class TerrainTests(unittest.TestCase):
    def test_solids_replace_ground_but_shelves_keep_walkable_floors_underneath(self):
        board = Board()
        self.assertEqual(len(board.surfaces), 43)
        self.assertFalse(board.exists(Cell(3, 2, 0)))
        self.assertEqual([s.cell.z for s in board.surfaces_at(1, 3)], [0, 1, 2])
        self.assertEqual([s.cell.z for s in board.surfaces_at(3, 2)], [1, 2])

    def test_paths_respect_budget_height_and_blocked_units(self):
        board = Board()
        start = Cell(0, 2, 0)
        field = compute_movement_field(board, start, 5, 1, {Cell(3, 2, 1)})
        path = field.path_to(GOAL)
        self.assertEqual((path[0], path[-1]), (start, GOAL))
        self.assertLessEqual(len(path) - 1, 5)
        for a, b in zip(path, path[1:]):
            self.assertEqual(abs(a.x - b.x) + abs(a.y - b.y), 1)
            self.assertLessEqual(abs(a.z - b.z), 1)
            self.assertNotEqual(b, Cell(3, 2, 1))
        no_jump = compute_movement_field(board, start, 5, 0, set())
        self.assertTrue(all(cell.z == 0 for cell in no_jump.cost))
        self.assertEqual(compute_movement_field(board, start, 0, 1, set()).cost, {start: 0})

    def test_unit_and_cover_order_is_preserved_in_the_face_queue(self):
        items = build_draw_items(TacticsState())
        def index(kind, cell):
            return next(i for i, item in enumerate(items) if item.kind == kind
                        and (item.payload.cell if kind == "unit" else item.payload[0].cell) == cell)
        self.assertLess(index("unit", Cell(3, 2, 1)), index("top", Cell(3, 2, 2)))
        self.assertLess(index("top", Cell(4, 3, 2)), index("unit", Cell(4, 3, 2)))
        self.assertTrue(any(item.kind == "underside" for item in items))


class NativeTacticsTests(unittest.TestCase):
    def setUp(self):
        self.story = Story()
        self.revision = self.story.minigame("tactics")

    def test_goal_requires_a_legal_scout_move_and_returns_once(self):
        self.assertFalse(self.story.choose(self.revision, "reached"))
        self.assertFalse(self.story.select_tactics_unit(self.revision, "guard"))
        self.assertFalse(self.story.move_tactics_unit(self.revision, Cell(0, 0, 2)))
        self.assertFalse(self.story.move_tactics_unit(self.revision, Cell(4, 3, 2)))
        self.assertTrue(self.story.move_tactics_unit(self.revision, GOAL))
        self.assertEqual(self.story.consume(self.revision), "reached")
        self.assertIsNone(self.story.consume(self.revision))
        self.assertFalse(self.story.reset_tactics(self.revision))
        self.assertFalse(self.story.choose(self.revision, "skipped"))
        self.story.close(self.revision)
        self.assertIsNone(self.story.tactics_state())

    def test_reset_restores_positions_and_render_copies_cannot_change_the_live_board(self):
        original = self.story.current()
        private = self.story.tactics_state()
        private.units[1].cell = GOAL
        self.assertEqual(self.story.current(), original)
        self.assertTrue(self.story.move_tactics_unit(self.revision, Cell(0, 4, 0)))
        self.assertTrue(self.story.select_tactics_unit(self.revision, "knight"))
        self.assertTrue(self.story.reset_tactics(self.revision))
        self.assertEqual(self.story.current(), original)

    def test_worker_save_restores_moves_selection_and_rejects_old_controls(self):
        self.story.move_tactics_unit(self.revision, Cell(0, 4, 0))
        self.story.select_tactics_unit(self.revision, "knight")
        expected = self.story.current()
        with patch("runtime.renfletpy.story", self.story), ThreadPoolExecutor(max_workers=1) as executor:
            saved = executor.submit(pickle.dumps, SaveState()).result(timeout=5)
        self.story.reset_tactics(self.revision)
        adapter = pickle.loads(saved)
        revision = self.story.restore(json.loads(json.dumps(adapter.data)))
        self.assertEqual(self.story.current().positions, expected.positions)
        self.assertEqual(self.story.current().selected_unit, "knight")
        self.assertFalse(self.story.move_tactics_unit(self.revision, GOAL))
        self.assertFalse(self.story.select_tactics_unit(self.revision, "scout"))
        self.assertTrue(self.story.select_tactics_unit(revision, "scout"))
        self.assertTrue(self.story.move_tactics_unit(revision, GOAL))
        pending = Story()
        restored = pending.restore(self.story.snapshot())
        self.assertEqual(pending.consume(restored), "reached")
        self.assertIsNone(pending.consume(restored))

    def test_invalid_positions_and_results_leave_the_current_game_intact(self):
        saved = self.story.snapshot()
        invalid = []
        for field, value in (("positions", ()), ("selected_unit", "guard"), ("selected", "reached"),
                             ("choices", (("continue", "Continue"),))):
            bad = copy.deepcopy(saved)
            bad["history"][-1][field] = value
            invalid.append(bad)
        for position in (("scout", 0, 0, 2), ("scout", 0, 1, 0), ("scout", True, 4, 0)):
            bad = copy.deepcopy(saved)
            positions = list(bad["history"][-1]["positions"])
            positions[1] = position
            bad["history"][-1]["positions"] = positions
            invalid.append(bad)
        original = self.story.current()
        for data in invalid:
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.story.restore(data)
            self.assertEqual(self.story.current(), original)

    def test_replay_blocks_native_moves_and_previous_save_formats_still_load(self):
        self.story.request_restart()
        self.assertFalse(self.story.move_tactics_unit(self.revision, GOAL))
        self.story.reset()
        self.story.show("Journal", "An older panel")
        snapshot = self.story.snapshot()
        del snapshot["history"][-1]["positions"]
        del snapshot["history"][-1]["selected_unit"]
        self.story.restore(snapshot)
        self.assertEqual(self.story.current().text, "An older panel")


if __name__ == "__main__":
    unittest.main()
