"""Pinned Flet protocol fixture running beside the real native story thread."""

import asyncio
import threading
from types import SimpleNamespace

import msgpack
from flet.controls.base_control import BaseControl
from flet.controls.context import _context_page
from flet.messaging.connection import Connection
from flet.messaging.protocol import MessageAction, configure_encode_object_for_msgpack
from flet.messaging.session import Session
from flet.pubsub.pubsub_hub import PubSubHub

import sdk_bridge


class PreferencesConnection(Connection):
    # Service replies are simulated; control/event encoding uses pinned Flet.
    def __init__(self):
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.page_url = "flet://native-app-check"
        self.pubsubhub = PubSubHub(loop=self.loop)
        self.values = {}
        self.session = None
        self.patches = 0

    def encode(self, value):
        return msgpack.unpackb(msgpack.packb(value, default=configure_encode_object_for_msgpack(BaseControl)),
                               strict_map_key=False)

    def send_message(self, message):
        self.encode([message.action, message.body])
        if message.action == MessageAction.PATCH_CONTROL:
            self.patches += 1
        if message.action == MessageAction.INVOKE_METHOD:
            request = message.body
            if request.name == "get":
                result = self.values.get(request.args["key"])
            elif request.name == "set":
                self.values[request.args["key"]] = request.args["value"]
                result = True
            else:
                raise AssertionError("Unexpected service operation: " + request.name)
            self.loop.call_soon(self.session.handle_invoke_method_results,
                               request.control_id, request.call_id, result, None)


class AppUI:
    def __init__(self, route="/app"):
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, name="native-app-check-flet", daemon=True)
        self.thread.start()
        self.call(self.open(route))

    def call(self, operation):
        return asyncio.run_coroutine_threadsafe(operation, self.loop).result(timeout=5)

    async def open(self, route):
        self.connection = PreferencesConnection()
        self.session = Session(self.connection)
        self.connection.session = self.session
        self.page = self.session.page
        _context_page.set(self.page)
        self.connection.encode(self.session.get_page_patch())
        self.page.route = route
        self.page.push_route = self.navigate
        await sdk_bridge._page(self.page)

    async def drain(self):
        _context_page.set(self.page)
        for _ in range(5):
            await asyncio.sleep(0)

    async def navigate(self, route):
        _context_page.set(self.page)
        self.page.route = route
        await self.page.on_route_change(SimpleNamespace(route=route))

    async def click(self, label):
        await self.drain()

        def walk(controls):
            for control in controls:
                if getattr(control, "content", None) == label:
                    return control
                found = walk(getattr(control, "controls", []))
                if found is not None:
                    return found

        button = walk(self.page.views[-1].controls)
        assert button is not None and not button.disabled, (label, self.page.route)
        await self.session.dispatch_event(button._i, "click", None)
        await self.drain()

    async def snapshot(self):
        await self.drain()
        return {"route": self.page.route, "patches": self.connection.patches,
                "services": [service._i for service in self.page._services._services]}

    async def records_draft(self, text=None):
        await self.drain()
        field = self.page.views[-1].controls[0].controls[1]
        if text is not None:
            self.session.apply_patch(field._i, {"value": text})
        return field.value

    def close(self):
        async def shutdown():
            await self.drain()
            await self.page.on_close(None)
            self.session.close()
        self.call(shutdown())
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)
        assert not self.thread.is_alive()
        self.loop.close()
