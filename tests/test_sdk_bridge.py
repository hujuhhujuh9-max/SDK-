"""Exercise initial and later routes without requiring Flet on the build-input host."""

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from runtime.sdk_bridge import _page
from runtime import sdk_bridge
from runtime.renfletpy import story


class PageRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        story.reset()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.publish_transcript(())
        sdk_bridge._quitting.clear()
        self.pages = []

    async def asyncTearDown(self):
        for page in self.pages:
            await page.on_close(None)

    async def page(self, route="/"):
        page = types.SimpleNamespace(
            route=route, views=[types.SimpleNamespace(route="/")],
            update=Mock(), push_route=AsyncMock())
        flet = types.ModuleType("flet")
        def control(*args, **kwargs):
            if args:
                kwargs["content"] = args[0]
            return types.SimpleNamespace(**kwargs)

        for name in ("Text", "TextButton", "Button", "Row", "Column", "Container", "Theme", "View"):
            setattr(flet, name, control)
        flet.ThemeMode = types.SimpleNamespace(DARK="dark")
        flet.FontWeight = types.SimpleNamespace(W_600="w600")
        flet.ScrollMode = types.SimpleNamespace(AUTO="auto")
        flet.MainAxisAlignment = types.SimpleNamespace(CENTER="center", SPACE_BETWEEN="spaceBetween")

        async def open_page(target, route="/capabilities"):
            target.views.append(types.SimpleNamespace(route=route))
            await target.push_route(route)

        demo = types.ModuleType("capability_demo")
        demo.open_page = AsyncMock(side_effect=open_page)
        with patch.dict(sys.modules, {"flet": flet, "capability_demo": demo}):
            await _page(page)
        self.pages.append(page)
        # Route callbacks build new controls after the initial mount.
        page._fake_flet = flet
        return page, demo

    async def change_route(self, page, route, demo=None):
        modules = {"flet": page._fake_flet}
        if demo is not None:
            modules["capability_demo"] = demo
        with patch.dict(sys.modules, modules):
            await page.on_route_change(types.SimpleNamespace(route=route))

    async def test_cold_link_opens_once_and_back_returns_to_root(self):
        page, demo = await self.page("/capabilities")
        demo.open_page.assert_awaited_once_with(page, route="/capabilities")
        self.assertEqual(len(page.views), 2)
        await self.change_route(page, "/capabilities", demo)
        self.assertEqual(len(page.views), 2)
        await page.on_view_pop(None)
        self.assertEqual(len(page.views), 1)
        page.push_route.assert_awaited_with("/diagnostics")

    async def test_warm_link_opens_after_ordinary_startup(self):
        page, demo = await self.page()
        demo.open_page.assert_not_awaited()
        await self.change_route(page, "/capabilities", demo)
        demo.open_page.assert_awaited_once_with(page, route="/capabilities")
        self.assertEqual(len(page.views), 2)

    async def test_cold_query_link_preserves_route_and_opens_once(self):
        route = "/capabilities?probe=1"
        page, demo = await self.page(route)
        demo.open_page.assert_awaited_once_with(page, route=route)
        self.assertEqual(page.views[-1].route, route)
        await self.change_route(page, route, demo)
        self.assertEqual(len(page.views), 2)

    async def test_warm_root_link_pops_capabilities(self):
        page, demo = await self.page("/capabilities")
        await self.change_route(page, "/?probe=1")
        self.assertEqual(len(page.views), 1)
        self.assertEqual(page.views[0].route, "/?probe=1")

    async def test_changed_query_reuses_capabilities_view(self):
        page, demo = await self.page("/capabilities?probe=1")
        await self.change_route(page, "/capabilities?probe=2", demo)
        self.assertEqual(len(page.views), 2)
        self.assertEqual(page.views[-1].route, "/capabilities?probe=2")
        demo.open_page.assert_awaited_once()

    async def test_unknown_initial_route_keeps_root_view(self):
        page, demo = await self.page("/unknown")
        demo.open_page.assert_not_awaited()
        self.assertEqual(len(page.views), 1)

    async def test_menu_transcript_and_back_keep_the_pending_story_choice(self):
        revision = story.show("Mira", "Still waiting", (("sky", "Sky"),))
        page, _ = await self.page()
        await self.change_route(page, "/history")
        self.assertEqual([view.route for view in page.views], ["/", "/menu", "/history"])
        self.assertEqual(story.current().revision, revision)
        self.assertIsNone(story.consume(revision))
        await page.on_view_pop(None)
        page.push_route.assert_awaited_with("/menu")
        await self.change_route(page, "/")
        self.assertEqual(len(page.views), 1)
        self.assertEqual(page.views[0].bgcolor, "transparent")
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            self.assertTrue(story.choose(revision, "sky"))
            await asyncio.sleep(0)

    async def test_disconnect_and_reconnect_do_not_accumulate_story_listeners(self):
        page, _ = await self.page()
        self.assertEqual(len(story._listeners), 1)
        await page.on_disconnect(None)
        self.assertEqual(len(story._listeners), 0)
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            story.show("Mira", "Published while disconnected")
            await page.on_connect(None)
            await page.on_connect(None)
        self.assertEqual(len(story._listeners), 1)

    async def test_completed_minigame_returns_input_to_the_native_scene(self):
        from runtime.sdk_bridge import presentation
        page, _ = await self.page()
        self.assertEqual(presentation(), "scene")
        self.assertEqual(page.views[0].controls, [])
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            revision = story.minigame("star_map")
            await asyncio.sleep(0)
            self.assertEqual(presentation(), "interlude")
            story.choose(revision, "skipped")
            self.assertEqual(story.consume(revision), "skipped")
            story.close(revision)
            await asyncio.sleep(0)
        self.assertEqual(presentation(), "scene")
        self.assertEqual(page.views[0].controls, [])

    async def test_renpy_menu_action_is_queued_on_the_flet_loop_and_detaches(self):
        from runtime.sdk_bridge import open_menu
        page, _ = await self.page()
        open_menu()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        page.push_route.assert_awaited_with("/menu")
        await page.on_close(None)
        page.push_route.reset_mock()
        open_menu()
        await asyncio.sleep(0)
        page.push_route.assert_not_awaited()

    async def test_save_menu_submits_once_and_updates_only_on_the_flet_loop(self):
        page, _ = await self.page("/menu")
        # The two save controls live in their own row.
        def save_buttons():
            row = next(control for control in page.views[-1].controls[0].content
                       if isinstance(getattr(control, "content", None), list))
            return row.content
        save, load = save_buttons()
        self.assertTrue(load.disabled)
        self.assertFalse(save.disabled)
        page.update.reset_mock()
        await save.on_click(None)
        page.update.assert_not_called()
        self.assertEqual(sdk_bridge.take_save_request(), "save")
        self.assertIsNone(sdk_bridge.take_save_request())
        self.assertFalse(sdk_bridge.request_save("save"))
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            await asyncio.sleep(0)
            self.assertTrue(all(control.disabled for control in save_buttons()))
            sdk_bridge.update_save_status(True, "Saved.")
            await asyncio.sleep(0)
        self.assertTrue(all(not control.disabled for control in save_buttons()))
        self.assertEqual(story.history(), ())

    async def test_restoring_returns_to_the_story_and_callbacks_detach(self):
        page, _ = await self.page("/menu")
        sdk_bridge.resume_story()
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        page.push_route.assert_awaited_with("/")
        await page.on_close(None)
        page.push_route.reset_mock()
        page.update.reset_mock()
        sdk_bridge.resume_story()
        sdk_bridge.update_save_status(True, "Loaded.")
        await asyncio.sleep(0)
        page.push_route.assert_not_awaited()
        page.update.assert_not_called()

    async def test_automatic_recovery_preserves_explicit_diagnostics_links(self):
        for route in ("/diagnostics", "/capabilities?probe=cold"):
            page, _ = await self.page(route)
            page.push_route.reset_mock()
            sdk_bridge.resume_story()
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            page.push_route.assert_not_awaited()

    async def test_missing_load_and_unknown_commands_do_not_block_save(self):
        self.assertFalse(sdk_bridge.request_save("load"))
        with self.assertRaises(ValueError):
            sdk_bridge.request_save("delete")
        self.assertIsNone(sdk_bridge.take_save_request())
        self.assertTrue(sdk_bridge.request_save("save"))
        sdk_bridge.initialize_save_status(False)
        self.assertTrue(sdk_bridge.save_status()["busy"])
        self.assertEqual(sdk_bridge.take_save_request(), "save")

    async def test_history_refresh_keeps_native_chronology_and_detaches_on_close(self):
        page, _ = await self.page("/history")
        entries = (("Mira", "Look up.", ""), ("Star map", "Connect stars.", "Aligned"),
                   ("Mira", "We did it.", ""))
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            sdk_bridge.publish_transcript(entries)
            await asyncio.sleep(0)
        cards = page.views[-1].controls[1].content
        self.assertEqual([card.content.content[1].content for card in cards],
                         ["Look up.", "Connect stars.", "We did it."])
        page.update.reset_mock()
        sdk_bridge.publish_transcript(entries)
        await asyncio.sleep(0)
        page.update.assert_not_called()
        await page.on_close(None)
        sdk_bridge.publish_transcript(())
        await asyncio.sleep(0)
        page.update.assert_not_called()

    async def test_pending_save_blocks_quit_and_stale_replay_callbacks(self):
        page, _ = await self.page("/restart")
        replay = page.views[-1].controls[0].content[2]
        self.assertTrue(sdk_bridge.request_save("save"))
        self.assertFalse(sdk_bridge.request_quit())
        await replay.on_click(None)
        self.assertFalse(story.restarting())
        self.assertFalse(sdk_bridge.quitting())
        self.assertEqual(sdk_bridge.take_save_request(), "save")
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            sdk_bridge.update_save_status(True, "Saved.")
            await asyncio.sleep(0)
        await replay.on_click(None)
        self.assertTrue(story.restarting())
        self.assertFalse(sdk_bridge.request_save("save"))
        self.assertFalse(sdk_bridge.request_quit())
        story.reset()
        self.assertTrue(sdk_bridge.request_quit())
        self.assertFalse(sdk_bridge.request_save("save"))
        self.assertFalse(sdk_bridge.request_restart())


if __name__ == "__main__":
    unittest.main()
