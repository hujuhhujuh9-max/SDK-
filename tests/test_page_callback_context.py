"""Native publications keep the owning Flet page's context and lifetime."""

import asyncio
import contextvars
import importlib.util
import sys
import threading
import types
import unittest
from unittest import mock

from runtime import app_session, sdk_bridge
from runtime.renfletpy import story

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as ft
    from flet.controls.base_control import BaseControl
    from flet.controls.context import _context_page
    from flet.messaging.session import Session
    from test_form_list_flet import PreferencesConnection

_origin = contextvars.ContextVar("page_callback_fixture_origin", default="unbound")


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class PageCallbackContextTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.enterContext(mock.patch.dict(sys.modules, {
            "runtime.project_config": types.SimpleNamespace(
                STARTUP_TEMPLATE="story", PROJECT_SETUP=None),
        }))
        self.mounts = []
        self.tokens = []
        self.flet_thread = threading.get_ident()
        self.loop = asyncio.get_running_loop()
        self.loop_errors = []
        self.previous_error_handler = self.loop.get_exception_handler()
        self.loop.set_exception_handler(lambda loop, error: self.loop_errors.append(error))
        story.reset()
        sdk_bridge._stopping.clear()
        sdk_bridge._quitting.clear()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        sdk_bridge.publish_transcript(())
        app_session.session.restore(phase="ready", resume_kind="unavailable", showing_story=False)

    async def asyncTearDown(self):
        try:
            for mount in reversed(self.mounts):
                await mount.page.on_close(None)
                mount.session.close()
            for variable, token in reversed(self.tokens):
                variable.reset(token)
            story.reset()
            sdk_bridge.update_save_status(False, "No saved game yet.")
            sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
            sdk_bridge.publish_transcript(())
            await self.drain()
        finally:
            self.loop.set_exception_handler(self.previous_error_handler)

    async def drain(self):
        for _ in range(12):
            await asyncio.sleep(0)

    async def mount(self, route, origin):
        connection = PreferencesConnection()
        session = Session(connection)
        connection.session = session
        page = session.page
        page.route = route
        self.tokens.extend([
            (_context_page, _context_page.set(page)),
            (_origin, _origin.set(origin)),
        ])
        ft.context.reset_auto_update()
        connection.encode(session.get_page_patch())
        mount = types.SimpleNamespace(page=page, session=session, connection=connection,
                                      updates=[], origin=origin)
        self.mounts.append(mount)
        update = page.update

        def record_update(*args, **kwargs):
            # Observe the real callback's context, then encode its real patch.
            mount.updates.append((ft.context.page, _origin.get(), threading.get_ident()))
            return update(*args, **kwargs)

        page.update = record_update
        await sdk_bridge._page(page)
        return mount

    def native_publish(self, publish):
        errors = []
        contexts = []

        def run():
            _origin.set("native")
            for phase in ("before", "after"):
                try:
                    current = ft.context.page
                except RuntimeError:
                    current = None
                contexts.append((phase, current, threading.get_ident()))
                if phase == "before":
                    try:
                        publish()
                    except BaseException as error:
                        errors.append(error)

        native = threading.Thread(target=lambda: contextvars.Context().run(run),
                                  name="native-story-context-fixture")
        native.start()
        native.join(timeout=3)
        self.assertFalse(native.is_alive(), "Native publication should not wait for the Flet loop")
        self.assertEqual(errors, [])
        self.assertEqual([phase for phase, _, _ in contexts], ["before", "after"])
        for _, current, thread in contexts:
            self.assertIsNone(current, "Flet page context must stay absent on the native owner")
            self.assertNotEqual(thread, self.flet_thread)

    def publish(self, kind, origin):
        message = f"Page {origin} native {kind}"
        if kind == "story":
            story.show("Native narrator", message)
        elif kind == "save":
            sdk_bridge.update_save_status(True, message)
        elif kind == "history":
            sdk_bridge.publish_transcript((("Native narrator", message, ""),))
        elif kind == "reading":
            sdk_bridge.update_reading_status(origin == "A", "animated" if origin == "A" else "instant",
                                             message)
        else:
            self.fail("Unknown callback fixture")

    def visible_text(self, page):
        seen = set()

        def visit(value):
            if isinstance(value, BaseControl):
                if id(value) in seen:
                    return
                seen.add(id(value))
                if isinstance(value, ft.Text):
                    yield value.value
                for child in vars(value).values():
                    yield from visit(child)
            elif isinstance(value, (list, tuple)):
                for child in value:
                    yield from visit(child)
            elif isinstance(value, dict):
                for child in value.values():
                    yield from visit(child)

        return list(visit(page.views))

    async def exercise_replaced_page(self, kind, route):
        retired = await self.mount(route, "A")
        retired_updates = list(retired.updates)
        retired_patches = list(retired.connection.patches)
        self.native_publish(lambda: self.publish(kind, "A"))
        # Neither native join nor these route factories yield. B takes ownership
        # before A's queued callback can execute, reproducing the reconnect race.
        active = await self.mount("/diagnostics", "B")
        active_updates = list(active.updates)
        active_patches = list(active.connection.patches)
        self.assertEqual(sdk_bridge.presentation(), "diagnostics")
        await self.drain()
        self.assertEqual(self.loop_errors, [])
        self.assertEqual(retired.updates, retired_updates)
        self.assertEqual(retired.connection.patches, retired_patches)
        self.assertEqual(retired.page.route, route)
        self.assertEqual(active.updates, active_updates)
        self.assertEqual(active.connection.patches, active_patches)
        self.assertEqual(active.page.route, "/diagnostics")
        self.assertEqual(sdk_bridge.presentation(), "diagnostics")

        # The same public publication must still update B in B's context.
        active.page.route = route
        await active.session.dispatch_event(active.page._i, "route_change", {"route": route})
        await self.drain()
        active.updates.clear()
        active_patches = len(active.connection.patches)
        self.native_publish(lambda: self.publish(kind, "B"))
        await self.drain()
        self.assertEqual(self.loop_errors, [])
        self.assertIn(f"Page B native {kind}", self.visible_text(active.page))
        self.assertGreater(len(active.connection.patches), active_patches)
        self.assertTrue(active.updates)
        for page, origin, thread in active.updates:
            self.assertIs(page, active.page)
            self.assertEqual(origin, "B")
            self.assertEqual(thread, self.flet_thread)
        self.assertEqual(retired.updates, retired_updates)
        self.assertEqual(retired.connection.patches, retired_patches)

    async def test_native_story_callback_cannot_render_a_replaced_page(self):
        await self.exercise_replaced_page("story", "/")

    async def test_native_save_callback_cannot_refresh_a_replaced_menu(self):
        await self.exercise_replaced_page("save", "/menu")

    async def test_native_history_callback_cannot_refresh_a_replaced_history(self):
        await self.exercise_replaced_page("history", "/history")

    async def test_native_reading_task_cannot_rebuild_a_replaced_page(self):
        await self.exercise_replaced_page("reading", "/settings")


if __name__ == "__main__":
    unittest.main()
