"""Application routes, inputs and story controls over the real Flet socket."""

import asyncio
import importlib.util
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runtime import application_screens as screens
from runtime.application_data import DEFAULT_STORAGE_KEY
from scripts.flet_protocol import walk
from test_application_screens_flet import idle_status

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    from flet.controls.context import _context_page
    from flet.messaging.flet_socket_server import FletSocketServer
    from test_form_list_protocol import PreferenceClient
else:
    PreferenceClient = object


class ScreenClient(PreferenceClient):
    """Emulate native navigation and preferences replies; events travel on the wire."""

    async def until(self, predicate):
        for _ in range(100):
            message = await self.receive()
            if message[0] == 5:
                request = message[1]
                self.calls.append(request)
                if request["name"] == "get":
                    await self.reply(request, self.values.get(request["args"]["key"]))
                elif request["name"] == "set":
                    self.values[request["args"]["key"]] = request["args"]["value"]
                    await self.reply(request, True)
                elif request["name"] == "push_route":
                    route = request["args"]["route"]
                    await self.reply(request, None)
                    await self.send(4, {"id": self.page_id, "props": {"route": route}})
                    await self.send(3, {"target": self.page_id, "name": "route_change", "data": {"route": route}})
                else:
                    raise AssertionError("Unexpected native method: " + request["name"])
            if predicate(message):
                return message
        raise AssertionError("Expected application message was not received")


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class ApplicationScreensProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="application-screens-protocol-")
        self.socket_path = str(Path(self.folder.name) / "flet.sock")
        self.values = {"runner.capability": "working"}
        self.status = idle_status()
        self.requests = []
        self.accept = True
        self.clients = []
        self.server = None
        self.session = None
        await self.start_server()

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        if self.server is not None:
            await self.server.close()
        await asyncio.sleep(0)
        self.folder.cleanup()

    def read_status(self):
        return dict(self.status)

    def request_story(self, action, revision):
        self.requests.append((action, revision))
        if self.accept:
            self.status["busy"] = True
        return self.accept

    async def start_server(self):
        async def mount(session):
            self.session = session
            page = session.page

            async def refresh_status():
                await render(page.route)

            async def render(route):
                options = (page, page.push_route, self.read_status, self.request_story)
                if route == screens.APP_ROUTE:
                    view = screens.app_home_view(*options, refresh_status=refresh_status)
                elif route == screens.RECORDS_ROUTE:
                    view = await screens.create_app_records_view(page, page.push_route)
                elif route == screens.STORY_ROUTE:
                    view = screens.app_story_view(*options, refresh_status=refresh_status)
                elif route in (screens.START_ROUTE, screens.CANCEL_ROUTE):
                    view = screens.app_confirmation_view(
                        *options, action="start" if route == screens.START_ROUTE else "cancel",
                        refresh_status=refresh_status)
                elif route == screens.RESULT_ROUTE:
                    view = screens.app_result_view(page.push_route, self.status["result"])
                else:
                    raise AssertionError("Unexpected fixture route: " + route)
                # Explicit unmount/mount makes each wire snapshot independently
                # inspectable; services stay owned by the same page.
                page.views.clear()
                page.update()
                page.views.append(view)
                page.update()

            async def route_changed(event):
                await render(event.route)

            page.on_route_change = route_changed
            token = _context_page.set(page)
            try:
                self.render = render
                await render(page.route)
            finally:
                _context_page.reset(token)

        self.server = FletSocketServer(loop=asyncio.get_running_loop(), uds_path=self.socket_path,
                                       on_session_created=mount, executor=ThreadPoolExecutor(max_workers=1))
        await self.server.start()

    async def connect(self, route=screens.APP_ROUTE):
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        client = ScreenClient(reader, writer, self.values)
        self.clients.append(client)
        await client.send(1, {"session_id": "", "page_name": "", "page": {
            "platform": "android", "width": 411.0, "height": 731.0, "route": route}})
        registered = await client.receive()
        self.assertEqual(registered[0], 1)
        self.assertFalse(registered[1].get("error"))
        client.page_id = registered[1]["page_patch"]["_i"]
        return client

    def control(self, message, kind, name, value):
        matches = [item for item in walk(message) if isinstance(item, dict)
                   and item.get("_c") == kind and item.get(name) == value]
        self.assertEqual(len(matches), 1, (kind, name, value))
        return matches[0]

    async def click_until(self, client, message, label, expected, kind="Button"):
        await client.click(self.control(message, kind, "content", label)["_i"])
        return await client.until(lambda item: item[0] == 2 and expected in walk(item))

    async def publish(self, route, **changes):
        self.status.update(changes)
        self.status["revision"] += 1
        previous_route = self.session.page.route
        self.session.page.route = route
        token = _context_page.set(self.session.page)
        try:
            if previous_route == route:
                await self.render(route)
            else:
                await self.session.dispatch_event(self.session.page._i, "route_change", {"route": route})
        finally:
            _context_page.reset(token)

    async def test_wire_records_start_return_resume_and_completion_preserve_app_data(self):
        client = await self.connect()
        home = await client.until(lambda message: "Application" in walk(message))
        records = await self.click_until(client, home, "Application records", "Records loaded")
        title = self.control(records, "TextField", "label", "Title")
        await client.type(title["_i"], "星図 from the app")
        await client.click(self.control(records, "Button", "content", "Add record")["_i"])
        await client.until(lambda message: "Record saved" in walk(message))
        persisted = self.values[DEFAULT_STORAGE_KEY]
        home = await self.click_until(client, records, "Return to app", "Application", kind="TextButton")
        await client.click(self.control(home, "Button", "content", "Start story")["_i"])
        await client.until(lambda message: "Starting story…" in walk(message))
        self.assertEqual(self.requests, [("start", 1)])
        self.assertEqual(self.session.page.route, screens.APP_ROUTE)
        await self.publish(screens.STORY_ROUTE, active=True, resume_available=True, busy=False)
        controls = await client.until(lambda message: "Story controls" in walk(message))
        await client.click(self.control(controls, "Button", "content", "Return to app")["_i"])
        await client.until(lambda message: "Returning to app…" in walk(message))
        self.assertEqual(self.requests[-1], ("return", 2))
        self.assertEqual(self.session.page.route, screens.STORY_ROUTE)
        await self.publish(screens.APP_ROUTE, active=False, busy=False)
        home = await client.until(lambda message: "Application" in walk(message))
        await client.click(self.control(home, "Button", "content", "Resume story")["_i"])
        await client.until(lambda message: "Resuming story…" in walk(message))
        self.assertEqual(self.requests[-1], ("resume", 3))
        result = {"status": "completed", "story_title": "Before the First Light",
                  "summary": "The morning is yours.", "values": {"Memory": "Stars", "Score": 0}}
        await self.publish(screens.RESULT_ROUTE, active=False, busy=False, resume_available=False, result=result)
        completed = await client.until(lambda message: "Story completed" in walk(message))
        self.assertIn("Memory: Stars", walk(completed))
        self.assertIn("Score: 0", walk(completed))
        home = await self.click_until(client, completed, "Return to app", "Application")
        records = await self.click_until(client, home, "Application records", "Records loaded")
        self.assertIn("Title: 星図 from the app", walk(records))
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], persisted)
        self.assertEqual(sum(call["name"] == "set" for call in client.calls), 1)
        self.assertEqual(self.values["runner.capability"], "working")
        self.assertEqual(len(json.loads(persisted)["records"]), 1)

    async def test_wire_confirmation_keep_and_cancel_queue_once(self):
        self.status = idle_status(active=True, resume_available=True)
        client = await self.connect()
        home = await client.until(lambda message: "Application" in walk(message))
        confirmation = await self.click_until(client, home, "Start story", "Start this story again?")
        self.assertEqual(self.requests, [])
        controls = await self.click_until(client, confirmation, "Keep current story", "Story controls", kind="TextButton")
        self.assertEqual(self.requests, [])
        confirmation = await self.click_until(client, controls, "Cancel story", "Cancel this story?")
        confirm_id = self.control(confirmation, "Button", "content", "Confirm cancellation")["_i"]
        await client.click(confirm_id)
        busy = await client.until(lambda message: "Cancelling story…" in walk(message))
        self.assertTrue(any(isinstance(item, list) and item[-2:] == ["disabled", True]
                            for item in walk(busy)))
        await client.click(confirm_id)
        await self.publish(screens.RESULT_ROUTE, busy=False, active=False, result={
            "status": "cancelled", "summary": "Your app records are kept."})
        await client.until(lambda message: "Story cancelled" in walk(message))
        self.assertEqual(self.requests, [("cancel", 1)])
        self.assertNotIn(DEFAULT_STORAGE_KEY, self.values)

    async def test_wire_rejection_reload_same_route_and_retry(self):
        self.accept = False
        client = await self.connect()
        home = await client.until(lambda message: "Application" in walk(message))
        await client.click(self.control(home, "Button", "content", "Start story")["_i"])
        await client.until(lambda message: "Story request was not accepted. Reload before continuing." in walk(message))
        # Reload uses a refresh callback: Flet drops a second route_change to
        # the same route, so push_route alone cannot provide this recovery.
        reload_id = self.control(home, "TextButton", "content", "Reload story status")["_i"]
        await client.click(reload_id)
        refreshed = await client.until(lambda message: "Application" in walk(message))
        self.accept = True
        await client.click(self.control(refreshed, "Button", "content", "Start story")["_i"])
        await client.until(lambda message: "Starting story…" in walk(message))
        self.assertEqual(self.requests, [("start", 1), ("start", 1)])
        self.assertEqual(self.session.page.route, screens.APP_ROUTE)

    async def test_wire_stale_event_displays_failure_without_submitting(self):
        self.status = idle_status(resume_available=True)
        client = await self.connect()
        home = await client.until(lambda message: "Application" in walk(message))
        self.status["revision"] += 1
        await client.click(self.control(home, "Button", "content", "Resume story")["_i"])
        await client.until(lambda message: "Story status changed. Reload before continuing." in walk(message))
        self.assertEqual(self.requests, [])
        self.assertEqual(self.session.page.route, screens.APP_ROUTE)


if __name__ == "__main__":
    unittest.main()
