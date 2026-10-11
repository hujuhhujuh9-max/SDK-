"""Exercise bounded workloads, state ownership and actual asynchronous jobs."""

import asyncio
import copy
import json
import math
import threading
import unittest
from types import SimpleNamespace

from runtime.scale_activity import migrate_scale_v1, validate_scale_result, validate_scale_state

from runtime.scale_workloads import (
    TableWorkQueue, canvas_command, canvas_primitives, canvas_state,
    edit_table, node_position, pick_node, query_table, table_row, table_state, validate_canvas,
)


class ScaleModelTests(unittest.TestCase):
    def test_activity_validation_and_v1_migration_return_explicit_acceptance(self):
        old = canvas_state()
        del old["revision"], old["input_receipts"]
        restored = migrate_scale_v1(old)
        self.assertIs(validate_scale_state(restored), True)
        result = SimpleNamespace(status="completed", value={
            key: restored[key] for key in ("selected", "camera", "input_receipts")})
        self.assertIs(validate_scale_result(result), True)
        self.assertIs(validate_scale_result(SimpleNamespace(status="cancelled", value={"reason": "user"})), True)
        result.value["camera"]["scale"] = float("nan")
        with self.assertRaises(ValueError):
            validate_scale_result(result)

    def test_canvas_draws_declared_size_and_picks_after_camera_changes(self):
        for tier, expected in (("nominal", 2000), ("stress", 10000)):
            original = canvas_state(tier)
            self.assertEqual(len(list(canvas_primitives(original))), expected)
            changed = canvas_command(original, "pan", {"dx": 35, "dy": -20})
            changed = canvas_command(changed, "zoom", {"factor": 2, "x": 80, "y": 90})
            wx, wy = node_position(42, changed["nodes"])
            camera = changed["camera"]
            self.assertEqual(pick_node(changed, wx * camera["scale"] + camera["x"],
                                       wy * camera["scale"] + camera["y"]), 42)
            self.assertEqual(original["camera"], canvas_state(tier)["camera"])
            self.assertIsNone(pick_node(changed, -1000, -1000))
            self.assertEqual(json.loads(json.dumps(changed)), changed)

    def test_zoom_preserves_the_focal_world_point_and_clamps(self):
        state = canvas_state()
        state = canvas_command(state, "pan", {"dx": 15, "dy": -10})
        fx, fy = 50, 90
        before = ((fx - state["camera"]["x"]) / state["camera"]["scale"],
                  (fy - state["camera"]["y"]) / state["camera"]["scale"])
        state = canvas_command(state, "zoom", {"factor": 1000, "x": fx, "y": fy})
        self.assertEqual(state["camera"]["scale"], 4)
        after = ((fx - state["camera"]["x"]) / state["camera"]["scale"],
                 (fy - state["camera"]["y"]) / state["camera"]["scale"])
        for original, final in zip(before, after):
            self.assertAlmostEqual(original, final)

    def test_invalid_saved_camera_and_selection_are_rejected(self):
        for camera in ({"x": 0, "y": 0, "scale": math.nan},
                       {"x": True, "y": 0, "scale": 1},
                       {"x": 0, "y": 0, "scale": 0},
                       {"x": 0, "y": 0, "scale": 1, "controller": object()}):
            state = canvas_state()
            state["camera"] = camera
            with self.assertRaises(ValueError):
                validate_canvas(state)
        with self.assertRaises(ValueError):
            canvas_command(canvas_state(), "select", {"node": 500})
        with self.assertRaises(ValueError):
            canvas_command(canvas_state(), "zoom", {"factor": math.inf, "x": 0, "y": 0})

    def test_edit_sort_and_filter_cover_all_data_rows(self):
        state = table_state("stress")
        edit_table(state, 99999, "A unique distant edit")
        state["filter"] = "UNIQUE DISTANT"
        self.assertEqual(query_table(state), [99999])
        self.assertEqual(table_row(99999, state)["title"], "A unique distant edit")
        state["filter"] = "Record 0999"
        rows = query_table(state)
        self.assertEqual(len(rows), 99)
        scores = [table_row(index, state)["score"] for index in rows]
        self.assertEqual(scores, sorted(scores))
        state["descending"] = True
        self.assertEqual(query_table(state), list(reversed(rows)))
        state["draft"] = "Still being typed"
        copy_state = json.loads(json.dumps(state))
        self.assertEqual(copy_state["draft"], state["draft"])
        self.assertEqual(copy_state["edits"], state["edits"])


class ScaleWorkerTests(unittest.IsolatedAsyncioTestCase):
    async def test_a_blocked_worker_does_not_block_input_and_only_latest_result_commits(self):
        entered, release = threading.Event(), threading.Event()
        calls, results = [], []

        def query(state):
            calls.append(state["revision"])
            if state["revision"] == 1:
                entered.set()
                release.wait(3)
            return [state["revision"]]

        worker = TableWorkQueue(lambda rows, state: results.append(rows), query=query)
        try:
            state = table_state()
            state["revision"] = 1
            worker.submit(state)
            await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), 4)
            state["revision"] = 2
            worker.submit(state)
            state["revision"] = 3
            worker.submit(state)
            # The event loop services this input while the first real thread
            # remains blocked. The unsaved draft is never passed back by it.
            state["draft"] = "Input handled during work"
            self.assertFalse(release.is_set())
            release.set()
            await asyncio.wait_for(worker.task, 4)
            self.assertEqual(calls, [1, 3])
            self.assertEqual(results, [[3]])
            self.assertEqual(state["draft"], "Input handled during work")
        finally:
            release.set()
            await worker.close()

    async def test_disposal_rejects_late_thread_results_and_future_work(self):
        entered, release = threading.Event(), threading.Event()
        results = []

        def query(state):
            entered.set()
            release.wait(3)
            return [42]

        worker = TableWorkQueue(lambda rows, state: results.append(rows), query=query)
        worker.submit(table_state())
        await asyncio.wait_for(asyncio.to_thread(entered.wait, 3), 4)
        await worker.close()
        release.set()
        await asyncio.sleep(0.01)
        self.assertEqual(results, [])
        self.assertFalse(worker.submit(table_state()))

    async def test_worker_snapshot_is_independent_of_newer_edits(self):
        state = table_state()
        results = []
        worker = TableWorkQueue(lambda rows, snapshot: results.append(snapshot), query=lambda state: [])
        worker.submit(state)
        edit_table(state, 0, "Changed after submission")
        await asyncio.wait_for(worker.task, 3)
        self.assertEqual(results[0]["edits"], {})
        await worker.close()


if __name__ == "__main__":
    unittest.main()
