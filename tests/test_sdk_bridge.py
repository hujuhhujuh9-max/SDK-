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
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        sdk_bridge.publish_transcript(())
        sdk_bridge._quitting.clear()
        self.pages = []

    async def asyncTearDown(self):
        for page in self.pages:
            await page.on_close(None)

    async def page(self, route="/", *, record_loader=None):
        page = types.SimpleNamespace(
            route=route, views=[types.SimpleNamespace(route="/")],
            update=Mock(), push_route=AsyncMock())
        flet = types.ModuleType("flet")
        def control(*args, **kwargs):
            if args:
                kwargs["content"] = args[0]
            return types.SimpleNamespace(**kwargs)

        for name in ("Text", "TextButton", "Button", "Row", "Column", "Container", "Theme", "TextTheme", "TextStyle", "View"):
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
        recipe = types.ModuleType("form_list")
        recipe.create_form_list_view = AsyncMock(side_effect=record_loader or (
            lambda target, **options:
            types.SimpleNamespace(route=options["route"], on_back=options["on_back"])))
        self.pages.append(page)
        # Route callbacks build new controls while the initial mount is pending.
        page._fake_flet = flet
        page._record_recipe = recipe
        with patch.dict(sys.modules, {"flet": flet, "capability_demo": demo,
                                     "form_list": recipe, "runtime.form_list": recipe}):
            await _page(page)
        return page, demo

    async def change_route(self, page, route, demo=None):
        modules = {"flet": page._fake_flet, "form_list": page._record_recipe,
                   "runtime.form_list": page._record_recipe}
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

    async def test_records_cold_query_link_reuses_view_and_back_returns_to_diagnostics(self):
        page, demo = await self.page("/records?source=cold")
        factory = page._record_recipe.create_form_list_view
        factory.assert_awaited_once()
        self.assertEqual([view.route for view in page.views],
                         ["/diagnostics", "/records?source=cold"])
        view = page.views[-1]
        self.assertEqual(sdk_bridge.presentation(), "page")
        await self.change_route(page, "/records?source=warm")
        self.assertIs(page.views[-1], view)
        self.assertEqual(view.route, "/records?source=warm")
        factory.assert_awaited_once()
        demo.open_page.assert_not_awaited()
        await view.on_back(None)
        page.push_route.assert_awaited_with("/diagnostics")
        await self.change_route(page, "/diagnostics")
        self.assertEqual(len(page.views), 1)
        self.assertEqual(sdk_bridge.presentation(), "diagnostics")

    async def test_records_are_optional_and_preserve_the_pending_story_revision(self):
        revision = story.show("Mira", "Still waiting", (("sky", "Sky"),))
        page, _ = await self.page()
        page._record_recipe.create_form_list_view.assert_not_awaited()
        await self.change_route(page, "/records")
        self.assertEqual(story.current().revision, revision)
        self.assertEqual(len(story._listeners), 1)
        self.assertEqual(sdk_bridge.presentation(), "page")
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            self.assertTrue(story.choose(revision, "sky"))
            await asyncio.sleep(0)
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertEqual(story.current().selected, "sky")
        await self.change_route(page, "/")
        self.assertEqual(sdk_bridge.presentation(), "interlude")
        self.assertEqual(story.consume(revision), "sky")
        self.assertIsNone(story.consume(revision))
        self.assertFalse(story.choose(revision - 1, "sky"))

    async def test_leaving_records_discards_the_view_and_reentry_loads_a_fresh_one(self):
        page, _ = await self.page("/records")
        view = page.views[-1]
        await self.change_route(page, "/diagnostics")
        await self.change_route(page, "/records")
        self.assertIsNot(page.views[-1], view)
        self.assertEqual(page._record_recipe.create_form_list_view.await_count, 2)

    async def test_slow_records_load_cannot_replace_a_newer_story_route(self):
        page, _ = await self.page()
        entered = asyncio.Event()
        async def load(target, **options):
            entered.set()
            await asyncio.Future()
        page._record_recipe.create_form_list_view.side_effect = load
        opening = asyncio.create_task(self.change_route(page, "/records"))
        await asyncio.wait_for(entered.wait(), 3)
        await self.change_route(page, "/")
        await asyncio.wait_for(opening, 3)
        self.assertEqual([view.route for view in page.views], ["/"])
        self.assertEqual(sdk_bridge.presentation(), "scene")

    async def test_concurrent_records_query_links_share_one_load_and_keep_latest_query(self):
        page, _ = await self.page()
        entered, release = asyncio.Event(), asyncio.Event()
        async def load(target, **options):
            entered.set()
            await release.wait()
            return types.SimpleNamespace(route=options["route"])
        factory = page._record_recipe.create_form_list_view
        factory.side_effect = load
        first = asyncio.create_task(self.change_route(page, "/records?first"))
        await asyncio.wait_for(entered.wait(), 3)
        second = asyncio.create_task(self.change_route(page, "/records?latest"))
        await asyncio.sleep(0)
        release.set()
        await asyncio.wait_for(asyncio.gather(first, second), 3)
        factory.assert_awaited_once()
        self.assertEqual([view.route for view in page.views],
                         ["/diagnostics", "/records?latest"])

    async def test_records_startup_cannot_restore_callbacks_after_close_or_disconnect(self):
        for event in ("on_close", "on_disconnect"):
            with self.subTest(event=event):
                entered = asyncio.get_running_loop().create_future()

                async def load(target, **options):
                    entered.set_result(target)
                    await asyncio.Future()

                opening = asyncio.create_task(self.page("/records", record_loader=load))
                page = await asyncio.wait_for(entered, 3)
                try:
                    await getattr(page, event)(None)
                    await asyncio.wait_for(opening, 3)
                    self.assertEqual(len(story._listeners), 0)
                    for name in ("_story_detach", "_menu_request", "_resume_request",
                                 "_save_refresh", "_history_refresh", "_reading_refresh"):
                        self.assertIsNone(getattr(sdk_bridge, name), name)

                    page._record_recipe.create_form_list_view.side_effect = (
                        lambda target, **options: types.SimpleNamespace(route=options["route"]))
                    with patch.dict(sys.modules, {"flet": page._fake_flet,
                                                 "runtime.form_list": page._record_recipe}):
                        await page.on_connect(object())
                    self.assertEqual(len(story._listeners), 1)
                    self.assertEqual(page.views[-1].route, "/records")
                finally:
                    if not opening.done():
                        opening.cancel()
                    await asyncio.gather(opening, return_exceptions=True)
                    await page.on_close(None)

    async def test_leaving_records_during_startup_keeps_the_story_connected(self):
        entered = asyncio.get_running_loop().create_future()

        async def load(target, **options):
            entered.set_result(target)
            await asyncio.Future()

        opening = asyncio.create_task(self.page("/records", record_loader=load))
        page = await asyncio.wait_for(entered, 3)
        try:
            page.route = "/"
            await self.change_route(page, "/")
            await asyncio.wait_for(opening, 3)
            self.assertEqual([view.route for view in page.views], ["/"])
            self.assertEqual(len(story._listeners), 1)
            self.assertIsNotNone(sdk_bridge._menu_request)
        finally:
            if not opening.done():
                opening.cancel()
            await asyncio.gather(opening, return_exceptions=True)

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

    async def test_native_tactics_keeps_flet_hidden_and_resumes_the_same_board_after_menus(self):
        revision = story.minigame("tactics")
        page, _ = await self.page()
        self.assertEqual(page.views[0].controls, [])
        self.assertEqual(sdk_bridge.presentation(), "scene")
        await self.change_route(page, "/menu")
        self.assertEqual(sdk_bridge.presentation(), "page")
        story.select_tactics_unit(revision, "knight")
        await asyncio.sleep(0)
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertEqual(page.views[0].controls, [])
        await self.change_route(page, "/")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertEqual(story.current().selected_unit, "knight")
        await page.on_disconnect(None)
        restored = story.restore(story.snapshot())
        await page.on_connect(None)
        self.assertGreater(restored, revision)
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertEqual(page.views[0].controls, [])

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
        for route in ("/diagnostics", "/capabilities?probe=cold", "/records?probe=cold"):
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

    async def test_reconnect_refreshes_history_and_save_status_changed_while_disconnected(self):
        page, _ = await self.page("/history")
        await page.on_disconnect(None)
        sdk_bridge.publish_transcript((("Mira", "Published while disconnected.", ""),))
        sdk_bridge.update_save_status(True, "Saved while disconnected.")
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            await page.on_connect(object())
        card, = page.views[-1].controls[1].content
        self.assertEqual(card.content.content[1].content, "Published while disconnected.")
        menu = page.views[-2].controls[0].content
        self.assertEqual(menu[4].content, "Saved while disconnected.")
        self.assertFalse(menu[3].content[1].disabled)

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

    async def test_reading_controls_queue_once_without_changing_the_pending_interlude(self):
        revision = story.minigame("star_map")
        story.tap_star(revision, "deneb")
        page, _ = await self.page("/settings")
        larger = page.views[-1].controls[0].content[2].content[1]
        await larger.on_click(None)
        self.assertFalse(sdk_bridge.reading_status()["large_text"])
        self.assertEqual(sdk_bridge.take_reading_request(), ("large_text", True))
        self.assertIsNone(sdk_bridge.take_reading_request())
        self.assertFalse(sdk_bridge.request_quit())
        self.assertFalse(sdk_bridge.request_restart())
        self.assertFalse(sdk_bridge.request_save("save"))
        await larger.on_click(None)  # A stale button cannot enqueue twice.
        self.assertIsNone(sdk_bridge.take_reading_request())
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            sdk_bridge.update_reading_status(True, "instant", "Kept.")
            await asyncio.sleep(0)
            await asyncio.sleep(0)
        self.assertEqual(page.views[-1].controls[0].content[1].content, "Text size: Larger")
        self.assertEqual(page.views[-1].controls[0].content[3].size, 25)
        self.assertEqual(page.theme.text_theme.label_large.size, 18)
        self.assertEqual(story.current().revision, revision)
        self.assertEqual(story.current().progress, ("deneb",))
        await self.change_route(page, "/")
        self.assertEqual(page.views[0].controls[0].content.content[1].size, 25)
        self.assertEqual(sdk_bridge.presentation(), "interlude")

    async def test_reading_reconnect_refreshes_preferences_and_detaches_queued_updates(self):
        page, _ = await self.page("/settings")
        await page.on_disconnect(None)
        sdk_bridge.update_reading_status(True, "animated", "Kept while disconnected.")
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            await page.on_connect(object())
        content = page.views[-1].controls[0].content
        self.assertEqual(content[1].content, "Text size: Larger")
        self.assertEqual(content[4].content, "Dialogue: Animated")
        page.update.reset_mock()
        sdk_bridge.initialize_reading(False, "instant")  # Queued before disposal.
        await page.on_close(None)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        page.update.assert_not_called()
        self.assertIsNone(sdk_bridge._reading_refresh)

    async def test_save_busy_and_invalid_preferences_cannot_queue_persistent_writes(self):
        self.assertTrue(sdk_bridge.request_save("save"))
        self.assertFalse(sdk_bridge.request_reading("large_text", True))
        for name, value in (("large_text", 1), ("text_speed", "fast"), ("unknown", True)):
            with self.assertRaises(ValueError):
                sdk_bridge.request_reading(name, value)
        self.assertIsNone(sdk_bridge.take_reading_request())

    async def test_finishing_a_save_reenables_settings_and_replay_opened_while_busy(self):
        for route in ("/settings", "/restart"):
            self.assertTrue(sdk_bridge.request_save("save"))
            page, _ = await self.page(route)
            action = (page.views[-1].controls[0].content[2].content[1] if route == "/settings"
                      else page.views[-1].controls[0].content[2])
            self.assertTrue(action.disabled)
            with patch.dict(sys.modules, {"flet": page._fake_flet}):
                sdk_bridge.update_save_status(True, "Saved.")
                await asyncio.sleep(0)
            action = (page.views[-1].controls[0].content[2].content[1] if route == "/settings"
                      else page.views[-1].controls[0].content[2])
            self.assertFalse(action.disabled)
            await page.on_close(None)


if __name__ == "__main__":
    unittest.main()
