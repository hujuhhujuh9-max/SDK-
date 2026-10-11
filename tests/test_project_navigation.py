"""Project pages use normal SDK routing and preserve models across native flow."""

import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest import mock

from runtime.app_navigation import NavigationState, ScreenRegistry, ScreenView
from runtime import app_home, app_session, sdk_bridge
from runtime.project_api import ensure_project_setup
from runtime.story_activities import activities
from runtime.renfletpy import story
from test_app_starter_protocol import AppStarterPageCase, FLET_AVAILABLE

ROOT = Path(__file__).resolve().parents[1]
if FLET_AVAILABLE:
    import flet as ft
    from flet.messaging.protocol import MessageAction


class ScreenRegistrationTests(unittest.TestCase):
    def test_dynamic_links_aliases_query_and_state_ownership(self):
        registry = ScreenRegistry()
        registry.register("/app/item/{item_id}", lambda ctx: None,
                          aliases=("/item/{item_id}",), parent="/app", state_factory=lambda: {"draft": ""})
        state = NavigationState()
        first = registry.match("/app/item/hello%20world?source=story")
        self.assertEqual(first.params, {"item_id": "hello world"})
        first_state = state.state_for(first)
        first_state["draft"] = "kept"
        self.assertIs(state.state_for(registry.match("/item/hello%20world?source=link")), first_state)
        self.assertEqual(state.state_for(registry.match("/item/other")), {"draft": ""})
        self.assertIsNone(registry.match("/item/not%2Fa%2Fsegment"))

    def test_conflicts_and_bad_models_fail_before_navigation(self):
        registry = ScreenRegistry()
        for path in ("/app", "/menu", "/records", "/app/saves", "/bad?query=1", "/bad//path",
                     "/{top}", "/app/{section}", "/{root}/saves"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                registry.register(path, lambda ctx: None)
        registry.register("/app/item/{id}", lambda ctx: None)
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            registry.register("/app/item/{other}", lambda ctx: None)
        for key in ("sdk.records", "sdk.saved-games"):
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "namespace"):
                registry.register("/app/project", lambda ctx: None, state_key=key)
        registry.register("/app/bad", lambda ctx: None, state_factory=lambda: {"service": object()})
        with self.assertRaises(TypeError):
            NavigationState().state_for(registry.match("/app/bad"))

    def test_literal_precedence_and_direct_link_back_parent(self):
        registry = ScreenRegistry()
        registry.register("/app/item/{id}", lambda ctx: None, parent="/app/items")
        literal = registry.register("/app/item/new", lambda ctx: None)
        self.assertIs(registry.match("/app/item/new").definition, literal)
        state = NavigationState()
        state.visit("/app/item/mira?first=1")
        state.visit("/app/item/mira?first=2")
        self.assertEqual(state.app_history, ["/app/item/mira?first=2"])
        self.assertEqual(state.back_target(registry.match(state.app_history[-1])), "/app/items")


class ProjectSetupTests(unittest.TestCase):
    def test_hook_runs_once_and_failed_registration_is_atomic(self):
        module = types.ModuleType("navigation_setup_fixture")
        calls = []

        def register(api):
            calls.append(api)
            api.register_screen("/app/setup", lambda ctx: None)

        module.register = register
        config = types.SimpleNamespace(PROJECT_SETUP="navigation_setup_fixture:register")
        with mock.patch.dict(sys.modules, {"runtime.project_config": config,
                                           "navigation_setup_fixture": module}):
            first = ensure_project_setup()
            self.assertIs(ensure_project_setup(), first)
        self.assertEqual(len(calls), 1)

        def failing(api):
            api.register_activity("setup_atomic_fixture", version=1, create_state=dict,
                                  renderer=lambda ctx: [], reduce=lambda state, name, value: state)
            raise ValueError("Project setup failed")

        module.register = failing
        with mock.patch.dict(sys.modules, {"runtime.project_config": types.SimpleNamespace(
                PROJECT_SETUP="navigation_setup_fixture:register"), "navigation_setup_fixture": module}):
            with self.assertRaisesRegex(ValueError, "Project setup failed"):
                ensure_project_setup()
        self.assertFalse(activities.contains("setup_atomic_fixture"))


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class ProjectNavigationProtocolTests(AppStarterPageCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        spec = importlib.util.spec_from_file_location("navigation_project_fixture", ROOT / "examples/project_app/my_app.py")
        self.module = importlib.util.module_from_spec(spec)
        self.config = types.SimpleNamespace(STARTUP_TEMPLATE="app", APP_HOME="navigation_project_fixture:app_home_view",
                                            PROJECT_SETUP="navigation_project_fixture:register")
        self.modules = mock.patch.dict(sys.modules, {"runtime.project_config": self.config,
                                                     "navigation_project_fixture": self.module, "app_home": app_home})
        self.modules.start()
        spec.loader.exec_module(self.module)

    async def asyncTearDown(self):
        await self.close_page()
        self.modules.stop()
        await super().asyncTearDown()

    def field(self, label):
        return next(c for c in self.all_controls() if isinstance(c, ft.TextField) and c.label == label)

    async def draft(self, value):
        field = self.field("Notebook draft")
        self.transport.apply_patch(field._i, {"value": value})
        await self.transport.dispatch_event(field._i, "change", None)
        await self.settled()

    async def test_project_multipage_story_return_keeps_draft_and_selection(self):
        await self.open_page("/app/notebook")
        await self.draft("A draft before the story")
        await self.click("Select Rowan")
        old_start = self.button("Start notebook story")
        await self.click("Start notebook story")
        self.assertEqual(self.page.route, "/app/notebook")
        command = app_session.session.take_request()
        self.assertEqual(command["action"], "start")
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/")
        story.show("A note", "Keep the story pending", (("keep", "Keep note"),))
        revision = story.current().revision
        await self.settled()
        await self.navigate("/menu")
        await self.click("Return to app")
        command = app_session.session.take_request()
        self.assertEqual(command["action"], "return")
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/app/notebook")
        self.assertEqual(self.field("Notebook draft").value, "A draft before the story")
        self.assertIn("Selected: rowan", self.visible_text())
        self.assertEqual(story.current().revision, revision)
        await old_start.on_click(None)
        self.assertIsNone(app_session.session.take_request())
        await self.click("Open lighthouse entry")
        self.assertEqual(self.page.route, "/app/entries/lighthouse?source=notebook")
        self.assertIn("Draft: A draft before the story", self.visible_text())
        await self.click("Back")
        self.assertEqual(self.page.route, "/app/notebook")

    async def test_direct_parameter_link_and_unknown_link_do_not_reveal_story(self):
        await self.open_page("/app/entries/balcony?source=direct")
        self.assertIn("Entry: balcony", self.visible_text())
        await self.click("Back")
        self.assertEqual(self.page.route, "/app/notebook")
        app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        story.show("Secret", "Do not expose returned story")
        await self.navigate("/app/unregistered")
        self.assertEqual(self.page.route, "/app")
        self.assertNotIn("Do not expose returned story", self.visible_text())

    async def test_dialog_back_dismisses_without_navigating_or_starting_story(self):
        app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        await self.open_page("/app/notebook")
        await self.click("Start notebook story")
        self.assertTrue(any(dialog.open for dialog in self.page._dialogs.controls))
        self.assertIsNone(app_session.session.take_request())
        await self.page.on_view_pop(None)
        self.assertEqual(self.page.route, "/app/notebook")
        self.assertFalse(any(dialog.open for dialog in self.page._dialogs.controls))
        self.assertIsNone(app_session.session.take_request())
        await self.page.on_view_pop(None)
        self.assertEqual(self.page.route, "/app")

    async def test_confirmed_client_back_keeps_the_dialog_screen_until_sdk_navigation(self):
        app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        await self.open_page("/app/notebook")
        await self.draft("Dialog draft")
        await self.click("Start notebook story")
        view = self.page.views[-1]
        self.assertFalse(view.can_pop)
        self.assertIsNotNone(view.on_confirm_pop)
        ids = [control._i for control in self.page.views]
        await self.transport.dispatch_event(view._i, "confirm_pop", None)
        await self.settled()
        self.assertEqual(self.page.route, "/app/notebook")
        self.assertEqual([control._i for control in self.page.views], ids)
        self.assertFalse(any(dialog.open for dialog in self.page._dialogs.controls))
        self.assertIsNone(app_session.session.take_request())
        reply = self.connection.calls[-1]
        self.assertEqual((reply.control_id, reply.name, reply.args),
                         (view._i, "confirm_pop", {"should_pop": False}))
        await self.transport.dispatch_event(view._i, "confirm_pop", None)
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(self.page._runner_navigation_state.states[
            "project.notebook"]["draft"], "Dialog draft")

    async def test_confirm_reply_cannot_apply_back_after_a_new_route_intent(self):
        await self.open_page("/app/notebook")
        await self.click("Open lighthouse entry")
        view = self.page.views[-1]
        confirmed = asyncio.Event()
        reply = asyncio.Event()
        route_reply = asyncio.Event()
        pushed = []

        async def confirm(should_pop):
            self.assertFalse(should_pop)
            confirmed.set()
            await reply.wait()

        async def delayed_route(route):
            pushed.append(route)
            await route_reply.wait()
            await self.navigate(route)

        self.page.push_route = delayed_route
        with mock.patch.object(view, "confirm_pop", confirm):
            pending = asyncio.create_task(view.on_confirm_pop(types.SimpleNamespace(control=view)))
            await confirmed.wait()
            back = asyncio.create_task(self.click("Back"))
            await self.settled()
            self.assertEqual(pushed, ["/app/notebook"])
            self.assertIs(self.page.views[-1], view)
            reply.set()
            await pending
            self.assertEqual(pushed, ["/app/notebook"])
            self.assertEqual(self.page._runner_navigation_state.app_history, ["/app/notebook"])
            route_reply.set()
            await back
        self.assertEqual(self.page.route, "/app/notebook")

    async def test_retired_view_confirmation_does_not_invoke_a_native_method(self):
        await self.open_page("/app/notebook")
        view = self.page.views[-1]
        callback = view.on_confirm_pop
        await self.click("Open lighthouse entry")
        with mock.patch.object(view, "confirm_pop", new_callable=mock.AsyncMock) as confirm:
            await callback(types.SimpleNamespace(control=view))
            confirm.assert_not_awaited()
        self.assertEqual(self.page.route, "/app/entries/lighthouse?source=notebook")

    async def test_real_confirmation_reply_after_unmount_does_not_report_a_runtime_error(self):
        await self.open_page("/app/notebook")
        view = self.page.views[-1]
        requests = []
        requested = asyncio.Event()
        send = self.connection.send_message

        def withhold_confirmation(message):
            if message.action == MessageAction.INVOKE_METHOD and message.body.name == "confirm_pop":
                self.connection.encode([message.action, message.body])
                requests.append(message.body)
                requested.set()
            else:
                send(message)

        with mock.patch.object(self.connection, "send_message", withhold_confirmation):
            pending = asyncio.create_task(self.transport.dispatch_event(view._i, "confirm_pop", None))
            await asyncio.wait_for(requested.wait(), 1)
            await self.click("Open lighthouse entry")
            self.assertNotIn(view._i, self.transport.index)
            request = requests[0]
            with self.assertNoLogs(level="ERROR"):
                self.transport.handle_invoke_method_results(request.control_id, request.call_id, None, None)
                await pending
        self.assertEqual(self.page.route, "/app/entries/lighthouse?source=notebook")
        await self.click("Back")
        self.assertEqual(self.page.route, "/app/notebook")

    async def test_active_view_confirmation_failure_is_reported_and_can_be_retried(self):
        await self.open_page("/app/notebook")
        view = self.page.views[-1]
        send = self.connection.send_message

        def reject_confirmation(message):
            if message.action == MessageAction.INVOKE_METHOD and message.body.name == "confirm_pop":
                request = message.body
                self.connection.loop.call_soon(self.transport.handle_invoke_method_results,
                                              request.control_id, request.call_id, None, "Native confirmation failed")
            else:
                send(message)

        with mock.patch.object(self.connection, "send_message", reject_confirmation), self.assertLogs(level="ERROR") as logs:
            await self.transport.dispatch_event(view._i, "confirm_pop", None)
        self.assertTrue(any("Native confirmation failed" in line for line in logs.output))
        self.assertEqual(self.page.route, "/app/notebook")
        await self.transport.dispatch_event(view._i, "confirm_pop", None)
        self.assertEqual(self.page.route, "/app")

    async def test_explicit_project_pop_policy_is_not_overwritten(self):
        renderer = self.module.notebook
        policy = mock.AsyncMock()

        def custom(context):
            view = renderer(context)
            view.can_pop = False
            view.on_confirm_pop = policy
            return view

        self.module.notebook = custom
        await self.open_page("/app/notebook")
        view = self.page.views[-1]
        self.assertIs(view.on_confirm_pop, policy)
        await self.transport.dispatch_event(view._i, "confirm_pop", None)
        policy.assert_awaited_once()
        self.assertEqual(self.page.route, "/app/notebook")

    async def test_rebuild_reconnect_and_recovery_keep_model_retire_controls(self):
        await self.open_page("/app/notebook")
        await self.draft("Rebuild me")
        old_select = self.button("Select Rowan")
        sdk_bridge.update_reading_status(True, "instant", "Bigger text")
        await self.settled()
        self.assertEqual(self.field("Notebook draft").value, "Rebuild me")
        await old_select.on_click(None)
        self.assertIn("Selected: mira", self.visible_text())
        sdk_bridge.resume_story()
        await self.settled()
        self.assertEqual(self.page.route, "/app/notebook")
        await self.page.on_disconnect(None)
        await self.page.on_connect(types.SimpleNamespace())
        await self.settled()
        self.assertEqual(self.field("Notebook draft").value, "Rebuild me")

    async def test_records_and_saved_game_drafts_remount_through_same_registry(self):
        await self.open_page("/app/records")
        title = self.field("Title")
        self.transport.apply_patch(title._i, {"value": "Record draft"})
        await self.navigate("/app/notebook")
        await self.navigate("/app/records")
        self.assertEqual(self.field("Title").value, "Record draft")
        await self.navigate("/app/saves")
        self.assertEqual(sdk_bridge.take_save_request(), "list")
        sdk_bridge.publish_save_slots(())
        sdk_bridge.update_save_status(False, "Ready")
        await self.settled()
        self.transport.apply_patch(self.field("Save name")._i, {"value": "Save name draft"})
        await self.navigate("/app/notebook")
        await self.navigate("/app/saves")
        self.assertEqual(self.field("Save name").value, "Save name draft")
        sdk_bridge.take_save_request()
        sdk_bridge.update_save_status(False, "Ready")

    async def test_late_native_ack_respects_new_custom_route(self):
        await self.open_page("/app/notebook")
        await self.draft("Before acknowledgement")
        await self.click("Start notebook story")
        command = app_session.session.take_request()
        await self.navigate("/app/entries/lighthouse")
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/app/entries/lighthouse")
        self.assertIn("Draft: Before acknowledgement", self.visible_text())

    async def test_retired_async_factory_disposes_its_late_result_once(self):
        started = asyncio.Event()
        cancelled, disposed = [], []
        register = self.module.register

        async def slow(ctx):
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.append(True)
            return ScreenView(ft.View(route=ctx.route, controls=[ft.Text("Late screen")]),
                              dispose=lambda: disposed.append(True))

        def setup(api):
            register(api)
            api.register_screen("/app/slow", slow)

        self.module.register = setup
        self.prepare_page("/app/slow")
        opening = asyncio.create_task(sdk_bridge._page(self.page))
        await started.wait()
        await self.navigate("/app/notebook")
        await opening
        await self.settled()
        self.assertTrue(cancelled)
        self.assertNotIn("Late screen", self.visible_text())
        self.assertEqual(disposed, [True])
        await self.navigate("/app")
        self.assertEqual(disposed, [True])

    async def test_story_browsers_keep_their_parent_and_app_history(self):
        await self.open_page("/app/notebook")
        await self.click("Start notebook story")
        command = app_session.session.take_request()
        self.assertTrue(app_session.session.finish(command["command_id"]))
        await self.settled()
        history = list(self.page._runner_navigation_state.app_history)
        await self.navigate("/menu")
        await self.click("Saved games")
        self.assertEqual(self.page.route, "/saves")
        self.assertEqual(sdk_bridge.take_save_request(), "list")
        sdk_bridge.publish_save_slots(())
        sdk_bridge.update_save_status(False, "Ready")
        await self.settled()
        await self.click("Back")
        self.assertEqual(self.page.route, "/menu")
        self.assertTrue(app_session.session.status()["showing_story"])
        await self.navigate("/records")
        await self.click("Back")
        self.assertEqual(self.page.route, "/diagnostics")
        self.assertEqual(self.page._runner_navigation_state.app_history, history)

    async def test_query_change_keeps_one_pending_factory_and_disposer(self):
        started, finish = asyncio.Event(), asyncio.Event()
        calls, disposed = [], []
        register = self.module.register

        async def slow(ctx):
            calls.append(ctx)
            started.set()
            await finish.wait()
            return ScreenView(ft.View(route=ctx.route, controls=[ft.Text("Query " + ctx.query["q"][0])]),
                              dispose=lambda: disposed.append(True))

        def setup(api):
            register(api)
            api.register_screen("/app/query", slow)

        self.module.register = setup
        self.prepare_page("/app/query?q=first")
        opening = asyncio.create_task(sdk_bridge._page(self.page))
        await started.wait()
        navigation = asyncio.create_task(self.navigate("/app/query?q=latest"))
        await asyncio.sleep(0)
        finish.set()
        await asyncio.gather(opening, navigation)
        await self.settled()
        self.assertEqual(len(calls), 1)
        self.assertEqual(disposed, [])
        self.assertIn("Query latest", self.visible_text())
        await self.navigate("/app/notebook")
        self.assertEqual(disposed, [True])


if __name__ == "__main__":
    unittest.main()
