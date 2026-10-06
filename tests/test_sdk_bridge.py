"""Exercise initial and later routes without requiring Flet on the build-input host."""

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from runtime.sdk_bridge import _page
from runtime.renfletpy import story


class PageRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        story.reset()
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


if __name__ == "__main__":
    unittest.main()
