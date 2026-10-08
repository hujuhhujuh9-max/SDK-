"""Exercise initial and later routes without requiring Flet on the build-input host."""

import asyncio
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from runtime.sdk_bridge import _page
from runtime import sdk_bridge
from runtime import application_screens
from runtime.renfletpy import story


class PageRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        story.reset()
        sdk_bridge.update_save_status(False, "No saved game yet.")
        sdk_bridge.update_reading_status(False, "instant", "Reading choices kept.")
        sdk_bridge.publish_transcript(())
        sdk_bridge._quitting.clear()
        sdk_bridge.restore_story_status()
        self.pages = []

    async def asyncTearDown(self):
        for page in self.pages:
            await page.on_close(None)
        sdk_bridge.restore_story_status()

    async def page(self, route="/", *, record_loader=None, update_hook=None):
        page = types.SimpleNamespace(
            route=route, views=[types.SimpleNamespace(route="/")],
            update=Mock(), push_route=AsyncMock())
        if update_hook is not None:
            page.update.side_effect = lambda: update_hook(page)
        flet = types.ModuleType("flet")
        def control(*args, **kwargs):
            if args:
                kwargs["content"] = args[0]
                if type(args[0]) is list:
                    kwargs["controls"] = args[0]
                elif type(args[0]) is str:
                    kwargs["value"] = args[0]
            kwargs.setdefault("disabled", False)
            kwargs.setdefault("visible", True)
            return types.SimpleNamespace(**kwargs)

        for name in ("Text", "TextButton", "Button", "ProgressRing", "Row", "Column", "Container", "Theme", "TextTheme", "TextStyle", "View"):
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
        def records(target, **options):
            back = control(on_click=options["on_back"])
            async def current_back(event):
                await back.on_click(event)
            return types.SimpleNamespace(route=options["route"], on_back=current_back,
                                         _runner_back_control=back)
        recipe.create_form_list_view = AsyncMock(side_effect=record_loader or records)
        self.pages.append(page)
        # Route callbacks build new controls while the initial mount is pending.
        page._fake_flet = flet
        page._record_recipe = recipe
        with patch.dict(sys.modules, {"flet": flet, "capability_demo": demo,
                                     "form_list": recipe, "runtime.form_list": recipe}), patch.object(
                                         application_screens, "create_form_list_view", recipe.create_form_list_view):
            await _page(page)
        return page, demo

    async def change_route(self, page, route, demo=None):
        page.route = route
        modules = {"flet": page._fake_flet, "form_list": page._record_recipe,
                   "runtime.form_list": page._record_recipe}
        if demo is not None:
            modules["capability_demo"] = demo
        with patch.dict(sys.modules, modules), patch.object(
                application_screens, "create_form_list_view", page._record_recipe.create_form_list_view):
            await page.on_route_change(types.SimpleNamespace(route=route))

    def find_control(self, page, label):
        def walk(controls):
            for control in controls:
                if getattr(control, "content", None) == label or getattr(control, "value", None) == label:
                    return control
                children = getattr(control, "controls", [])
                if not children and not isinstance(getattr(control, "content", None), (str, list, type(None))):
                    children = [control.content]
                found = walk(children)
                if found is not None:
                    return found
            return None
        found = walk(page.views[-1].controls)
        self.assertIsNotNone(found, label)
        return found

    def story_button(self, page):
        return self.find_control(page, "Resume story" if sdk_bridge.app_story_status()["resume_available"]
                                 else "Start from beginning")

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

    async def drain(self, page):
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            for _ in range(4):
                await asyncio.sleep(0)

    async def test_app_cold_children_keep_queries_and_back_goes_to_app_home(self):
        for route in ("/app/story?source=cold", "/app/records?source=cold", "/app/settings?source=cold"):
            page, _ = await self.page(route)
            self.assertEqual([view.route for view in page.views], ["/app", route])
            self.assertEqual(sdk_bridge.presentation(), "page")
            await page.on_view_pop(None)
            page.push_route.assert_awaited_once_with("/app")
            await self.change_route(page, "/app?home=cold")
            await page.on_view_pop(None)
            page.push_route.assert_awaited_once()
            self.assertEqual([view.route for view in page.views], ["/app?home=cold"])

    async def test_app_records_query_reuses_view_and_retains_parent_for_back(self):
        page, _ = await self.page("/app?workspace=1")
        await self.change_route(page, "/app/records?record=1")
        view = page.views[-1]
        await self.change_route(page, "/app/records?record=2")
        self.assertIs(page.views[-1], view)
        page._record_recipe.create_form_list_view.assert_awaited_once()
        await page.on_view_pop(None)
        page.push_route.assert_awaited_with("/app?workspace=1")

    async def test_app_settings_back_and_story_back_retain_the_parent_query(self):
        page, _ = await self.page("/app?workspace=1")
        await self.change_route(page, "/app/settings")
        back = page.views[-1].controls[0].content[0].content[-1]
        await back.on_click(None)
        page.push_route.assert_awaited_with("/app?workspace=1")
        await self.change_route(page, "/app/story")
        back = self.find_control(page, "Return to app")
        await back.on_click(None)
        page.push_route.assert_awaited_with("/app?workspace=1")

    async def test_app_start_waits_for_confirmation_and_rejects_duplicate_clicks(self):
        page, _ = await self.page("/app?workspace=1")
        await self.change_route(page, "/app/story")
        start = self.story_button(page)
        await start.on_click(None)
        await start.on_click(None)
        page.push_route.assert_not_awaited()
        self.assertEqual(sdk_bridge.story_status()["state"], "idle")
        command = sdk_bridge.take_story_command()
        self.assertEqual(command["action"], "start")
        self.assertEqual(command["return_route"], "/app?workspace=1")
        self.assertIsNone(sdk_bridge.take_story_command())
        await self.drain(page)
        self.assertTrue(self.story_button(page).disabled)
        self.assertTrue(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        await self.drain(page)
        page.push_route.assert_awaited_once_with("/")
        self.assertFalse(sdk_bridge.confirm_story_command(command["request_id"], success=True))
        await self.drain(page)
        page.push_route.assert_awaited_once()

    async def test_native_confirmation_after_departure_keeps_the_selected_app_screen(self):
        import threading
        for destination in ("/app/records?edit=1", "/app/settings?reading=1"):
            sdk_bridge.restore_story_status()
            page, _ = await self.page("/app/story")
            await self.story_button(page).on_click(None)
            command = sdk_bridge.take_story_command()
            await self.change_route(page, destination)
            view = page.views[-1]
            page.update.reset_mock()
            worker = threading.Thread(target=lambda: sdk_bridge.confirm_story_command(
                command["request_id"], success=True, message="Native story started."))
            worker.start()
            worker.join(timeout=3)
            self.assertFalse(worker.is_alive())
            page.update.assert_not_called()
            await self.drain(page)
            self.assertEqual(page.route, destination)
            # Settings may refresh its confirmed reading controls; records keep
            # their existing view and unsubmitted edits.
            if "records" in destination:
                self.assertIs(page.views[-1], view)
            page.push_route.assert_not_awaited()
            self.assertEqual(sdk_bridge.story_status()["state"], "active")

    async def test_confirmation_queued_before_route_departure_cannot_navigate(self):
        page, _ = await self.page("/app/story")
        await self.story_button(page).on_click(None)
        command = sdk_bridge.take_story_command()
        sdk_bridge.confirm_story_command(command["request_id"], success=True)
        await self.change_route(page, "/app/settings")
        await self.drain(page)
        page.push_route.assert_not_awaited()
        self.assertEqual(page.views[-1].route, "/app/settings")

    async def test_stale_app_start_button_cannot_submit_after_route_departure(self):
        page, _ = await self.page("/app/story")
        button = self.story_button(page)
        await self.change_route(page, "/app/records")
        await button.on_click(None)
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertFalse(sdk_bridge.story_status()["busy"])

    async def test_failed_start_leaves_the_screen_and_enables_retry(self):
        page, _ = await self.page("/app/story")
        await self.story_button(page).on_click(None)
        command = sdk_bridge.take_story_command()
        sdk_bridge.confirm_story_command(command["request_id"], success=False, message="Try again.")
        await self.drain(page)
        page.push_route.assert_not_awaited()
        self.find_control(page, "Try again.")
        self.assertFalse(self.story_button(page).disabled)
        self.assertEqual(sdk_bridge.story_status()["state"], "idle")

    async def test_app_start_reenables_when_a_competing_save_finishes(self):
        self.assertTrue(sdk_bridge.request_save("save"))
        page, _ = await self.page("/app/story")
        self.assertTrue(self.story_button(page).disabled)
        sdk_bridge.update_save_status(True, "Saved.")
        await self.drain(page)
        self.assertFalse(self.story_button(page).disabled)

    async def test_same_route_reading_refresh_does_not_discard_story_confirmation(self):
        page, _ = await self.page("/app/story")
        await self.story_button(page).on_click(None)
        command = sdk_bridge.take_story_command()
        sdk_bridge.initialize_reading(False, "instant")
        sdk_bridge.confirm_story_command(command["request_id"], success=True)
        await self.drain(page)
        page.push_route.assert_awaited_once_with("/")

    async def test_initial_mount_reconciles_a_confirmation_published_before_subscribing(self):
        sdk_bridge.request_story("start")
        command = sdk_bridge.take_story_command()
        from runtime import application_screens as app_ui
        create = app_ui.app_story_view
        def create_while_confirming(*args, **kwargs):
            view = create(*args, **kwargs)
            sdk_bridge.confirm_story_command(command["request_id"], success=True)
            return view
        with patch.object(app_ui, "app_story_view", side_effect=create_while_confirming):
            page, _ = await self.page("/app/story")
        self.assertEqual(self.story_button(page).content, "Resume story")
        self.assertFalse(self.story_button(page).disabled)
        await self.drain(page)
        page.push_route.assert_not_awaited()

    async def test_initial_subscription_keeps_the_first_unchanged_controls_alive(self):
        buttons = []
        def remember(page):
            buttons.append(page.views[-1].controls[-1].content[0])
        page, _ = await self.page("/diagnostics", update_hook=remember)
        # Protocol clients can dispatch the initial button immediately. A
        # second identical render would retire its ID before that first event.
        self.assertIs(buttons[0], page.views[-1].controls[-1].content[0])
        initial = sdk_bridge.counter()
        buttons[0].on_click(None)
        self.assertEqual(sdk_bridge.counter(), initial + 1)

    async def test_recovery_or_new_request_during_ui_patch_invalidates_confirmed_navigation(self):
        for interrupt in ("recovery", "resume"):
            sdk_bridge.restore_story_status()
            page, _ = await self.page("/app/story")
            await self.story_button(page).on_click(None)
            command = sdk_bridge.take_story_command()
            await self.drain(page)
            updates = 0
            def patch_ui():
                nonlocal updates
                updates += 1
                if updates == 2:
                    if interrupt == "recovery":
                        sdk_bridge.restore_story_status("recovered-story")
                    else:
                        sdk_bridge.request_story("resume")
            page.update.side_effect = patch_ui
            sdk_bridge.confirm_story_command(command["request_id"], success=True)
            await self.drain(page)
            page.push_route.assert_not_awaited()
            self.assertEqual(page.route, "/app/story")

    async def test_back_from_optional_story_confirms_return_to_its_app_route(self):
        start_id = sdk_bridge.request_story("start", return_route="/app/records?workspace=1")
        sdk_bridge.take_story_command()
        sdk_bridge.confirm_story_command(start_id, success=True)
        page, _ = await self.page("/")
        await page.on_view_pop(None)
        await page.on_view_pop(None)
        page.push_route.assert_not_awaited()
        self.assertEqual(sdk_bridge.story_status()["state"], "active")
        command = sdk_bridge.take_story_command()
        self.assertEqual(command["action"], "return")
        self.assertEqual(command["session_id"], start_id)
        sdk_bridge.confirm_story_command(command["request_id"], success=True)
        await self.drain(page)
        page.push_route.assert_awaited_once_with("/app/records?workspace=1")
        self.assertEqual(sdk_bridge.story_status()["state"], "suspended")

    async def test_recovered_story_back_uses_its_restored_app_destination(self):
        sdk_bridge.restore_story_status("before-the-first-light", state="active",
                                        return_route="/app/records?workspace=recovered")
        page, _ = await self.page("/")
        await page.on_view_pop(None)
        command = sdk_bridge.take_story_command()
        self.assertEqual(command["return_route"], "/app/records?workspace=recovered")
        sdk_bridge.confirm_story_command(command["request_id"], success=True)
        await self.drain(page)
        page.push_route.assert_awaited_with("/app/records?workspace=recovered")

    async def test_stale_menu_return_button_does_not_interrupt_app_records(self):
        sdk_bridge.restore_story_status("before-the-first-light", state="active")
        page, _ = await self.page("/menu")
        button = next(control for control in page.views[-1].controls[0].content
                      if getattr(control, "content", None) == "Return to app")
        await self.change_route(page, "/app/records")
        await button.on_click(None)
        self.assertIsNone(sdk_bridge.take_story_command())
        await self.drain(page)
        page.push_route.assert_not_awaited()

    async def test_disconnect_retains_command_and_reconnect_refreshes_without_resubmitting(self):
        page, _ = await self.page("/app/story?resume=1")
        await self.story_button(page).on_click(None)
        command = sdk_bridge.take_story_command()
        await page.on_disconnect(None)
        sdk_bridge.confirm_story_command(command["request_id"], success=True)
        with patch.dict(sys.modules, {"flet": page._fake_flet}):
            await page.on_connect(object())
        await self.drain(page)
        self.assertEqual(page.views[-1].route, "/app/story?resume=1")
        self.assertEqual(self.story_button(page).content, "Resume story")
        self.assertEqual(len(story._listeners), 1)
        self.assertIsNone(sdk_bridge.take_story_command())
        page.push_route.assert_not_awaited()

    async def test_recovery_invalidates_pending_results_without_hijacking_app_routes(self):
        for route in ("/app", "/app/story", "/app/records?edit=1", "/app/settings?reading=1"):
            sdk_bridge.restore_story_status()
            pending_id = sdk_bridge.request_story("start")
            sdk_bridge.take_story_command()
            page, _ = await self.page(route)
            sdk_bridge.restore_story_status("before-the-first-light", state="suspended")
            sdk_bridge.resume_story()
            self.assertFalse(sdk_bridge.confirm_story_command(pending_id, success=True))
            await self.drain(page)
            self.assertEqual(page.route, route)
            self.assertEqual(page.views[-1].route, route)
            page.push_route.assert_not_awaited()

    async def test_queued_native_navigation_is_retired_on_disconnect_and_reconnect(self):
        for request in (sdk_bridge.open_menu, sdk_bridge.resume_story):
            page, _ = await self.page("/menu")
            request()
            await page.on_disconnect(None)
            with patch.dict(sys.modules, {"flet": page._fake_flet}):
                await page.on_connect(object())
            await self.drain(page)
            page.push_route.assert_not_awaited()

    async def test_queued_navigation_task_cannot_run_after_close(self):
        page, _ = await self.page("/menu")
        sdk_bridge.resume_story()
        await asyncio.sleep(0)  # The scheduler has created the navigation task.
        await page.on_close(None)
        await self.drain(page)
        page.push_route.assert_not_awaited()

    async def test_back_callback_from_a_disconnected_or_replaced_page_is_retired(self):
        page, _ = await self.page("/history")
        views = list(page.views)
        await page.on_disconnect(None)
        await page.on_view_pop(None)
        self.assertEqual(page.views, views)
        page.push_route.assert_not_awaited()
        old, _ = await self.page("/history")
        views = list(old.views)
        current, _ = await self.page("/app/records")
        await old.on_view_pop(None)
        self.assertEqual(old.views, views)
        old.push_route.assert_not_awaited()
        self.assertEqual(current.route, "/app/records")

    async def test_replaced_page_cannot_change_presentation_or_reclaim_callbacks(self):
        old, _ = await self.page()
        with patch.dict(sys.modules, {"flet": old._fake_flet}):
            story.show("Mira", "Queued on the old page.")
        current, _ = await self.page("/diagnostics")
        old.update.reset_mock()
        await self.drain(old)
        old.update.assert_not_called()
        self.assertEqual(sdk_bridge.presentation(), "diagnostics")
        await old.on_connect(object())
        await old.on_close(None)
        self.assertEqual(len(story._listeners), 1)
        sdk_bridge.open_menu()
        await self.drain(current)
        current.push_route.assert_not_awaited()
        self.assertEqual(sdk_bridge.presentation(), "diagnostics")

    async def test_return_result_after_opening_settings_cannot_replace_the_screen(self):
        sdk_bridge.restore_story_status("before-the-first-light", state="active")
        page, _ = await self.page("/")
        await page.on_view_pop(None)
        command = sdk_bridge.take_story_command()
        await self.change_route(page, "/app/settings")
        sdk_bridge.confirm_story_command(command["request_id"], success=True)
        await self.drain(page)
        page.push_route.assert_not_awaited()
        self.assertEqual(page.views[-1].route, "/app/settings")

    async def test_confirmation_back_keeps_story_and_result_back_keeps_app_parent(self):
        page, _ = await self.page("/app?workspace=1")
        for route in ("/app/story/start?confirm=1", "/app/story/cancel?confirm=1"):
            await self.change_route(page, route)
            await page.on_view_pop(None)
            page.push_route.assert_awaited_with("/app/story")
            self.assertIsNone(sdk_bridge.take_story_command())
        await self.change_route(page, "/app/story/result?read=1")
        await page.on_view_pop(None)
        page.push_route.assert_awaited_with("/app?workspace=1")

    async def test_old_start_confirmation_cannot_replace_a_recovered_session(self):
        sdk_bridge.restore_story_status("before-the-first-light", state="active")
        page, _ = await self.page("/app/story/start")
        button = self.find_control(page, "Start again")
        recovered = sdk_bridge.restore_story_status("before-the-first-light", state="suspended")
        await button.on_click(None)
        self.assertIsNone(sdk_bridge.take_story_command())
        self.assertEqual(sdk_bridge.story_status()["session_id"], recovered)
        self.find_control(page, "Reload story status")
        page.push_route.assert_not_awaited()

    async def test_cancel_waits_for_confirmation_and_does_not_hijack_records(self):
        session = sdk_bridge.restore_story_status("before-the-first-light", state="active")
        page, _ = await self.page("/app/story")
        await self.find_control(page, "Cancel story").on_click(None)
        page.push_route.assert_awaited_once_with("/app/story/cancel")
        self.assertIsNone(sdk_bridge.take_story_command())
        await self.change_route(page, "/app/story/cancel")
        await self.find_control(page, "Confirm cancellation").on_click(None)
        self.assertEqual(sdk_bridge.story_status()["state"], "active")
        command = sdk_bridge.take_story_command()
        self.assertEqual((command["action"], command["session_id"]), ("cancel", session))
        await self.change_route(page, "/app/records?draft=1")
        view = page.views[-1]
        sdk_bridge.confirm_story_command(command["request_id"], success=True)
        await self.drain(page)
        page.push_route.assert_awaited_once()
        self.assertEqual(sdk_bridge.story_status()["state"], "cancelled")
        self.assertIs(page.views[-1], view)

    async def test_native_completion_opens_result_once_only_from_the_current_story(self):
        session = sdk_bridge.restore_story_status("before-the-first-light", state="active")
        page, _ = await self.page("/")
        sdk_bridge.finish_story(session, result=[0, False])
        await self.drain(page)
        page.push_route.assert_awaited_once_with("/app/story/result")
        self.assertFalse(sdk_bridge.finish_story(session, result="duplicate"))
        await self.drain(page)
        page.push_route.assert_awaited_once()
        await self.change_route(page, "/app/story/result")
        self.find_control(page, "Result: [0, false]")

    async def test_native_end_queued_before_navigation_is_retired_even_after_returning_to_story(self):
        for outcome in ("return", "complete"):
            session = sdk_bridge.restore_story_status("before-the-first-light", state="active")
            page, _ = await self.page("/")
            if outcome == "return":
                sdk_bridge.return_from_story(session)
            else:
                sdk_bridge.finish_story(session, result="done")
            await self.change_route(page, "/app/records")
            await self.change_route(page, "/")
            await self.drain(page)
            page.push_route.assert_not_awaited()

    async def test_pre_busy_choice_and_star_callbacks_cannot_complete_native_input(self):
        for kind, label in (("panel", "Sky"), ("star_map", "Deneb")):
            story.reset()
            sdk_bridge.restore_story_status("before-the-first-light", state="active")
            revision = story.show("Mira", "Pending input", (("sky", "Sky"),), kind=kind)
            page, _ = await self.page("/")
            button = self.find_control(page, label)
            request = sdk_bridge.request_story("return")
            await button.on_click(None)
            self.assertIsNone(story.current().selected)
            self.assertEqual(story.current().progress, ())
            self.assertIsNone(story.consume(revision))
            sdk_bridge.take_story_command()
            sdk_bridge.confirm_story_command(request, success=False)
            await self.drain(page)
            await self.find_control(page, label).on_click(None)
            if kind == "panel":
                self.assertEqual(story.consume(revision), "sky")
            else:
                self.assertEqual(story.current().progress, ("deneb",))

    async def test_retired_dialogue_inputs_and_menu_cannot_hijack_another_route(self):
        story.show("Mira", "Pending input", (("sky", "Sky"),))
        page, _ = await self.page("/")
        choice = self.find_control(page, "Sky")
        menu = self.find_control(page, "Menu")
        await self.change_route(page, "/app/records")
        await choice.on_click(None)
        await menu.on_click(None)
        self.assertIsNone(story.current().selected)
        page.push_route.assert_not_awaited()
        await self.change_route(page, "/")
        await choice.on_click(None)
        self.assertIsNone(story.current().selected)
        await page.on_disconnect(None)
        await self.find_control(page, "Sky").on_click(None)
        self.assertIsNone(story.current().selected)

    async def test_reload_rebuilds_same_route_after_a_stale_view_rejection(self):
        page, _ = await self.page("/app/story")
        old = self.story_button(page)
        sdk_bridge.restore_story_status()
        await old.on_click(None)
        reload_button = self.find_control(page, "Reload story status")
        self.assertTrue(reload_button.visible)
        await reload_button.on_click(None)
        fresh = self.story_button(page)
        self.assertIsNot(fresh, old)
        await fresh.on_click(None)
        self.assertEqual(sdk_bridge.take_story_command()["action"], "start")
        page.push_route.assert_not_awaited()

    async def test_native_initialization_during_mount_refreshes_disabled_controls_without_navigation(self):
        sdk_bridge.configure_app_story("before-the-first-light", "Before the First Light", initializing=True)
        self.assertIsNone(sdk_bridge.request_story("start"))
        create = application_screens.app_story_view
        def finish_initialization(*args, **kwargs):
            view = create(*args, **kwargs)
            sdk_bridge.restore_story_status()
            return view
        with patch.object(application_screens, "app_story_view", side_effect=finish_initialization):
            page, _ = await self.page("/app/story")
        self.assertFalse(sdk_bridge.app_story_status()["loading"])
        self.assertFalse(self.story_button(page).disabled)
        page.push_route.assert_not_awaited()

    async def test_old_start_confirmation_cannot_reopen_a_session_that_already_returned(self):
        page, _ = await self.page("/app/story")
        await self.story_button(page).on_click(None)
        command = sdk_bridge.take_story_command()
        sdk_bridge.confirm_story_command(command["request_id"], success=True)
        sdk_bridge.return_from_story(command["session_id"])
        await self.drain(page)
        self.assertEqual(sdk_bridge.story_status()["state"], "suspended")
        page.push_route.assert_not_awaited()

    async def test_old_return_navigation_cannot_override_a_newer_terminal_result(self):
        for mailbox in (False, True):
            session = sdk_bridge.restore_story_status("before-the-first-light", state="active")
            page, _ = await self.page("/")
            if mailbox:
                request = sdk_bridge.request_story("return")
                sdk_bridge.take_story_command()
                sdk_bridge.confirm_story_command(request, success=True)
            else:
                sdk_bridge.return_from_story(session)
            sdk_bridge.finish_story(session, result="done")
            await self.drain(page)
            page.push_route.assert_awaited_once_with("/app/story/result")

    async def test_optional_native_replay_uses_confirmation_and_never_sets_legacy_restart(self):
        sdk_bridge.configure_app_story("lantern", "The Last Lantern", native_host=True)
        try:
            sdk_bridge.restore_story_status("lantern", state="active")
            page, _ = await self.page("/menu")
            await self.find_control(page, "Replay story").on_click(None)
            page.push_route.assert_awaited_once_with("/app/story/start")
            self.assertIsNone(sdk_bridge.take_story_command())
            self.assertFalse(sdk_bridge.request_restart())
            self.assertFalse(story.restarting())
            await self.change_route(page, "/restart")
            await self.find_control(page, "Start again").on_click(None)
            command = sdk_bridge.take_story_command()
            self.assertEqual(command["action"], "start")
            self.assertFalse(story.restarting())
        finally:
            sdk_bridge.restore_story_status()
            sdk_bridge.configure_app_story("before-the-first-light", "Before the First Light")


if __name__ == "__main__":
    unittest.main()
