"""Verify the new screen with the prepared Flet controls and service protocol."""

import asyncio
import gc
import importlib.util
import json
import unittest

from runtime.application_data import DEFAULT_STORAGE_KEY
from runtime.form_list import create_form_list_view
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


class PreferencesConnection(Connection):
    """Emulate native preference replies through Flet's actual method bridge."""

    def __init__(self):
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.pubsubhub = PubSubHub(loop=self.loop)
        self.values = {}
        self.calls = []
        self.session = None

    def send_message(self, message):
        # Native transports encode every packet; this also records Flet's
        # structural snapshots used by subsequent incremental patches.
        self.encode([message.action, message.body])
        if message.action != MessageAction.INVOKE_METHOD:
            return
        request = message.body
        self.calls.append(request)
        if request.name == "get":
            result = self.values.get(request.args["key"])
        elif request.name == "set":
            self.values[request.args["key"]] = request.args["value"]
            result = True
        else:
            raise AssertionError("Unexpected native method: " + request.name)
        self.loop.call_soon(self.session.handle_invoke_method_results,
                           request.control_id, request.call_id, result, None)

    def encode(self, value):
        return msgpack.unpackb(msgpack.packb(
            value, default=configure_encode_object_for_msgpack(BaseControl)),
            strict_map_key=False)


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class FormListFletTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = PreferencesConnection()
        self.session = Session(self.connection)
        self.connection.session = self.session
        self.page = self.session.page
        self.token = _context_page.set(self.page)
        self.connection.encode(self.session.get_page_patch())

    async def asyncTearDown(self):
        _context_page.reset(self.token)
        self.session.close()
        await asyncio.sleep(0)

    async def mount(self):
        view = await create_form_list_view(self.page)
        self.assertIsInstance(view, ft.View)
        self.page.views.append(view)
        self.page.update()
        return view

    async def test_real_controls_and_native_method_bridge_support_full_workflow(self):
        view = await self.mount()
        fields = view.controls[0].controls
        title, details = fields[1:3]
        save, cancel, reload = fields[3].controls
        status, record_list = fields[4:]
        self.assertIsInstance(title, ft.TextField)
        self.assertTrue(details.multiline)
        title.value = "Native record"
        details.value = "Persisted through Flet"
        await save._trigger_event("click", None)
        self.assertEqual(status.value, "Record saved")
        edit, delete = record_list.controls[0].content.controls[-1].controls
        await edit._trigger_event("click", None)
        title.value = "Edited record"
        await save._trigger_event("click", None)
        saved = json.loads(self.connection.values[DEFAULT_STORAGE_KEY])["records"]
        self.assertEqual(saved[0]["values"]["title"], "Edited record")
        controls = [item.get("_c") for item in walk(
            self.connection.encode(self.session.get_page_patch()))
                    if isinstance(item, dict)]
        self.assertIn("TextField", controls)
        self.assertIn("Button", controls)
        edit, delete = record_list.controls[0].content.controls[-1].controls
        await delete._trigger_event("click", None)
        self.assertEqual(json.loads(self.connection.values[DEFAULT_STORAGE_KEY])["records"], [])
        self.assertEqual([call.name for call in self.connection.calls],
                         ["get", "get", "set", "get", "set", "get", "set"])
        service = self.page._runner_application_data["preferences"]
        self.assertTrue(all(call.control_id == service._i for call in self.connection.calls))

    async def test_reopening_view_retains_one_registered_service_and_saved_records(self):
        view = await self.mount()
        fields = view.controls[0].controls
        fields[1].value = "Kept across views"
        await fields[3].controls[0]._trigger_event("click", None)
        service = self.page._runner_application_data["preferences"]
        service_id = service._i
        self.page.views.pop()
        self.page.update()
        gc.collect()
        await self.session.after_event(None)
        reopened = await self.mount()
        records = reopened.controls[0].controls[-1]
        self.assertEqual(records.controls[0].content.controls[0].value,
                         "Title: Kept across views")
        self.assertEqual([item._i for item in self.page._services._services], [service_id])
        self.assertIs(self.session.index.get(service_id), service)


if __name__ == "__main__":
    unittest.main()
