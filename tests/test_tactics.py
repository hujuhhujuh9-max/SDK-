"""Exercise stacked surfaces, legal paths, and native-interlude save boundaries."""

import copy
import json
import pickle
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from runtime.renfletpy import SaveState, Story
from runtime.tactics import (
    Board, Cell, GOAL, LEVEL_H, TacticsState, TacticsView, build_draw_items,
    camera_bounds, camera_cell, compute_movement_field, point_in_diamond, project,
)


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

    def test_only_solid_terrain_has_filled_faces_and_units_stand_above_it(self):
        for rotation in range(4):
            with self.subTest(rotation=rotation):
                items = build_draw_items(TacticsState(), rotation)
                def index(kind, cell):
                    return next(i for i, item in enumerate(items) if item.kind == kind
                                and item.payload.cell == cell)
                self.assertLess(index("terrain", Cell(3, 2, 1)), index("unit", Cell(3, 2, 1)))
                self.assertEqual({item.kind for item in items}, {"terrain", "wall", "marker", "unit"})
                terrain = [item.payload for item in items if item.kind == "terrain"]
                self.assertEqual(len(terrain), 12)
                self.assertTrue(all(surface.kind == "solid" for surface in terrain))
                self.assertTrue(all(surface.cell.z == 1 for surface in terrain))

    def test_every_camera_orientation_keeps_equal_floor_spacing_and_world_identity(self):
        for rotation in range(4):
            for surface in Board().iter_surfaces():
                cell = surface.cell
                self.assertEqual(camera_cell(camera_cell(cell, rotation), -rotation), cell)
                for mode in ("isometric", "side"):
                    low = project(cell, rotation, mode)
                    high = project(Cell(cell.x, cell.y, cell.z + 1), rotation, mode)
                    self.assertEqual(low[0], high[0])
                    self.assertEqual(low[1] - high[1], LEVEL_H)

    def test_top_down_levels_filter_units_and_markers_but_keep_terrain_footprints(self):
        state = TacticsState()
        for level in range(3):
            items = build_draw_items(state, mode="top_down", level=level)
            units = [item.payload for item in items if item.kind == "unit"]
            self.assertEqual({u.uid for u in units},
                             {u.uid for u in state.units if u.cell.z == level})
            self.assertTrue(all(item.payload[0].cell.z == level
                                for item in items if item.kind == "marker"))
            self.assertEqual(sum(item.kind == "terrain" for item in items), 12 if level < 2 else 0)
            self.assertFalse(any(item.kind == "wall" for item in items))
        with self.assertRaises(ValueError):
            build_draw_items(state, mode="top_down")

    def test_top_down_picking_rotates_cells_and_side_view_cannot_choose_a_row(self):
        for rotation in range(4):
            cell = Cell(0, 4, 1)
            x, y = project(cell, rotation, "top_down")
            self.assertTrue(point_in_diamond(x + 24, y, cell, rotation, "top_down"))
            self.assertFalse(point_in_diamond(x + 80, y, cell, rotation, "top_down"))
            self.assertEqual(project(Cell(0, 4, 0), rotation, "top_down"), (x, y))
            x, y = project(cell, rotation, "side")
            self.assertFalse(point_in_diamond(x, y, cell, rotation, "side"))

    def test_side_terrain_rows_merge_into_one_silhouette_without_repeated_alpha_faces(self):
        state = TacticsState()
        for rotation in range(4):
            items = build_draw_items(state, rotation, "side")
            terrain = [item.payload for item in items if item.kind == "terrain"]
            xs = [project(s.cell, rotation, "side")[0] for s in terrain]
            self.assertEqual(len(xs), len(set(xs)))
            self.assertEqual(sum(item.kind == "wall" for item in items), len(xs))
            self.assertFalse(any(item.kind == "marker" and item.payload[1] for item in items))

    def test_camera_fit_contains_every_grid_and_upright_unit_in_all_modes(self):
        for mode in ("isometric", "top_down", "side"):
            left, top, right, bottom = camera_bounds(mode)
            for rotation in range(4):
                for cell in Board().surfaces:
                    x, y = project(cell, rotation, mode)
                    self.assertTrue(left <= x <= right)
                    self.assertTrue(top <= y - (22 if mode == "top_down" else 80) <= y <= bottom)

    def test_rotated_solid_walls_keep_floor_bands_and_shelves_do_not_hide_them(self):
        state = TacticsState()
        state.board.surfaces.clear()
        state.units.clear()
        state.selected_uid = None
        state.board.add(2, 2, 2, "solid")
        for rotation in range(4):
            # An adjacent shelf has air beneath it, so the solid's wall still
            # needs both floor bands even when that shelf faces the camera.
            front = camera_cell(Cell(2, 2, 2), rotation)
            neighbor = camera_cell(Cell(front.x, front.y + 1, 2), -rotation)
            state.board.add(neighbor.x, neighbor.y, 2, "shelf")
            faces = [item.payload for item in build_draw_items(state, rotation)
                     if item.kind == "wall"]
            self.assertEqual(len(faces), 4)
            self.assertTrue(all(face[2][1] - face[1][1] == LEVEL_H for face in faces))
            state.board.surfaces.pop(neighbor)


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
        self.story.set_tactics_view(self.revision, opacity=0.25, rotation=3, zoom=1.3,
                                    pan_x=50.0, pan_y=-20.0, mode="top_down", level=0)
        expected = self.story.current()
        with patch("runtime.renfletpy.story", self.story), ThreadPoolExecutor(max_workers=1) as executor:
            saved = executor.submit(pickle.dumps, SaveState()).result(timeout=5)
        self.story.reset_tactics(self.revision)
        adapter = pickle.loads(saved)
        revision = self.story.restore(json.loads(json.dumps(adapter.data)))
        self.assertEqual(self.story.current().positions, expected.positions)
        self.assertEqual(self.story.current().selected_unit, "knight")
        self.assertEqual(self.story.tactics_view(), expected.view)
        self.assertFalse(self.story.set_tactics_view(self.revision, opacity=1.0))
        self.assertFalse(self.story.move_tactics_unit(self.revision, GOAL))
        self.assertFalse(self.story.select_tactics_unit(self.revision, "scout"))
        self.assertTrue(self.story.select_tactics_unit(revision, "scout"))
        self.assertTrue(self.story.move_tactics_unit(revision, GOAL))
        pending = Story()
        restored = pending.restore(self.story.snapshot())
        self.assertEqual(pending.consume(restored), "reached")
        self.assertIsNone(pending.consume(restored))

    def test_camera_changes_and_route_reset_preserve_the_other_kind_of_state(self):
        before = self.story.current()
        self.assertTrue(self.story.set_tactics_view(self.revision, opacity=0, rotation=2, zoom=1.5))
        self.assertEqual(self.story.current().positions, before.positions)
        self.assertEqual(self.story.current().selected_unit, before.selected_unit)
        self.assertIsNone(self.story.current().selected)
        view = self.story.tactics_view()
        self.story.move_tactics_unit(self.revision, Cell(0, 4, 0))
        self.story.reset_tactics(self.revision)
        self.assertEqual(self.story.tactics_view(), view)
        self.assertEqual(self.story.current().positions, before.positions)
        self.story.move_tactics_unit(self.revision, GOAL)
        self.assertFalse(self.story.set_tactics_view(self.revision, opacity=1))

    def test_invalid_view_settings_cannot_partially_replace_the_live_story(self):
        saved = self.story.snapshot()
        original = self.story.current()
        for field, value in (("opacity", -0.1), ("opacity", float("nan")), ("opacity", True),
                             ("rotation", 4), ("rotation", 1.0), ("zoom", 0.1),
                             ("pan_x", float("inf")), ("pan_y", 281), ("unknown", 0),
                             ("mode", "perspective"), ("mode", "top_down"),
                             ("level", -1), ("level", 3), ("level", True), ("level", 1.0)):
            with self.subTest(field=field, value=value):
                self.assertFalse(self.story.set_tactics_view(self.revision, **{field: value}))
                bad = copy.deepcopy(saved)
                bad["history"][-1]["view"][field] = value
                with self.assertRaises(ValueError):
                    self.story.restore(bad)
                self.assertEqual(self.story.current(), original)

    def test_old_tactics_save_gets_default_view_and_new_game_does_not_inherit_previous_camera(self):
        self.story.set_tactics_view(self.revision, rotation=1, opacity=1.0)
        saved = self.story.snapshot()
        del saved["history"][-1]["view"]
        self.story.restore(saved)
        self.assertEqual(self.story.tactics_view(), TacticsView())
        self.story.reset()
        self.story.minigame("tactics")
        self.assertEqual(self.story.tactics_view(), TacticsView())

    def test_previous_camera_save_keeps_settings_and_previous_knight_position(self):
        self.story.set_tactics_view(self.revision, rotation=2, opacity=0.6, pan_x=12)
        saved = self.story.snapshot()
        view = saved["history"][-1]["view"]
        del view["mode"], view["level"]
        positions = list(saved["history"][-1]["positions"])
        positions[0] = ("knight", 0, 1, 0)
        saved["history"][-1]["positions"] = positions
        self.story.restore(saved)
        self.assertEqual(self.story.tactics_view(), TacticsView(rotation=2, opacity=0.6, pan_x=12))
        self.assertEqual(self.story.tactics_state().units[0].cell, Cell(0, 1, 0))

    def test_invalid_positions_and_results_leave_the_current_game_intact(self):
        saved = self.story.snapshot()
        invalid = []
        for field, value in (("positions", ()), ("selected_unit", "guard"), ("selected", "reached"),
                             ("choices", (("continue", "Continue"),))):
            bad = copy.deepcopy(saved)
            bad["history"][-1][field] = value
            invalid.append(bad)
        for position in (("scout", 0, 0, 2), ("scout", 0, 5, 0), ("scout", True, 4, 0)):
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
        del snapshot["history"][-1]["view"]
        self.story.restore(snapshot)
        self.assertEqual(self.story.current().text, "An older panel")


if __name__ == "__main__":
    unittest.main()
