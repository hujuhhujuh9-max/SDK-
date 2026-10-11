"""Use real pinned controls/model/events and inspect their serialized patches."""

import asyncio
import importlib.util
import unittest

from runtime.scale_ui import CanvasPanel, TablePanel
from runtime.scale_workloads import PROBE_COLORS, canvas_state, node_position, table_state
from scripts.flet_protocol import walk

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as ft
    import msgpack
    from flet.controls.base_control import BaseControl
    from flet.controls.context import _context_page
    from flet.messaging.connection import Connection
    from flet.messaging.protocol import configure_encode_object_for_msgpack
    from flet.messaging.session import Session
    from flet.pubsub.pubsub_hub import PubSubHub
else:
    Connection = object


class ScaleConnection(Connection):
    def __init__(self):
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.page_url = "flet://scale"
        self.pubsubhub = PubSubHub(loop=self.loop)
        self.messages = []
        self.sizes = []

    def send_message(self, message):
        encoded = msgpack.packb([message.action, message.body],
                               default=configure_encode_object_for_msgpack(BaseControl))
        self.sizes.append(len(encoded))
        self.messages.append(msgpack.unpackb(encoded, strict_map_key=False))

    def encode(self, value):
        return msgpack.unpackb(msgpack.packb(value, default=configure_encode_object_for_msgpack(BaseControl)),
                               strict_map_key=False)


@unittest.skipUnless(FLET_AVAILABLE, "Requires prepared pinned Flet")
class ScaleFletTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = ScaleConnection()
        self.session = Session(self.connection)
        self.page = self.session.page
        self.token = _context_page.set(self.page)
        self.panels = []
        self.connection.encode(self.session.get_page_patch())

    async def asyncTearDown(self):
        for panel in self.panels:
            await panel.dispose()
        _context_page.reset(self.token)
        self.session.close()
        await asyncio.sleep(0)

    def mount(self, panel):
        self.panels.append(panel)
        self.page.views.append(ft.View(route="/scale", controls=[ft.Column(panel.controls)]))
        self.page.update()

    async def test_canvas_real_gestures_preserve_camera_and_color_receipts_across_rebuild(self):
        state = canvas_state()
        panel = CanvasPanel(self.page, state, lambda name, payload: True)
        self.mount(panel)
        kinds = [value.get("_c") for value in walk(self.connection.messages)
                 if isinstance(value, dict)]
        self.assertEqual(kinds.count("Circle"), 1000)
        self.assertEqual(kinds.count("Line"), 500)
        self.assertEqual(kinds.count("Rect"), 500)
        self.assertIn("GestureDetector", kinds)
        semantics = [value for value in walk(self.connection.messages)
                     if isinstance(value, dict) and value.get("_c") == "Semantics"]
        self.assertIn("cap-scale-canvas", [value.get("identifier") for value in semantics])
        await self.session.dispatch_event(panel.gestures._i, "scale_start", {
            "lfp": {"x": 40, "y": 50}, "gfp": {"x": 40, "y": 50}, "pc": 2})
        event = {"lfp": {"x": 40, "y": 50}, "gfp": {"x": 40, "y": 50}, "pc": 2,
                 "hs": 2, "vs": 2, "s": 2, "rot": 0, "fpd": {"x": 0, "y": 0}}
        await self.session.dispatch_event(panel.gestures._i, "scale_update", event)
        event = {**event, "s": 3, "hs": 3, "vs": 3}
        await self.session.dispatch_event(panel.gestures._i, "scale_update", event)
        self.assertAlmostEqual(state["camera"]["scale"], 0.9)
        await self.session.dispatch_event(panel.probe._i, "click", None)
        self.assertEqual(panel.probe.bgcolor, PROBE_COLORS[1])
        self.assertEqual(state["input_receipts"], 1)
        self.page.views.clear()
        self.page.update()
        await panel.dispose()
        rebuilt = CanvasPanel(self.page, state, lambda name, payload: True)
        self.mount(rebuilt)
        self.assertEqual(rebuilt.probe.bgcolor, PROBE_COLORS[1])
        self.assertAlmostEqual(rebuilt.state["camera"]["scale"], 0.9)
        self.assertEqual(len(rebuilt.canvas.shapes), 2000)

    async def test_canvas_rejected_command_cannot_change_saved_values(self):
        state = canvas_state()
        panel = CanvasPanel(self.page, state, lambda name, payload: False)
        self.mount(panel)
        await self.session.dispatch_event(panel.probe._i, "click", None)
        self.assertEqual(state["input_receipts"], 0)
        self.assertEqual(panel.probe.bgcolor, PROBE_COLORS[0])

    async def test_canvas_world_is_not_clipped_before_camera_transform(self):
        state = canvas_state()
        panel = CanvasPanel(self.page, state, lambda name, payload: True)
        self.mount(panel)
        self.assertIs(panel.gestures.content, panel.viewport)
        self.assertEqual((panel.viewport.width, panel.viewport.height), (320, 240))
        self.assertEqual((panel.canvas.left, panel.canvas.top), (0, 0))
        self.assertEqual(panel.viewport.clip_behavior, ft.ClipBehavior.HARD_EDGE)
        node = state["nodes"] - 1
        world_x, world_y = node_position(node, state["nodes"])
        self.assertGreater(world_x, panel.viewport.width)
        self.assertGreater(world_y, panel.viewport.height)
        # The pinned Dart painter clips to its own untransformed size. Its
        # source bounds must contain every node, including link endpoints.
        for index in range(state["nodes"]):
            x, y = node_position(index, state["nodes"])
            self.assertLessEqual(x + 36, panel.canvas.width)
            self.assertLessEqual(y + 36, panel.canvas.height)
        await self.session.dispatch_event(panel.gestures._i, "scale_start", {
            "lfp": {"x": 0, "y": 0}, "gfp": {"x": 0, "y": 0}, "pc": 2})
        await self.session.dispatch_event(panel.gestures._i, "scale_update", {
            "lfp": {"x": 0, "y": 0}, "gfp": {"x": 0, "y": 0}, "pc": 2,
            "hs": 10 / 3, "vs": 10 / 3, "s": 10 / 3, "rot": 0,
            "fpd": {"x": 80 - world_x, "y": 100 - world_y}})
        await self.session.dispatch_event(panel.gestures._i, "tap_up", {
            "l": {"x": 80, "y": 100}, "g": {"x": 80, "y": 100}})
        self.assertEqual(state["selected"], node)
        self.assertEqual(panel.canvas.transform.alignment, ft.Alignment.TOP_LEFT)
        self.assertEqual(panel.canvas.shapes[node * 4 + 2].paint.color, "#ffe08a")

    async def test_table_lazy_protocol_worker_edits_and_draft_rebuild(self):
        state = table_state()
        panel = TablePanel(self.page, state)
        self.mount(panel)
        lists = [item for item in walk(self.connection.messages)
                 if isinstance(item, dict) and item.get("_c") == "ListView"]
        # True is the pinned native default and omitted from initial serialization.
        self.assertTrue(lists[-1].get("build_controls_on_demand", True))
        self.assertTrue(panel.list.build_controls_on_demand)
        self.assertEqual(len(lists[-1]["controls"]), 1000)
        self.assertEqual(len(panel.table.rows), 100)
        self.assertTrue(all(len(row.cells) == 4 for row in panel.table.rows))
        self.session.apply_patch(panel.draft._i, {"value": "A distant edited row"})
        await self.session.dispatch_event(panel.draft._i, "change", None)
        state["selected"] = 9999
        panel.save_edit(None)
        self.session.apply_patch(panel.filter._i, {"value": "distant"})
        await self.session.dispatch_event(panel.filter._i, "change", None)
        panel.run_worker()
        # Input receipt updates while the asynchronous scan is pending.
        await self.session.dispatch_event(panel.probe._i, "click", None)
        await asyncio.wait_for(panel.worker.task, 5)
        self.assertEqual(panel.ids, [9999])
        self.assertEqual(panel.table.rows[0].cells[1].content.value, "A distant edited row")
        self.session.apply_patch(panel.draft._i, {"value": "Unsaved after worker"})
        await self.session.dispatch_event(panel.draft._i, "change", None)
        self.page.views.clear()
        self.page.update()
        await panel.dispose()
        rebuilt = TablePanel(self.page, state)
        self.mount(rebuilt)
        self.assertEqual(rebuilt.draft.value, "Unsaved after worker")
        self.assertEqual(rebuilt.state["selected"], 9999)
        self.assertEqual(rebuilt.probe_text.value, "Probe input 1")
        self.assertEqual(rebuilt.ids, [9999])


if __name__ == "__main__":
    unittest.main()
