"""Exercise initial and later routes without requiring Flet on the build-input host."""

import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from runtime.sdk_bridge import _page


class PageRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def page(self, route="/"):
        page = types.SimpleNamespace(
            route=route, views=[types.SimpleNamespace(route="/")],
            update=Mock(), push_route=AsyncMock())
        flet = types.ModuleType("flet")
        flet.Text = flet.Button = flet.Row = Mock()

        async def open_page(target, route="/capabilities"):
            target.views.append(types.SimpleNamespace(route=route))
            await target.push_route(route)

        demo = types.ModuleType("capability_demo")
        demo.open_page = AsyncMock(side_effect=open_page)
        with patch.dict(sys.modules, {"flet": flet, "capability_demo": demo}):
            await _page(page)
        return page, demo

    async def test_cold_link_opens_once_and_back_returns_to_root(self):
        page, demo = await self.page("/capabilities")
        demo.open_page.assert_awaited_once_with(page, route="/capabilities")
        self.assertEqual(len(page.views), 2)
        with patch.dict(sys.modules, {"capability_demo": demo}):
            await page.on_route_change(types.SimpleNamespace(route="/capabilities"))
        self.assertEqual(len(page.views), 2)
        await page.on_view_pop(None)
        self.assertEqual(len(page.views), 1)
        page.push_route.assert_awaited_with("/")

    async def test_warm_link_opens_after_ordinary_startup(self):
        page, demo = await self.page()
        demo.open_page.assert_not_awaited()
        with patch.dict(sys.modules, {"capability_demo": demo}):
            await page.on_route_change(types.SimpleNamespace(route="/capabilities"))
        demo.open_page.assert_awaited_once_with(page)
        self.assertEqual(len(page.views), 2)

    async def test_cold_query_link_preserves_route_and_opens_once(self):
        route = "/capabilities?probe=1"
        page, demo = await self.page(route)
        demo.open_page.assert_awaited_once_with(page, route=route)
        self.assertEqual(page.views[-1].route, route)
        with patch.dict(sys.modules, {"capability_demo": demo}):
            await page.on_route_change(types.SimpleNamespace(route=route))
        self.assertEqual(len(page.views), 2)

    async def test_warm_root_link_pops_capabilities(self):
        page, demo = await self.page("/capabilities")
        await page.on_route_change(types.SimpleNamespace(route="/?probe=1"))
        self.assertEqual(len(page.views), 1)
        self.assertEqual(page.views[0].route, "/?probe=1")

    async def test_changed_query_reuses_capabilities_view(self):
        page, demo = await self.page("/capabilities?probe=1")
        with patch.dict(sys.modules, {"capability_demo": demo}):
            await page.on_route_change(types.SimpleNamespace(route="/capabilities?probe=2"))
        self.assertEqual(len(page.views), 2)
        self.assertEqual(page.views[-1].route, "/capabilities?probe=2")
        demo.open_page.assert_awaited_once()

    async def test_unknown_initial_route_keeps_root_view(self):
        page, demo = await self.page("/unknown")
        demo.open_page.assert_not_awaited()
        self.assertEqual(len(page.views), 1)


if __name__ == "__main__":
    unittest.main()
