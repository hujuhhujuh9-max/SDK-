"""Real Flet routing during the native saved-story confirmation visibility scope.

The native producer is represented by the taken command and its acknowledgement.
These cases exercise actual Flet controls, client events and preference messages;
the native/Android probes separately establish prompt rendering and save loading.
"""

import asyncio
import os
import tempfile
import unittest
from unittest import mock

from runtime import app_session, sdk_bridge
from runtime.application_data import DEFAULT_STORAGE_KEY
from test_app_starter_protocol import AppStarterPageCase, FLET_AVAILABLE
from test_form_list_flet import PreferencesConnection

if FLET_AVAILABLE:
    import flet as ft
    from flet.controls.context import _context_page
    from flet.messaging.protocol import MessageAction
    from flet.messaging.session import Session


class DelayedRouteConnection(PreferencesConnection):
    """Hold real Page.push_route calls separately from client route events."""

    def __init__(self, values):
        super().__init__(values)
        self.route_requests = asyncio.Queue()
        self.pending_routes = {}
        self.client_route = None

    def send_message(self, message):
        if message.action == MessageAction.SESSION_CRASHED:
            raise AssertionError("Flet session reported an error: " + str(message.body))
        if message.action == MessageAction.INVOKE_METHOD and message.body.name == "push_route":
            self.encode([message.action, message.body])
            request = message.body
            self.calls.append(request)
            self.pending_routes[request.call_id] = request
            self.route_requests.put_nowait(request)
        else:
            super().send_message(message)

    def acknowledge_route(self, request):
        self.pending_routes.pop(request.call_id, None)
        self.session.handle_invoke_method_results(request.control_id, request.call_id, None, None)


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class AppConfirmationProtocolTests(AppStarterPageCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        sdk_bridge._stopping.clear()
        self.scope_command_id = None

    async def asyncTearDown(self):
        if self.scope_command_id is not None:
            sdk_bridge.end_app_story_load(self.scope_command_id)
        await super().asyncTearDown()
        sdk_bridge._stopping.clear()

    async def saved_resume(self):
        self.assertTrue(app_session.session.initialize_saved(True))
        await self.open_page()
        self.assertFalse(self.button("Resume story").disabled)
        self.assertIn("Resume from your saved place.", self.visible_text())
        await self.click("Resume story")
        command = app_session.session.take_request()
        self.assertIsNotNone(command)
        self.assertEqual(command["action"], "resume")
        self.assertTrue(app_session.session.status()["busy"])
        self.assertEqual(app_session.session.status()["resume_kind"], "saved")
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(sdk_bridge.presentation(), "page")
        return command

    def begin_load(self, command):
        self.assertTrue(sdk_bridge.begin_app_story_load(command["command_id"]))
        self.scope_command_id = command["command_id"]
        self.assertEqual(sdk_bridge.presentation(), "scene")

    def end_load(self, command):
        self.assertTrue(sdk_bridge.end_app_story_load(command["command_id"]))
        if self.scope_command_id == command["command_id"]:
            self.scope_command_id = None

    def title_field(self):
        return next(control for control in self.all_controls()
                    if isinstance(control, ft.TextField) and control.label == "Title")

    async def records_draft(self, route, value):
        await self.navigate(route)
        view = self.page.views[-1]
        field = self.title_field()
        self.transport.apply_patch(field._i, {"value": value})
        await self.transport.dispatch_event(field._i, "change", None)
        self.assertEqual(field.value, value)
        self.assertEqual([call.name for call in self.connection.calls], ["get"])
        return view, field

    async def test_saved_resume_shows_native_confirmation_without_completing_home_navigation(self):
        command = await self.saved_resume()
        self.begin_load(command)
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertTrue(self.button("Resume story").disabled)
        self.assertTrue(self.button("Start story").disabled)
        self.assertFalse(sdk_bridge.request_quit())

        # A declined native load acknowledges failure before its finally block
        # releases visibility. A queued Flet status refresh cannot hide the prompt.
        self.assertTrue(app_session.session.finish(command["command_id"], success=False,
                                                  message="Resume cancelled."))
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.end_load(command)
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertEqual(self.page.route, "/app")
        self.assertFalse(app_session.session.status()["busy"])
        self.assertEqual(app_session.session.status()["resume_kind"], "saved")
        self.assertFalse(self.button("Resume story").disabled)
        self.assertIn("Resume cancelled.", self.visible_text())
        self.assertIsNone(app_session.session.take_request())

    async def test_new_records_link_and_draft_survive_native_load_cancellation(self):
        command = await self.saved_resume()
        # A newer deep link can arrive before the native timer opens its prompt.
        view, field = await self.records_draft("/app/records?source=before-prompt", "Keep this draft")
        self.begin_load(command)
        await self.navigate("/app/records?source=during-prompt")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(field.value, "Keep this draft")
        self.assertEqual([call.name for call in self.connection.calls], ["get"])

        self.assertTrue(app_session.session.finish(command["command_id"], success=False,
                                                  message="Resume cancelled."))
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.end_load(command)
        await self.settled()
        self.assertEqual(self.page.route, "/app/records?source=during-prompt")
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(field.value, "Keep this draft")
        self.assertFalse(app_session.session.status()["busy"])
        self.assertFalse(self.button("Add record").disabled)
        self.assertEqual(self.values, {})
        self.assertIsNone(app_session.session.take_request())
        await self.click("Back")
        self.assertEqual(self.page.route, "/app")
        self.assertFalse(self.button("Resume story").disabled)
        self.assertIn("Resume cancelled.", self.visible_text())

    async def test_saved_resume_acknowledgement_does_not_hijack_new_records_during_scope(self):
        command = await self.saved_resume()
        self.begin_load(command)
        view, field = await self.records_draft("/app/records?source=after-prompt", "Newer app draft")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        old_revision = command["revision"]
        restored = app_session.session.restore(command_id=command["command_id"])
        self.assertGreater(restored, old_revision)
        await self.settled()
        self.assertEqual(self.page.route, "/app/records?source=after-prompt")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        # Ownership outlives the mailbox acknowledgement, so finally can release
        # this scope even after native restoration advances the story revision.
        self.end_load(command)
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertEqual(self.page.route, "/app/records?source=after-prompt")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(field.value, "Newer app draft")
        self.assertFalse(app_session.session.status()["busy"])
        self.assertEqual(app_session.session.status()["resume_kind"], "live")
        self.assertIsNone(app_session.session.take_request())

    async def test_stale_scope_release_after_reconnect_cannot_hide_a_new_native_prompt(self):
        old_command = await self.saved_resume()
        self.begin_load(old_command)
        await self.page.on_disconnect(None)
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertTrue(app_session.session.finish(old_command["command_id"], success=False,
                                                  message="Resume cancelled."))
        # The native finally owns release even when no Flet page is connected.
        self.end_load(old_command)
        self.assertEqual(sdk_bridge.presentation(), "scene")
        await self.page.on_connect(object())
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertFalse(self.button("Resume story").disabled)

        await self.click("Resume story")
        new_command = app_session.session.take_request()
        self.assertIsNotNone(new_command)
        self.assertNotEqual(new_command["command_id"], old_command["command_id"])
        self.begin_load(new_command)
        self.assertFalse(sdk_bridge.end_app_story_load(old_command["command_id"]))
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertTrue(app_session.session.status()["busy"])
        self.assertEqual(self.page.route, "/app")
        self.assertTrue(app_session.session.finish(new_command["command_id"], success=False,
                                                  message="Resume cancelled."))
        self.end_load(new_command)
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertFalse(self.button("Resume story").disabled)
        self.assertEqual(len(app_session.session._listeners), 1)

    async def test_reconnect_keeps_unanswered_native_confirmation_visible(self):
        command = await self.saved_resume()
        self.begin_load(command)
        await self.page.on_disconnect(None)
        await self.page.on_connect(object())
        await self.settled()
        self.assertTrue(app_session.session.status()["busy"])
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertTrue(self.button("Resume story").disabled)
        self.assertTrue(self.button("Start story").disabled)
        self.assertIsNone(app_session.session.take_request())
        self.assertEqual(len(app_session.session._listeners), 1)

        self.assertTrue(app_session.session.finish(command["command_id"], success=False,
                                                  message="Resume cancelled."))
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.end_load(command)
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertEqual(self.page.route, "/app")
        self.assertFalse(app_session.session.status()["busy"])
        self.assertFalse(self.button("Resume story").disabled)
        self.assertIn("Resume cancelled.", self.visible_text())

    async def test_backend_stop_and_finalization_keep_pending_native_scope_on_reconnect(self):
        command = await self.saved_resume()
        self.begin_load(command)
        # Run the real backend stop/start/finally lifecycle with its socket entry
        # stubbed; the page above still uses the actual pinned-Flet transport.
        with tempfile.TemporaryDirectory() as private, \
                mock.patch.dict(os.environ, {"ANDROID_PRIVATE": private,
                                             "ANDROID_CACHE": private + "/cache"}), \
                mock.patch.object(sdk_bridge, "_thread", None), \
                mock.patch.object(ft, "run_async", new_callable=mock.AsyncMock) as serve:
            sdk_bridge.stop()
            await self.page.on_disconnect(None)
            sdk_bridge.start()
            thread = sdk_bridge._thread
            await asyncio.to_thread(thread.join, 2)
            if thread.is_alive():
                sdk_bridge.stop()
            self.assertFalse(thread.is_alive(), "Fixture backend did not finalize")
            serve.assert_awaited_once()
            self.assertIsNone(sdk_bridge._loop)
            self.assertIsNone(sdk_bridge._task)

        await self.page.on_connect(object())
        await self.settled()
        self.assertTrue(app_session.session.status()["busy"])
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertTrue(self.button("Resume story").disabled)
        self.assertIsNone(app_session.session.take_request())
        self.assertTrue(app_session.session.finish(command["command_id"], success=False,
                                                  message="Resume cancelled."))
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.end_load(command)
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "page")
        self.assertFalse(self.button("Resume story").disabled)
        self.assertIn("Resume cancelled.", self.visible_text())


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class AppRouteRpcTests(AppStarterPageCase):
    def prepare_page(self, route):
        self.connection = DelayedRouteConnection(self.values)
        self.transport = Session(self.connection)
        self.connection.session = self.transport
        self.page = self.transport.page
        self.page.route = route
        self.connection.client_route = route
        self.token = _context_page.set(self.page)
        self.connection.encode(self.transport.get_page_patch())
        self.client_events = []
        # Keep Page.push_route intact: the existing fixture's navigate adapter
        # acknowledges route changes synchronously and cannot exercise this race.

    async def asyncTearDown(self):
        if self.page is not None:
            await self.page.on_disconnect(None)
            for request in list(self.connection.pending_routes.values()):
                self.connection.acknowledge_route(request)
            await self.settled()
            for event in self.client_events:
                if not event.done():
                    event.cancel()
            await asyncio.gather(*self.client_events, return_exceptions=True)
        await super().asyncTearDown()

    async def next_route(self, route):
        request = await asyncio.wait_for(self.connection.route_requests.get(), 1)
        self.assertEqual(request.args, {"route": route})
        self.assertEqual(request.control_id, self.page._i)
        return request

    async def client_route_event(self, route):
        self.connection.client_route = route
        return await self.release_buffered_route_event(route)

    def apply_route_rpc(self, request):
        route = request.args["route"]
        if route == self.connection.client_route:
            return None
        self.connection.client_route = route
        return route

    async def release_buffered_route_event(self, route):
        # Dart's onRouteUpdated sends a page property update and then an event.
        # Releasing an older buffered event does not change actual RouteState.
        self.transport.apply_patch(self.page._i, {"route": route})
        event = asyncio.create_task(self.transport.dispatch_event(
            self.page._i, "route_change", {"route": route}))
        self.client_events.append(event)
        await self.settled()
        return event

    async def acknowledge(self, request):
        self.connection.acknowledge_route(request)
        await self.settled()

    def title_field(self):
        return next(control for control in self.all_controls()
                    if isinstance(control, ft.TextField) and control.label == "Title")

    async def type_title(self, text):
        field = self.title_field()
        self.transport.apply_patch(field._i, {"value": text})
        await self.transport.dispatch_event(field._i, "change", None)
        return field

    async def records_with_data(self, route):
        event = await self.client_route_event(route)
        await asyncio.wait_for(event, 1)
        await self.type_title("Created after native navigation")
        await self.click("Add record")
        self.assertIn("Record saved", self.visible_text())
        field = await self.type_title("Keep the unsubmitted draft")
        return self.page.views[-1], field, self.values[DEFAULT_STORAGE_KEY]

    def assert_records_retained(self, route, view, field, data):
        self.assertEqual(self.page.route, route)
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(view.route, route)
        self.assertEqual(field.value, "Keep the unsubmitted draft")
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], data)
        self.assertIn("Title: Created after native navigation", self.visible_text())
        self.assertEqual(sdk_bridge.presentation(), "page")

    async def finish_repair(self, request):
        await self.client_route_event(request.args["route"])
        await self.acknowledge(request)
        await asyncio.wait_for(asyncio.gather(*self.client_events), 1)
        self.assertTrue(self.connection.route_requests.empty())

    async def test_inflight_app_resume_route_cannot_replace_new_records_on_echo_before_ack(self):
        app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        await self.open_page("/app")
        self.assertNotIn("push_route", self.page.__dict__)
        await self.click("Resume story")
        command = app_session.session.take_request()
        self.assertEqual(command["action"], "resume")
        self.assertTrue(app_session.session.finish(command["command_id"]))
        resume = await self.next_route("/")

        route = "/app/records?source=newer-than-resume"
        view, field, data = await self.records_with_data(route)
        await self.client_route_event(resume.args["route"])
        self.assert_records_retained(route, view, field, data)
        await self.acknowledge(resume)
        repair = await self.next_route(route)
        await self.finish_repair(repair)
        self.assertEqual(self.connection.client_route, route)
        self.assert_records_retained(route, view, field, data)

    async def test_native_recovery_ack_before_echo_cannot_replace_newer_records(self):
        app_session.session.restore(phase="active", resume_kind="live", showing_story=True)
        await self.open_page("/menu")
        sdk_bridge.resume_story()
        resume = await self.next_route("/")
        await self.acknowledge(resume)
        # A native status update may be queued before Dart's route-change event.
        sdk_bridge.initialize_reading(True, "instant")
        await self.settled()
        self.assertEqual(sdk_bridge.presentation(), "scene")

        route = "/app/records?source=after-native-rpc"
        view, field, data = await self.records_with_data(route)
        await self.client_route_event(resume.args["route"])
        self.assert_records_retained(route, view, field, data)
        repair = await self.next_route(route)
        await self.finish_repair(repair)
        self.assertEqual(self.connection.client_route, route)
        self.assert_records_retained(route, view, field, data)

    async def test_newer_external_query_wins_during_delayed_native_menu_route_repair(self):
        app_session.session.restore(phase="active", resume_kind="live", showing_story=True)
        await self.open_page("/app")
        await self.client_route_event("/")
        sdk_bridge.open_menu()
        menu = await self.next_route("/menu")
        first = "/app/records?source=before-menu-echo"
        view, field, data = await self.records_with_data(first)
        await self.client_route_event(menu.args["route"])
        self.assert_records_retained(first, view, field, data)
        await self.acknowledge(menu)
        first_repair = await self.next_route(first)

        latest = "/app/records?source=during-repair"
        event = await self.client_route_event(latest)
        await asyncio.wait_for(event, 1)
        self.assert_records_retained(latest, view, field, data)
        await self.client_route_event(first_repair.args["route"])
        self.assert_records_retained(latest, view, field, data)
        await self.acknowledge(first_repair)
        latest_repair = await self.next_route(latest)
        await self.finish_repair(latest_repair)
        self.assertEqual(self.connection.client_route, latest)
        self.assert_records_retained(latest, view, field, data)

    async def test_native_same_target_ack_without_echo_cannot_swallow_later_explicit_route(self):
        app_session.session.restore(phase="active", resume_kind="live", showing_story=True)
        await self.open_page("/menu")
        sdk_bridge.open_menu()
        await self.settled()
        # RouteState does not emit an event when the client's exact route is
        # already the requested value. Suppressing this no-op RPC is valid too.
        if not self.connection.route_requests.empty():
            menu = await self.next_route("/menu")
            self.assertEqual(self.connection.client_route, menu.args["route"])
            await self.acknowledge(menu)
        self.assertEqual(self.page.route, "/menu")

        route = "/app/records?source=after-menu-noop"
        view, field, data = await self.records_with_data(route)
        self.assert_records_retained(route, view, field, data)
        event = await self.client_route_event("/menu")
        self.assertEqual(self.page.route, "/menu")
        self.assertEqual(self.page.views[-1].route, "/menu")
        self.assertIn("Paused", self.visible_text())
        self.assertFalse(self.button("Quick save").disabled)
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], data)
        await asyncio.wait_for(event, 1)
        self.assertTrue(self.connection.route_requests.empty())

    async def test_repeated_native_resume_without_second_echo_cannot_swallow_later_story_link(self):
        app_session.session.restore(phase="active", resume_kind="live", showing_story=True)
        await self.open_page("/menu")
        sdk_bridge.resume_story()
        sdk_bridge.resume_story()
        first = await self.next_route("/")
        await self.settled()
        repeated = None
        if not self.connection.route_requests.empty():
            repeated = await self.next_route("/")
        await self.client_route_event(first.args["route"])
        await self.acknowledge(first)
        # A coalesced request needs no second RPC; if one was already sent,
        # Flutter acknowledges it without another route event for the same '/'.
        if repeated is not None:
            self.assertEqual(self.connection.client_route, repeated.args["route"])
            await self.acknowledge(repeated)
        self.assertTrue(self.connection.route_requests.empty())
        self.assertEqual(self.page.route, "/")

        route = "/app/records?source=after-repeat-resume"
        view, field, data = await self.records_with_data(route)
        self.assert_records_retained(route, view, field, data)
        event = await self.client_route_event("/")
        self.assertEqual(self.page.route, "/")
        self.assertEqual(self.page.views[-1].route, "/")
        self.assertEqual(sdk_bridge.presentation(), "scene")
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], data)
        await asyncio.wait_for(event, 1)
        self.assertTrue(self.connection.route_requests.empty())

    async def test_reconnect_pending_route_echo_cannot_replace_new_records(self):
        app_session.session.restore(phase="active", resume_kind="live", showing_story=True)
        await self.open_page("/menu")
        sdk_bridge.resume_story()
        resume = await self.next_route("/")
        await self.page.on_disconnect(None)
        await self.page.on_connect(object())
        await self.settled()
        route = "/app/records?source=after-route-reconnect"
        view, field, data = await self.records_with_data(route)
        await self.client_route_event(resume.args["route"])
        self.assert_records_retained(route, view, field, data)
        await self.acknowledge(resume)
        repair = await self.next_route(route)
        await self.finish_repair(repair)
        self.assertEqual(self.connection.client_route, route)
        self.assert_records_retained(route, view, field, data)
        self.assertEqual(len(app_session.session._listeners), 1)

    async def test_records_reopen_after_external_home_requires_fresh_rpc_and_back_event(self):
        await self.open_page("/app")
        first_click = asyncio.create_task(self.transport.dispatch_event(
            self.button("Application records")._i, "click", None))
        self.client_events.append(first_click)
        first = await self.next_route("/app/records")
        old_records_event = self.apply_route_rpc(first)
        self.assertEqual(old_records_event, "/app/records")
        self.assertEqual(self.page.route, "/app")

        # Flutter already applied the first RPC, but its event is buffered.
        # An external Home link then becomes the client's actual route and is
        # accepted by the backend before the user opens Records again.
        await self.client_route_event("/app")
        second_click = asyncio.create_task(self.transport.dispatch_event(
            self.button("Application records")._i, "click", None))
        self.client_events.append(second_click)
        second = await self.next_route("/app/records")
        self.assertNotEqual(second.call_id, first.call_id)

        await self.release_buffered_route_event(old_records_event)
        self.assertEqual(self.connection.client_route, "/app")
        await self.acknowledge(first)
        fresh_records_event = self.apply_route_rpc(second)
        self.assertEqual(fresh_records_event, "/app/records")
        await self.release_buffered_route_event(fresh_records_event)
        await self.acknowledge(second)
        self.assertEqual(self.page.views[-1].route, "/app/records")
        self.assertEqual(self.connection.client_route, "/app/records")
        await self.type_title("Saved after reopening Records")
        await self.click("Add record")
        data = self.values[DEFAULT_STORAGE_KEY]

        back_click = asyncio.create_task(self.transport.dispatch_event(
            self.button("Back")._i, "click", None))
        self.client_events.append(back_click)
        back = await self.next_route("/app")
        home_event = self.apply_route_rpc(back)
        self.assertEqual(home_event, "/app", "Back must change actual client RouteState")
        await self.release_buffered_route_event(home_event)
        await self.acknowledge(back)
        await asyncio.wait_for(asyncio.gather(*self.client_events), 1)
        self.assertEqual(self.page.route, "/app")
        self.assertEqual(self.connection.client_route, "/app")
        self.assertEqual(self.page.views[-1].route, "/app")
        self.assertIn("App home", self.visible_text())
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], data)
        self.assertTrue(self.connection.route_requests.empty())


if __name__ == "__main__":
    unittest.main()
