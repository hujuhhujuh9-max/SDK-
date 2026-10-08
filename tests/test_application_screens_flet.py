"""C's screen interactions through the pinned Flet session and encoded patches."""

import asyncio
import importlib.util
import json
import unittest

from runtime import application_screens as screens, story_ui
from runtime.application_data import DEFAULT_STORAGE_KEY
from runtime.renfletpy import Story
from scripts.flet_protocol import walk

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as ft
    from flet.controls.context import _context_page
    from flet.messaging.session import Session
    from test_form_list_flet import PreferencesConnection


def idle_status(**changes):
    return {"revision": 1, "loading": False, "busy": False, "active": False,
            "resume_available": False, "resume_reason": "No story bookmark is available.",
            "message": "", "error": None, "result": None, **changes}


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class ApplicationScreensFletTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = PreferencesConnection()
        self.session = Session(self.connection)
        self.connection.session = self.session
        self.page = self.session.page
        self.token = _context_page.set(self.page)
        self.connection.encode(self.session.get_page_patch())
        self.status = idle_status()
        self.requests = []
        self.accept = True
        self.request_error = None

        async def changed(event):
            await self.mount(event.route)

        self.page.on_route_change = changed
        await self.navigate(screens.APP_ROUTE)

    async def asyncTearDown(self):
        _context_page.reset(self.token)
        self.session.close()
        await asyncio.sleep(0)

    def read_status(self):
        return dict(self.status)

    def request_story(self, action, revision):
        self.requests.append((action, revision))
        if self.request_error is not None:
            raise self.request_error
        if self.accept:
            self.status["busy"] = True
        return self.accept

    async def navigate(self, route):
        if self.page.route == route:
            await self.mount(route)  # Native status publication explicitly refreshes a view.
            return
        self.page.route = route
        await self.session.dispatch_event(self.page._i, "route_change", {"route": route})

    async def refresh_status(self):
        await self.mount(self.page.route)

    async def mount(self, route):
        options = (self.page, self.navigate, self.read_status, self.request_story)
        if route == screens.APP_ROUTE:
            view = screens.app_home_view(*options, refresh_status=self.refresh_status)
        elif route == screens.STORY_ROUTE:
            view = screens.app_story_view(*options, refresh_status=self.refresh_status)
        elif route in (screens.START_ROUTE, screens.CANCEL_ROUTE):
            view = screens.app_confirmation_view(
                *options, action="start" if route == screens.START_ROUTE else "cancel",
                refresh_status=self.refresh_status)
        elif route == screens.RESULT_ROUTE:
            view = screens.app_result_view(self.navigate, self.status["result"])
        elif route == screens.RECORDS_ROUTE:
            view = await screens.create_app_records_view(self.page, self.navigate)
        else:
            raise AssertionError("Unexpected fixture route: " + route)
        self.page.views[:] = [view]
        self.page.update()

    def encoded(self):
        return self.connection.encode(self.session.get_page_patch())

    def control(self, kind, name, value):
        matches = [item for item in walk(self.encoded()) if isinstance(item, dict)
                   and item.get("_c") == kind and item.get(name) == value]
        self.assertEqual(len(matches), 1, (kind, name, value))
        return self.session.index[matches[0]["_i"]]

    def button(self, label):
        matches = [item for item in walk(self.encoded()) if isinstance(item, dict)
                   and item.get("_c") in ("Button", "TextButton") and item.get("content") == label]
        self.assertEqual(len(matches), 1, label)
        return self.session.index[matches[0]["_i"]]

    async def click(self, label):
        await self.session.dispatch_event(self.button(label)._i, "click", None)

    def assert_patch_contains(self, text):
        self.assertIn(text, list(walk(self.connection.patches)))

    async def test_loading_allows_records_but_blocks_story_commands(self):
        self.status = idle_status(loading=True)
        await self.navigate(screens.APP_ROUTE)
        self.assertIn("Loading story status…", walk(self.encoded()))
        self.assertTrue(self.control("ProgressRing", "_c", "ProgressRing").visible)
        for label in ("Start story", "Resume story"):
            self.assertTrue(self.button(label).disabled)
            await self.click(label)
        self.assertEqual(self.requests, [])
        await self.click("Application records")
        self.assertEqual(self.page.route, screens.RECORDS_ROUTE)
        self.assertIn("Records loaded", walk(self.encoded()))
        await self.click("Return to app")
        self.assertEqual(self.page.route, screens.APP_ROUTE)

    async def test_busy_controls_ignore_even_dispatched_disabled_events(self):
        self.status = idle_status(busy=True, active=True, resume_available=True)
        for route, labels in (
            (screens.APP_ROUTE, ("Start story", "Resume story")),
            (screens.STORY_ROUTE, ("Start from beginning", "Resume story", "Return to app", "Cancel story")),
            (screens.START_ROUTE, ("Start again",)),
            (screens.CANCEL_ROUTE, ("Confirm cancellation",)),
        ):
            with self.subTest(route=route):
                await self.navigate(route)
                for label in labels:
                    self.assertTrue(self.button(label).disabled)
                    await self.click(label)
        self.assertEqual(self.requests, [])

    async def test_unavailable_resume_has_reason_and_start_is_queued_once(self):
        self.status["resume_reason"] = "The saved story is no longer available."
        await self.navigate(screens.APP_ROUTE)
        self.assertIn(self.status["resume_reason"], walk(self.encoded()))
        self.assertTrue(self.button("Resume story").disabled)
        await self.click("Resume story")
        self.assertEqual(self.requests, [])
        await self.click("Start story")
        self.assertEqual(self.requests, [("start", 1)])
        self.assertEqual(self.page.route, screens.APP_ROUTE)
        self.assert_patch_contains("Starting story…")
        self.assertTrue(self.button("Start story").disabled)
        self.status["busy"] = False  # This view remains locked until replaced.
        await self.click("Start story")
        self.assertEqual(self.requests, [("start", 1)])

    async def test_active_start_requires_confirmation_and_keep_submits_nothing(self):
        self.status = idle_status(active=True, resume_available=True)
        await self.navigate(screens.APP_ROUTE)
        await self.click("Start story")
        self.assertEqual(self.page.route, screens.START_ROUTE)
        self.assertEqual(self.requests, [])
        await self.click("Keep current story")
        self.assertEqual(self.page.route, screens.STORY_ROUTE)
        self.assertEqual(self.requests, [])
        await self.click("Start from beginning")
        await self.click("Start again")
        await self.click("Start again")
        self.assertEqual(self.requests, [("start", 1)])
        self.assertEqual(self.page.route, screens.START_ROUTE)

    async def test_resumable_bookmark_requires_confirmation_before_replacing_progress(self):
        self.status = idle_status(resume_available=True)
        await self.navigate(screens.APP_ROUTE)
        await self.click("Start story")
        self.assertEqual(self.page.route, screens.START_ROUTE)
        self.assertEqual(self.requests, [])
        await self.click("Start again")
        self.assertEqual(self.requests, [("start", 1)])

    async def test_cancellation_requires_confirmation_and_waits_for_native_outcome(self):
        self.status = idle_status(active=True, resume_available=True)
        await self.navigate(screens.STORY_ROUTE)
        await self.click("Cancel story")
        self.assertEqual(self.page.route, screens.CANCEL_ROUTE)
        self.assertEqual(self.requests, [])
        await self.click("Confirm cancellation")
        await self.click("Confirm cancellation")
        self.assertEqual(self.requests, [("cancel", 1)])
        self.assertEqual(self.page.route, screens.CANCEL_ROUTE)
        self.assert_patch_contains("Cancelling story…")

    async def test_return_waits_for_native_checkpoint_and_resume_uses_new_revision(self):
        self.status = idle_status(active=True, resume_available=True)
        await self.navigate(screens.STORY_ROUTE)
        await self.click("Return to app")
        self.assertEqual(self.requests, [("return", 1)])
        self.assertEqual(self.page.route, screens.STORY_ROUTE)
        self.assert_patch_contains("Returning to app…")
        self.status = idle_status(revision=2, resume_available=True)
        await self.navigate(screens.APP_ROUTE)  # The native owner acknowledges return.
        await self.click("Resume story")
        self.assertEqual(self.requests, [("return", 1), ("resume", 2)])
        self.assert_patch_contains("Resuming story…")

    async def test_live_busy_and_unavailable_guards_recheck_before_submission(self):
        self.status = idle_status(resume_available=True)
        await self.navigate(screens.APP_ROUTE)
        self.status["busy"] = True
        await self.click("Start story")
        self.status.update(busy=False, resume_available=False)
        await self.click("Resume story")
        self.assertEqual(self.requests, [])

    async def test_stale_home_and_confirmation_events_require_reload(self):
        for route, label in ((screens.APP_ROUTE, "Start story"),
                             (screens.START_ROUTE, "Start again"),
                             (screens.CANCEL_ROUTE, "Confirm cancellation")):
            with self.subTest(route=route):
                self.status = idle_status(active=True, resume_available=True)
                await self.navigate(route)
                self.status["revision"] += 1
                await self.click(label)
                self.assertEqual(self.requests, [])
                self.assert_patch_contains("Story status changed. Reload before continuing.")
                self.assertTrue(self.button(label).disabled)
                await self.click("Reload story status")
                self.assertEqual(self.page.route, route)
                self.assertFalse(self.button(label).disabled)

    async def test_rejected_and_failed_requests_are_visible_and_reloadable(self):
        for error, expected in ((None, "Story request was not accepted. Reload before continuing."),
                                (OSError("native queue unavailable"), "Story request failed. Reload before trying again.")):
            with self.subTest(error=error):
                self.requests.clear()
                self.status = idle_status()
                self.accept = False
                self.request_error = error
                await self.navigate(screens.APP_ROUTE)
                if error is None:
                    await self.click("Start story")
                else:
                    with self.assertLogs(level="ERROR"):
                        await self.click("Start story")
                self.assert_patch_contains(expected)
                self.assertTrue(self.button("Start story").disabled)
                await self.click("Start story")
                self.assertEqual(len(self.requests), 1)
                self.assertFalse(self.button("Reload story status").disabled)
                await self.click("Reload story status")
                self.accept = True
                self.request_error = None
                await self.click("Start story")
                self.assertEqual(self.requests, [("start", 1), ("start", 1)])

    async def test_published_failure_is_visible_and_can_be_retried(self):
        self.status = idle_status(error="The story could not be started. Try again.")
        await self.navigate(screens.APP_ROUTE)
        self.assertIn(self.status["error"], walk(self.encoded()))
        self.assertFalse(self.button("Start story").disabled)
        self.assertTrue(self.button("Reload story status").visible)
        await self.click("Start story")
        self.assertEqual(self.requests, [("start", 1)])

    async def test_refresh_failure_keeps_reload_available_for_recovery(self):
        def refresh_status():
            raise OSError("status unavailable")

        self.status = idle_status(error="Could not read story status.")
        self.page.views[:] = [screens.app_home_view(
            self.page, self.navigate, self.read_status, self.request_story, refresh_status=refresh_status)]
        self.page.update()
        with self.assertLogs(level="ERROR"):
            await self.click("Reload story status")
        self.assert_patch_contains("Story status could not be loaded. Try Reload again.")
        self.assertFalse(self.button("Reload story status").disabled)
        self.assertTrue(self.button("Start story").disabled)
        self.assertEqual(self.requests, [])

    async def test_refresh_blocks_duplicate_events_and_story_requests_while_awaiting(self):
        entered, release = asyncio.Event(), asyncio.Event()
        refresh_calls = []

        async def refresh_status():
            refresh_calls.append(True)
            entered.set()
            await release.wait()
            await self.mount(self.page.route)

        self.status = idle_status(error="Could not read story status.")
        self.page.views[:] = [screens.app_home_view(
            self.page, self.navigate, self.read_status, self.request_story, refresh_status=refresh_status)]
        self.page.update()
        reload = self.button("Reload story status")
        refreshing = asyncio.create_task(self.session.dispatch_event(reload._i, "click", None))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            self.assertTrue(reload.disabled)
            await self.session.dispatch_event(reload._i, "click", None)
            await self.click("Start story")
            self.assertEqual(refresh_calls, [True])
            self.assertEqual(self.requests, [])
        finally:
            release.set()
            await asyncio.wait_for(refreshing, 3)
        self.assertFalse(self.button("Start story").disabled)

    async def test_result_states_are_read_only_and_return_to_app(self):
        for result_status, heading in (("completed", "Story completed"),
                                       ("cancelled", "Story cancelled"), ("failed", "Story failed")):
            with self.subTest(status=result_status):
                self.status["result"] = {"status": result_status, "story_title": "Before the First Light",
                                         "summary": "A morning to remember.",
                                         "values": {"Memory": "星図", "Score": 0, "Skipped": False}}
                await self.navigate(screens.APP_ROUTE)
                await self.click("View story result")
                encoded = self.encoded()
                for text in (heading, "A morning to remember.", "Memory: 星図", "Score: 0", "Skipped: False"):
                    self.assertIn(text, walk(encoded))
                await self.click("Return to app")
                self.assertEqual(self.page.route, screens.APP_ROUTE)
        self.status["result"] = None
        await self.navigate(screens.RESULT_ROUTE)
        self.assertIn("No story result yet.", walk(self.encoded()))
        self.assertEqual(self.requests, [])
        self.assertEqual(self.connection.calls, [])

    async def test_records_reentry_keeps_data_and_page_ownership_through_story_results(self):
        callbacks = {name: getattr(self.page, name) for name in (
            "on_route_change", "on_view_pop", "on_connect", "on_disconnect", "on_close")}
        views = list(self.page.views)
        draft_view = await screens.create_app_records_view(self.page, self.navigate)
        self.assertEqual(self.page.views, views)
        self.assertEqual(self.page.route, screens.APP_ROUTE)
        for name, callback in callbacks.items():
            self.assertIs(getattr(self.page, name), callback)
        self.assertEqual(draft_view.route, screens.RECORDS_ROUTE)
        await self.click("Application records")
        title = self.control("TextField", "label", "Title")
        self.session.apply_patch(title._i, {"value": "Current application record"})
        await self.click("Add record")
        persisted = self.connection.values[DEFAULT_STORAGE_KEY]
        preference_service = self.page._runner_application_data["preferences"]
        await self.click("Return to app")
        self.status = idle_status(revision=2, resume_available=True, result={
            "status": "completed", "summary": "Older story loaded and completed.", "values": {}})
        await self.navigate(screens.RESULT_ROUTE)
        await self.click("Application records")
        self.assertIn("Title: Current application record", walk(self.encoded()))
        self.assertEqual(self.connection.values[DEFAULT_STORAGE_KEY], persisted)
        self.assertIs(self.page._runner_application_data["preferences"], preference_service)
        self.assertEqual(sum(call.name == "set" for call in self.connection.calls), 1)
        self.assertEqual(len(json.loads(persisted)["records"]), 1)
        self.assertEqual(self.requests, [])

    async def test_optional_story_menu_and_interlude_return_controls_use_flet_events(self):
        story = Story()
        revision = story.show("Mira", "Keep the current scene.")
        returned = []

        async def return_async(event):
            returned.append(event.control.content)

        def return_sync(event):
            returned.append(event.control.content)

        for handler in (return_sync, return_async):
            for busy in (False, True):
                with self.subTest(handler=handler.__name__, busy=busy):
                    status = {"busy": busy, "available": True, "message": "Saved."}
                    view = story_ui.menu_view(self.navigate, lambda event: None, status,
                                               lambda action: None, on_return_to_app=handler)
                    self.page.views[:] = [view]
                    self.page.update()
                    before = len(returned)
                    self.assertEqual(self.button("Return to app").disabled, busy)
                    await self.click("Return to app")
                    self.assertEqual(len(returned), before + (not busy))
                    self.page.views[:] = [ft.View(route="/", controls=story_ui.dialogue_controls(
                        self.navigate, story.current(), on_return_to_app=handler, return_to_app_busy=busy))]
                    self.page.update()
                    before = len(returned)
                    await self.click("Return to app")
                    self.assertEqual(len(returned), before + (not busy))
                    self.assertEqual(story.current().revision, revision)
                    self.assertIsNone(story.consume(revision))
        default_menu = story_ui.menu_view(self.navigate, lambda event: None,
                                          {"busy": False, "available": True, "message": ""}, lambda action: None)
        self.page.views[:] = [default_menu, ft.View(route="/", controls=story_ui.dialogue_controls(self.navigate, story.current()))]
        self.page.update()
        self.assertNotIn("Return to app", walk(self.encoded()))

    async def test_interlude_busy_state_blocks_choices_during_native_return(self):
        story_ui.story.reset()
        try:
            revision = story_ui.story.minigame("star_map")
            self.page.views[:] = [ft.View(route="/", controls=story_ui.dialogue_controls(
                self.navigate, story_ui.story.current(), on_return_to_app=lambda event: None,
                return_to_app_busy=True))]
            self.page.update()
            for label in ("Deneb", "Vega", "Altair", "Skip minigame"):
                self.assertTrue(self.button(label).disabled)
                await self.click(label)
            self.assertEqual(story_ui.story.current().progress, ())
            self.assertIsNone(story_ui.story.consume(revision))
            self.page.views[:] = [ft.View(route="/", controls=story_ui.dialogue_controls(
                self.navigate, story_ui.story.current(), on_return_to_app=lambda event: None))]
            self.page.update()
            await self.click("Deneb")
            self.assertEqual(story_ui.story.current().progress, ("deneb",))
        finally:
            story_ui.story.reset()


if __name__ == "__main__":
    unittest.main()
