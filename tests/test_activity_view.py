"""Retained activity controls, native draft acknowledgements and cleanup."""

import asyncio
import importlib.util
import pickle
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from runtime.renfletpy import Story
from runtime.story_activities import (
    ActivityContext, ActivityRegistry, ActivityRenderError, ActivityView, plain_copy,
)


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("retained_survey", ROOT / "examples/activities/survey_activity.py")
survey = importlib.util.module_from_spec(spec)
spec.loader.exec_module(survey)
FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as ft
    import msgpack
    from flet.controls.context import _context_page
    from flet.messaging.flet_socket_server import FletSocketServer
    from flet.messaging.protocol import decode_ext_from_msgpack
    from scripts.flet_protocol import walk


def catalog():
    registry = ActivityRegistry()
    survey.register(SimpleNamespace(register_activity=registry.register))
    return registry


class ActivityViewContractTests(unittest.TestCase):
    def test_optional_view_and_legacy_control_list_are_both_supported(self):
        registry = ActivityRegistry()
        descriptor = ActivityView([], lambda context: None)
        for name, renderer in (("retained", lambda context: descriptor),
                               ("legacy", lambda context: [])):
            registry.register(name, version=1, create_state=lambda: {},
                              renderer=renderer, reduce=lambda state, name, payload: state)
        story = Story(registry)
        revision = story.start_activity("retained")
        self.assertIs(registry.render(ActivityContext(story, revision, lambda route: None)), descriptor)
        revision = story.start_activity("legacy")
        self.assertEqual(registry.render(ActivityContext(story, revision, lambda route: None)), [])
        with self.assertRaises(FrozenInstanceError):
            descriptor.controls = []
        # Live views cannot become game data, including their callback closures.
        with self.assertRaisesRegex(ValueError, "JSON"):
            plain_copy({"view": descriptor})

    def test_invalid_controls_and_asynchronous_lifecycle_callbacks_fail_clearly(self):
        async def asynchronous(*args):
            pass

        def generator(*args):
            yield None

        async def async_generator(*args):
            yield None

        class AsyncCallable:
            async def __call__(self, *args):
                pass

        for controls in (None, (), object()):
            with self.subTest(controls=type(controls)), self.assertRaisesRegex(TypeError, "controls"):
                ActivityView(controls, lambda context: None)
        for callback in (None, 1, asynchronous, generator, async_generator, AsyncCallable()):
            with self.subTest(refresh=callback), self.assertRaisesRegex(TypeError, "refresh"):
                ActivityView([], callback)
        for callback in (1, asynchronous, generator, async_generator, AsyncCallable()):
            with self.subTest(dispose=callback), self.assertRaisesRegex(TypeError, "dispose"):
                ActivityView([], lambda context: None, callback)

    def test_wrapped_async_results_are_closed_instead_of_becoming_unawaited_work(self):
        async def asynchronous():
            pass

        def generator():
            yield None

        for factory, frame in ((asynchronous, "cr_frame"), (generator, "gi_frame")):
            pending = factory()
            view = ActivityView([], lambda context: pending)
            with self.assertRaisesRegex(TypeError, "refresh.*synchronously"):
                view.refresh(None)
            self.assertIsNone(getattr(pending, frame))
            pending = factory()
            view = ActivityView([], lambda context: None, lambda: pending)
            with self.assertRaisesRegex(TypeError, "dispose.*synchronously"):
                view.dispose()
            self.assertIsNone(getattr(pending, frame))

    def test_invalid_descriptor_factory_does_not_change_the_saved_model(self):
        registry = ActivityRegistry()
        registry.register("invalid", version=1, create_state=lambda: {"draft": "intact"},
                          renderer=lambda context: ActivityView([], None),
                          reduce=lambda state, name, payload: state)
        story = Story(registry)
        revision = story.start_activity("invalid")
        with self.assertRaises(ActivityRenderError) as caught:
            registry.render(ActivityContext(story, revision, lambda route: None))
        self.assertIsInstance(caught.exception.__cause__, TypeError)
        self.assertEqual(story.current().activity["state"], {"draft": "intact"})


@unittest.skipUnless(FLET_AVAILABLE, "Requires prepared pinned Flet")
class ActivityViewWireTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(patch.dict(sys.modules, {"flet": ft}))
        self.registry = catalog()
        self.story = Story(self.registry)
        self.story.start_activity("field_survey")
        self.navigated = []
        self.edited = asyncio.Queue()
        self.mounts = 0
        self.cleanups = 0
        self.running = None
        self.service_stopped = False
        self.folder = tempfile.TemporaryDirectory(prefix="activity-view-wire-")
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.view = self.registry.render(self.context())
        self.column = self.view.controls[0].content
        self.field = self.column.controls[3]
        original_edit = self.field.on_change

        async def edited(event):
            await original_edit(event)
            await self.edited.put(event.control.value)

        self.field.on_change = edited
        owner = self

        class MountedService(ft.Container):
            def did_mount(self):
                owner.mounts += 1
                owner.running = asyncio.create_task(asyncio.Event().wait())

            def will_unmount(self):
                self.stop()

            def stop(self):
                if owner.running is not None and not owner.service_stopped:
                    owner.service_stopped = True
                    owner.cleanups += 1
                    owner.running.cancel()

        self.service = MountedService()
        self.status = ft.Text("Native model ready")
        original_dispose = self.view.dispose

        def dispose():
            original_dispose()
            self.service.stop()

        self.view = ActivityView(self.view.controls + [self.service], self.view.refresh, dispose)

        async def mount(session):
            token = _context_page.set(session.page)
            try:
                session.page.views[0].controls = self.view.controls + [self.status]
                session.page.update()
            finally:
                _context_page.reset(token)

        socket_path = str(Path(self.folder.name) / "flet.sock")
        self.server = FletSocketServer(loop=asyncio.get_running_loop(), uds_path=socket_path,
                                       on_session_created=mount, executor=self.executor)
        await self.server.start()
        self.reader, self.writer = await asyncio.open_unix_connection(socket_path)
        await self.send(1, {"session_id": "", "page_name": "", "page": {
            "platform": "android", "width": 400.0, "height": 700.0, "route": "/"}})
        self.assertEqual((await self.receive())[0], 1)
        await self.until(lambda value: "Unfinished observation" in walk(value))
        self.ancestry = [self.server.session.page.views[0], self.view.controls[0], self.column, self.field]
        self.ancestry_ids = [control._i for control in self.ancestry]
        self.assertEqual(self.mounts, 1)

    async def asyncTearDown(self):
        if self.running is not None:
            self.running.cancel()
            await asyncio.gather(self.running, return_exceptions=True)
        self.writer.close()
        await self.writer.wait_closed()
        await self.server.close()
        self.executor.shutdown(wait=True, cancel_futures=True)
        self.folder.cleanup()

    def context(self, *, large_text=False):
        return ActivityContext(self.story, self.story.current().revision, self.navigate, large_text)

    async def navigate(self, route):
        self.navigated.append(route)

    async def send(self, action, body):
        packet = b"\x00" + msgpack.packb([action, body])
        self.writer.write(len(packet).to_bytes(4, "little") + packet)
        await self.writer.drain()

    async def receive(self):
        async with asyncio.timeout(5):
            size = int.from_bytes(await self.reader.readexactly(4), "little")
            self.assertTrue(0 < size <= 1024 * 1024)
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
        self.fail("Expected activity protocol message was not received")

    async def type_text(self, value):
        # Same two messages emitted by TextFieldControl.onChanged in Dart.
        await self.send(4, {"id": self.field._i, "props": {"value": value}})
        await self.send(3, {"target": self.field._i, "name": "change", "data": value})
        self.assertEqual(await asyncio.wait_for(self.edited.get(), 5), value)

    async def refresh(self, context=None, receipt=None):
        context = context or self.context()
        receipt = receipt or "Owner committed: " + context.state["draft"]
        token = _context_page.set(self.server.session.page)
        try:
            self.view.refresh(context)
            self.status.value = receipt
            self.server.session.page.update()
        finally:
            _context_page.reset(token)
        return await self.until(lambda value: receipt in walk(value))

    async def test_multiple_native_draft_commits_keep_textfield_and_entire_ancestry_mounted(self):
        for value in ("N", "Ni", "Night", "Night sky"):
            previous = self.story.current().activity["state"]["draft"]
            await self.type_text(value)
            self.assertEqual(self.story.current().activity["state"]["draft"], previous)
            self.story.process_activity_commands()
            patch = await self.refresh()
            self.assertEqual([control._i for control in self.ancestry], self.ancestry_ids)
            for control in self.ancestry:
                self.assertIs(self.server.session.index[control._i], control)
            # A property patch has no new TextField descriptor or selection reset.
            self.assertNotIn("Unfinished observation", walk(patch))
            self.assertNotIn("selection", walk(patch))
            self.assertEqual(self.field.value, value)
            self.assertEqual(self.story.current().activity["state"]["draft"], value)
            self.assertEqual(self.mounts, 1)
            self.assertEqual(self.cleanups, 0)
            self.assertFalse(self.running.done())
        await self.refresh(self.context(large_text=True), receipt="Reading size updated in place")
        self.assertEqual(self.column.controls[0].controls[0].size, 30)
        self.assertEqual([control._i for control in self.ancestry], self.ancestry_ids)

    async def test_earlier_commit_cannot_overwrite_newer_unacknowledged_text(self):
        await self.type_text("A")
        self.story.process_activity_commands()
        earlier = self.context()
        await self.type_text("AB")
        await self.refresh(earlier, receipt="Earlier A acknowledged")
        self.assertEqual(self.field.value, "AB")
        self.assertEqual(self.story.current().activity["state"]["draft"], "A")
        self.story.process_activity_commands()
        await self.refresh()
        self.assertEqual(self.field.value, "AB")
        self.assertEqual(self.story.current().activity["state"]["draft"], "AB")
        self.assertEqual(self.cleanups, 0)

    async def test_half_save_load_reconstructs_controls_and_cleans_the_live_service(self):
        await self.type_text("Halfway survey draft")
        self.story.process_activity_commands()
        await self.refresh()
        saved = pickle.loads(pickle.dumps(self.story.snapshot()))
        self.assertEqual(saved["history"][-1]["activity"]["state"]["draft"], "Halfway survey draft")
        self.assertNotIn("ActivityView", repr(saved))
        self.assertNotIn("MountedService", repr(saved))
        self.story.restore(saved)
        self.view.dispose()
        rebuilt = self.registry.render(self.context())
        token = _context_page.set(self.server.session.page)
        try:
            self.server.session.page.views[0].controls = rebuilt.controls
            self.server.session.page.update()
        finally:
            _context_page.reset(token)
        await self.until(lambda value: "Halfway survey draft" in walk(value))
        await asyncio.gather(self.running, return_exceptions=True)
        self.assertEqual(self.cleanups, 1)
        self.assertTrue(self.running.cancelled())
        self.assertNotIn(self.field._i, self.server.session.index)
        replacement = rebuilt.controls[0].content.controls[3]
        self.assertNotEqual(replacement._i, self.field._i)
        self.assertEqual(replacement.value, "Halfway survey draft")
        # Detached callbacks from a closed view cannot enqueue into its lifetime.
        self.field.value = "Late detached edit"
        await self.field.on_change(SimpleNamespace(control=self.field))
        self.story.process_activity_commands()
        self.assertEqual(self.story.current().activity["state"]["draft"], "Halfway survey draft")


if __name__ == "__main__":
    unittest.main()
