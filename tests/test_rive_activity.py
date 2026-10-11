"""Saveable Rive values and real pinned-Flet command/event transport."""

import asyncio
import importlib.util
import json
import math
import pickle
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runtime import rive_activity
from runtime.renfletpy import Story
from runtime.story_activities import ActivityContext, ActivityRegistry
from scripts.flet_protocol import walk

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as ft
    import msgpack
    from flet.controls.context import _context_page
    from flet.messaging.flet_socket_server import FletSocketServer
    from flet.messaging.protocol import decode_ext_from_msgpack
    from runtime.rive_control import InteractiveRive


class RiveActivityTests(unittest.TestCase):
    def setUp(self):
        self.registry = ActivityRegistry()
        self.definition = rive_activity.register_rive_activity(self.registry)
        self.story = Story(registry=self.registry)
        self.revision = self.story.start_activity(rive_activity.ACTIVITY_KIND)

    def event(self):
        return {"name": "SomeGeneralEvent", "type": "general", "machine": "State Machine 1",
                "seconds_delay": 0.0, "properties": dict(rive_activity.SIGNAL_PROPERTIES)}

    def test_halfway_save_reopens_values_and_completes_from_real_event_shape_once(self):
        context = ActivityContext(self.story, self.revision, lambda route: None)
        with ThreadPoolExecutor(max_workers=1) as loop:
            self.assertTrue(loop.submit(context.command, "progress", 55.0).result())
            self.assertTrue(loop.submit(context.command, "downloading", False).result())
            # The Flet thread queued commands; it did not mutate game data.
            self.assertEqual(self.story.current().activity["state"]["progress"], 25.0)
            with self.assertRaisesRegex(RuntimeError, "owner thread"):
                loop.submit(self.story.process_activity_commands).result()
        self.story.process_activity_commands()
        saved = json.loads(json.dumps(pickle.loads(pickle.dumps(self.story.snapshot()))))
        self.assertNotIn("trigger", json.dumps(saved).lower())
        reopened = Story(registry=self.registry)
        reopened.restore(saved)
        self.assertEqual(reopened.current().activity["state"],
                         {"progress": 55.0, "downloading": False, "receipt": None})
        reopened_context = ActivityContext(reopened, reopened.current().revision, lambda route: None)
        self.assertTrue(reopened_context.command("progress", 100.0))
        self.assertTrue(reopened_context.command("receipt", self.event()))
        reopened.process_activity_commands()
        result = reopened.consume(reopened.current().revision)
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.value, {"progress": 100.0, "downloading": False,
                                        "signal": rive_activity.SIGNAL_PROPERTIES})
        self.assertIsNone(reopened.consume(reopened.current().revision))
        self.assertFalse(reopened_context.command("receipt", self.event()))

    def test_load_rejects_callbacks_from_the_old_control_generation(self):
        old = ActivityContext(self.story, self.revision, lambda route: None)
        self.story.restore(self.story.snapshot())
        self.assertGreater(self.story.current().revision, self.revision)
        self.assertFalse(old.command("progress", 100.0))
        self.assertFalse(old.command("receipt", self.event()))
        self.assertIsNone(self.story.current().activity["state"]["receipt"])

    def test_original_save_migrates_progress_without_replaying_a_trigger(self):
        restored = self.definition.restore({"version": 1, "state": {"progress": 70.0}, "result": None})
        self.assertEqual(restored, {"version": 2, "state": {
            "progress": 70.0, "downloading": True, "receipt": None}, "result": None})
        for progress in (math.nan, math.inf, -1, 101, True, "70"):
            with self.subTest(progress=progress), self.assertRaises(ValueError):
                self.definition.restore({"version": 1, "state": {"progress": progress}, "result": None})
        for state in ({}, {"progress": 50.0, "trigger": "FireGeneralEvent"}):
            with self.assertRaises(ValueError):
                self.definition.restore({"version": 1, "state": state, "result": None})

    def test_malformed_event_keeps_the_previous_valid_model(self):
        context = ActivityContext(self.story, self.revision, lambda route: None)
        event = self.event()
        event["properties"]["SomeBoolean"] = 1
        self.assertTrue(context.command("receipt", event))
        with self.assertLogs(level="ERROR"):
            self.story.process_activity_commands()
        self.assertIsNone(self.story.current().activity["state"]["receipt"])
        self.assertIsNone(self.story.consume(self.revision))

    def test_explicit_cancellation_returns_plain_saved_progress(self):
        context = ActivityContext(self.story, self.revision, lambda route: None)
        self.assertTrue(context.cancel({"progress": context.state["progress"], "reason": "user_cancelled"}))
        self.story.process_activity_commands()
        result = self.story.consume(self.revision)
        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.value, {"progress": 25.0, "reason": "user_cancelled"})

    @unittest.skipUnless(FLET_AVAILABLE, "Requires prepared pinned Flet")
    def test_renderer_reconstructs_controls_with_saved_scalar_values(self):
        self.story.activity_command(self.revision, "progress", 65.0)
        self.story.activity_command(self.revision, "downloading", False)
        self.story.process_activity_commands()
        first = self.definition.renderer(ActivityContext(self.story, self.revision, lambda route: None))
        self.story.restore(self.story.snapshot())
        second = self.definition.renderer(ActivityContext(self.story, self.story.current().revision, lambda route: None))
        def forest(controls):
            semantics = next(control for control in controls if isinstance(control, ft.Semantics)
                             and control.identifier == "cap-rive-forest")
            return semantics.content
        a, b = forest(first), forest(second)
        self.assertIsNot(a, b)
        self.assertNotEqual(a._i, b._i)
        self.assertEqual(a.key, b.key)
        self.assertEqual(b.numbers, {"Progress": 65.0})
        self.assertEqual(b.booleans, {"Downloading": False})
        self.assertNotIn("controls", self.story.current().activity["state"])


@unittest.skipUnless(FLET_AVAILABLE, "Requires prepared pinned Flet")
class RiveWireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="rive-protocol-")
        self.socket_path = str(Path(self.folder.name) / "flet.sock")
        self.events = []
        self.replies = []
        self.status = ft.Text("Ready")
        self.control = InteractiveRive(
            src="rive/events_test.riv", artboard="New Artboard", use_artboard_size=True,
            numbers={}, booleans={}, on_event=self.received,
        )
        async def fire(event):
            self.replies.append(await self.control.fire("FireGeneralEvent"))
            self.status.value = "Trigger acknowledged"
            self.status.update()
        self.button = ft.Button("Fire", on_click=fire)
        async def mount(session):
            token = _context_page.set(session.page)
            try:
                session.page.add(self.control, self.button, self.status)
            finally:
                _context_page.reset(token)
        self.server = FletSocketServer(loop=asyncio.get_running_loop(), uds_path=self.socket_path,
                                       on_session_created=mount, executor=ThreadPoolExecutor(max_workers=1))
        await self.server.start()
        self.reader, self.writer = await asyncio.open_unix_connection(self.socket_path)
        await self.send(1, {"session_id": "", "page_name": "", "page": {
            "platform": "android", "width": 400.0, "height": 700.0, "route": "/rive"}})
        self.assertEqual((await self.receive())[0], 1)
        self.mounted = await self.until(lambda value: "rive/events_test.riv" in walk(value))

    async def asyncTearDown(self):
        self.writer.close()
        await self.writer.wait_closed()
        await self.server.close()
        await asyncio.sleep(0)
        self.folder.cleanup()

    def received(self, event):
        self.events.append(event.data)
        self.status.value = "Native event " + str(event.data["properties"]["SomeNumber"])
        self.status.update()

    async def send(self, action, body):
        packet = b"\x00" + msgpack.packb([action, body])
        self.writer.write(len(packet).to_bytes(4, "little") + packet)
        await self.writer.drain()

    async def receive(self):
        async with asyncio.timeout(5):
            size = int.from_bytes(await self.reader.readexactly(4), "little")
            if not 0 < size <= 1024 * 1024:
                raise AssertionError("Invalid packet size")
            packet = await self.reader.readexactly(size)
        self.assertEqual(packet[0], 0)
        result = msgpack.unpackb(packet[1:], strict_map_key=False, ext_hook=decode_ext_from_msgpack)
        self.assertNotEqual(result[0], 6, result)
        return result

    async def until(self, predicate):
        for _ in range(100):
            result = await self.receive()
            if predicate(result):
                return result
        raise AssertionError("Expected Rive protocol message")

    async def test_canonical_fields_transient_trigger_and_plain_event_roundtrip(self):
        wire = next(value for value in walk(self.mounted) if isinstance(value, dict)
                    and value.get("_c") == "sdk_rive_interactive")
        self.assertEqual(wire["artboard"], "New Artboard")
        self.assertTrue(wire["use_artboard_size"])
        self.assertNotIn("art_board", wire)
        self.assertNotIn("triggers", wire)
        await self.send(3, {"target": self.button._i, "name": "click", "data": None})
        invoked = await self.until(lambda value: value[0] == 5)
        request = invoked[1]
        self.assertEqual(request["name"], "fire")
        self.assertEqual(request["args"], {"name": "FireGeneralEvent"})
        await self.send(5, {"control_id": request["control_id"], "call_id": request["call_id"],
                            "result": {"accepted": True, "name": "FireGeneralEvent"}, "error": None})
        await self.until(lambda value: "Trigger acknowledged" in walk(value))
        self.assertEqual(len(self.replies), 1)
        data = {"name": "SomeGeneralEvent", "type": "general", "machine": "State Machine 1",
                "seconds_delay": 0.0, "properties": rive_activity.SIGNAL_PROPERTIES}
        await self.send(3, {"target": self.control._i, "name": "event", "data": {"data": data}})
        await self.until(lambda value: "Native event 11.0" in walk(value))
        self.assertEqual(self.events, [data])

    async def test_invalid_number_and_bool_properties_fail_before_dispatch(self):
        self.control.numbers = {"Progress": float("nan")}
        with self.assertRaisesRegex(ValueError, "finite"):
            self.control.before_update()
        self.control.numbers = {}
        self.control.booleans = {"Downloading": 1}
        with self.assertRaisesRegex(ValueError, "boolean"):
            self.control.before_update()
        self.control.booleans = {}


if __name__ == "__main__":
    unittest.main()
