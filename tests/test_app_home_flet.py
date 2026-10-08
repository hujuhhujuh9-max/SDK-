"""Exercise optional app controls through pinned Flet serialization and events."""

import asyncio
import importlib.util
import unittest
from unittest.mock import AsyncMock, Mock

from runtime.app_home import app_home_view
from runtime.story_ui import menu_view
from scripts.flet_protocol import walk

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as ft
    import msgpack
    from flet.controls.base_control import BaseControl
    from flet.controls.context import _context_page
    from flet.messaging.connection import Connection
    from flet.messaging.protocol import MessageAction, configure_encode_object_for_msgpack
    from flet.messaging.session import Session
    from flet.pubsub.pubsub_hub import PubSubHub
else:
    Connection = object


class AppConnection(Connection):
    """Encode actual Flet messages; these controls need no native services."""

    def __init__(self):
        super().__init__()
        self.page_url = "flet://runner"
        self.pubsubhub = PubSubHub(loop=asyncio.get_running_loop())
        self.messages = []

    def encode(self, value):
        return msgpack.unpackb(msgpack.packb(
            value, default=configure_encode_object_for_msgpack(BaseControl)),
            strict_map_key=False)

    def send_message(self, message):
        self.messages.append(self.encode([message.action, message.body]))
        if message.action == MessageAction.INVOKE_METHOD:
            raise AssertionError("App UI must not invoke native services")


def control_tree(control):
    yield control
    for child in getattr(control, "controls", []):
        yield from control_tree(child)
    content = getattr(control, "content", None)
    if FLET_AVAILABLE and isinstance(content, BaseControl):
        yield from control_tree(content)


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class AppHomeFletTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = AppConnection()
        self.session = Session(self.connection)
        self.page = self.session.page
        self.token = _context_page.set(self.page)
        self.connection.encode(self.session.get_page_patch())
        self.routes = []
        self.commands = []
        self.accept = True
        self.status = {"story_id": "app-recipe", "revision": 7, "phase": "ready",
                       "busy": False, "resume_available": False, "resume_kind": "unavailable",
                       "message": "Ready for a story.", "result": None, "app_mode": True}

    async def asyncTearDown(self):
        _context_page.reset(self.token)
        self.session.close()
        await asyncio.sleep(0)

    async def navigate(self, route):
        self.routes.append(route)

    def request(self, action, revision, *, replace=False):
        self.commands.append((action, revision, replace))
        return self.accept

    async def mount(self, status=..., **options):
        view = app_home_view(self.page, self.navigate,
                             self.status if status is ... else status, self.request, **options)
        self.page.views[:] = [view]
        self.page.update()
        return view

    def button(self, view, label, index=0):
        matches = [item for item in control_tree(view)
                   if isinstance(item, (ft.Button, ft.TextButton)) and item.content == label]
        return matches[index]

    def text_values(self, view):
        return [item.value for item in control_tree(view) if isinstance(item, ft.Text)]

    def progress(self, view):
        return next(item for item in control_tree(view) if isinstance(item, ft.ProgressRing))

    async def click(self, control):
        await self.session.dispatch_event(control._i, "click", None)

    def wire_values(self):
        return list(walk(self.connection.messages))

    async def test_factory_keeps_routes_callbacks_and_services_with_real_serialization(self):
        self.page.route = "/diagnostics"
        callbacks = {name: AsyncMock() for name in (
            "on_route_change", "on_view_pop", "on_connect", "on_disconnect", "on_close")}
        for name, callback in callbacks.items():
            setattr(self.page, name, callback)
        views = list(self.page.views)
        services = list(self.page._services._services)
        sent = len(self.connection.messages)
        view = app_home_view(self.page, self.navigate, self.status, self.request,
                             route="/app?entry=test", large_text=True)
        self.assertIsInstance(view, ft.View)
        self.assertEqual(view.route, "/app?entry=test")
        self.assertEqual(self.page.views, views)
        self.assertEqual(self.page.route, "/diagnostics")
        for name, callback in callbacks.items():
            self.assertIs(getattr(self.page, name), callback)
        self.assertEqual(list(self.page._services._services), services)
        self.assertEqual(len(self.connection.messages), sent)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.routes, [])
        self.assertEqual(view.controls[0].controls[0].size, 38)
        self.page.views[:] = [view]
        self.page.update()
        values = self.wire_values()
        self.assertIn("App home", values)
        self.assertIn("ProgressRing", values)
        self.assertIn("Start story", values)
        self.assertIn("Waiting for the story", values)

    async def test_records_uses_only_the_injected_route_callback(self):
        view = await self.mount()
        await self.click(self.button(view, "Application records"))
        self.assertEqual(self.routes, ["/app/records"])
        self.assertEqual(self.commands, [])
        self.assertEqual(list(self.page._services._services), [])

    async def test_start_latches_before_duplicate_events_and_does_not_navigate(self):
        view = await self.mount()
        start = self.button(view, "Start story")
        await self.click(start)
        await self.click(start)
        await self.click(self.button(view, "Resume story"))
        await self.click(self.button(view, "Application records"))
        self.assertEqual(self.commands, [("start", 7, False)])
        self.assertEqual(self.routes, [])
        self.assertTrue(start.disabled)
        self.assertTrue(self.button(view, "Application records").disabled)
        self.assertTrue(self.progress(view).visible)
        self.assertIn("Starting story…", self.wire_values())

    async def test_loading_and_native_busy_reject_forged_control_events(self):
        for status in (None, dict(self.status, busy=True, message="Loading a saved place…")):
            with self.subTest(status=status):
                view = await self.mount(status)
                self.assertTrue(self.progress(view).visible)
                for label in ("Start story", "Resume story", "Application records"):
                    control = self.button(view, label)
                    self.assertTrue(control.disabled)
                    await self.click(control)
        self.assertEqual(self.commands, [])
        self.assertEqual(self.routes, [])

    async def test_live_resume_uses_the_rendered_revision_and_never_claims_a_save(self):
        self.status.update(phase="active", resume_available=True, resume_kind="live")
        view = await self.mount()
        self.status["revision"] = 8
        self.assertIn("Your story is kept in this session. Quick save in the story menu keeps a saved place.",
                      self.text_values(view))
        resume = self.button(view, "Resume story")
        await self.click(resume)
        await self.click(resume)
        self.assertEqual(self.commands, [("resume", 7, False)])
        self.assertEqual(self.routes, [])

    async def test_cancel_replacement_preserves_progress_without_submitting(self):
        self.status.update(phase="active", resume_available=True, resume_kind="live")
        view = await self.mount()
        start = self.button(view, "Start story")
        confirm = self.button(view, "Start new story")
        # A stale/forged confirmation cannot bypass showing the question.
        await self.click(confirm)
        self.assertEqual(self.commands, [])
        await self.click(start)
        self.assertTrue(start.disabled)
        self.assertTrue(self.button(view, "Resume story").disabled)
        await self.click(self.button(view, "Resume story"))
        await self.click(self.button(view, "Cancel"))
        await self.click(confirm)
        self.assertEqual(self.commands, [])
        self.assertFalse(start.disabled)
        self.assertFalse(self.button(view, "Resume story").disabled)
        await self.click(self.button(view, "Resume story"))
        self.assertEqual(self.commands, [("resume", 7, False)])

    async def test_saved_checkpoint_requires_confirmation_even_in_ready_phase(self):
        self.status.update(resume_available=True, resume_kind="saved")
        view = await self.mount()
        self.assertIn("Resume from your saved place.", self.text_values(view))
        await self.click(self.button(view, "Start story"))
        self.assertEqual(self.commands, [])
        confirm = self.button(view, "Start new story")
        await self.click(confirm)
        await self.click(confirm)
        await self.click(self.button(view, "Start story"))
        self.assertEqual(self.commands, [("start", 7, True)])
        self.assertEqual(self.routes, [])

    async def test_old_confirmation_keeps_rendered_revision_for_native_rejection(self):
        self.status.update(resume_available=True, resume_kind="saved")
        accepted = []

        def guarded_request(action, revision, *, replace=False):
            if revision != self.status["revision"]:
                return False
            accepted.append((action, revision, replace))
            return True

        view = app_home_view(self.page, self.navigate, self.status, guarded_request)
        self.page.views[:] = [view]
        self.page.update()
        await self.click(self.button(view, "Start story"))
        self.status["revision"] = 8
        await self.click(self.button(view, "Start new story"))
        self.assertEqual(accepted, [])
        self.assertFalse(self.progress(view).visible)
        self.assertFalse(self.button(view, "Start story").disabled)
        self.assertEqual(self.routes, [])

    async def test_saved_resume_is_distinct_from_live_and_unavailable_resume(self):
        view = await self.mount()
        unavailable = self.button(view, "Resume story")
        self.assertTrue(unavailable.disabled)
        await self.click(unavailable)
        self.status.update(resume_available=True, resume_kind="saved")
        view = await self.mount()
        await self.click(self.button(view, "Resume story"))
        self.assertEqual(self.commands, [("resume", 7, False)])

    async def test_rejected_or_failed_request_releases_controls_and_keeps_home(self):
        self.accept = False
        view = await self.mount()
        await self.click(self.button(view, "Start story"))
        self.assertFalse(self.button(view, "Start story").disabled)
        self.assertFalse(self.progress(view).visible)
        self.assertIn("The story status changed. Wait for its update and try again.",
                      self.wire_values())
        self.assertEqual(self.routes, [])
        failing = Mock(side_effect=RuntimeError("Mailbox unavailable"))
        view = app_home_view(self.page, self.navigate, self.status, failing)
        self.page.views[:] = [view]
        self.page.update()
        with self.assertLogs(level="ERROR"):
            await self.click(self.button(view, "Start story"))
        self.assertFalse(self.button(view, "Start story").disabled)
        self.assertFalse(self.progress(view).visible)
        self.assertIn("The story request could not be sent. Try again.", self.wire_values())

    async def test_fresh_native_status_releases_submission_and_displays_error(self):
        view = await self.mount()
        await self.click(self.button(view, "Start story"))
        self.status.update(revision=8, message="Could not start this story. Try again.")
        updated = await self.mount()
        self.assertFalse(self.button(updated, "Start story").disabled)
        self.assertIn("Could not start this story. Try again.", self.wire_values())
        await self.click(self.button(updated, "Start story"))
        self.assertEqual(self.commands, [("start", 7, False), ("start", 8, False)])

    async def test_completion_shows_matching_plain_result_without_resubmission(self):
        result = {"story_id": "app-recipe", "outcome": "completed",
                  "value": "You shared the lighthouse note."}
        self.status.update(phase="completed", result=result)
        view = await self.mount()
        self.assertIn("Story complete", self.text_values(view))
        self.assertIn(result["value"], self.wire_values())
        self.assertEqual(self.commands, [])
        self.assertEqual(self.routes, [])
        for changes in ({"phase": "active"},
                        {"result": dict(result, story_id="another-story")},
                        {"result": dict(result, outcome="cancelled")}):
            with self.subTest(changes=changes):
                changed = await self.mount(dict(self.status, **changes))
                self.assertNotIn("Story complete", self.text_values(changed))
                self.assertNotIn(result["value"], self.text_values(changed))

    async def mount_menu(self, *, busy=False, on_return_to_app=None):
        view = menu_view(self.navigate, Mock(),
                         {"busy": busy, "available": True, "message": "Saved native checkpoint."},
                         Mock(), on_return_to_app=on_return_to_app)
        self.page.views[:] = [view]
        self.page.update()
        return view

    async def test_default_story_menu_has_no_app_controls_or_changed_navigation(self):
        view = await self.mount_menu()
        labels = [item.content for item in control_tree(view)
                  if isinstance(item, (ft.Button, ft.TextButton))]
        self.assertEqual(labels, ["Resume", "Quick save", "Quick load", "Story history",
                                  "Reading settings", "Replay story", "Device diagnostics", "Quit"])
        self.assertNotIn("Return to app", self.wire_values())
        await self.click(self.button(view, "Resume"))
        self.assertEqual(self.routes, ["/"])

    async def test_return_control_latches_and_keeps_native_save_confirmation_separate(self):
        request = AsyncMock(return_value=True)
        view = await self.mount_menu(on_return_to_app=request)
        control = self.button(view, "Return to app")
        await self.click(control)
        await self.click(control)
        request.assert_awaited_once()
        self.assertTrue(control.disabled)
        self.assertEqual(self.routes, [])
        self.assertIn("Saved native checkpoint.", self.text_values(view))
        self.assertIn("Return keeps this story in this session. Quick save keeps a saved place.",
                      self.text_values(view))

    async def test_return_busy_rejection_and_failure_do_not_latch_forever(self):
        request = AsyncMock(return_value=False)
        view = await self.mount_menu(busy=True, on_return_to_app=request)
        await self.click(self.button(view, "Return to app"))
        request.assert_not_awaited()
        view = await self.mount_menu(on_return_to_app=request)
        control = self.button(view, "Return to app")
        await self.click(control)
        self.assertFalse(control.disabled)
        request.assert_awaited_once()
        request.side_effect = RuntimeError("Return unavailable")
        with self.assertLogs(level="ERROR"):
            await self.click(control)
        self.assertFalse(control.disabled)
        self.assertIn("Could not return to the app. Try again.", self.wire_values())

    async def test_concurrent_return_events_do_not_duplicate_a_pending_submission(self):
        entered = asyncio.Event()
        finish = asyncio.Event()

        async def submit_return(event):
            entered.set()
            await finish.wait()
            return True

        request = AsyncMock(side_effect=submit_return)
        view = await self.mount_menu(on_return_to_app=request)
        control = self.button(view, "Return to app")
        first = asyncio.create_task(self.click(control))
        try:
            await asyncio.wait_for(entered.wait(), 2)
            await self.click(control)
            request.assert_awaited_once()
        finally:
            finish.set()
            await first
        self.assertTrue(control.disabled)


if __name__ == "__main__":
    unittest.main()
