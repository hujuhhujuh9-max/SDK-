"""Verify the new screen with the prepared Flet controls and service protocol."""

import asyncio
import gc
import importlib.util
import json
import unittest

from runtime.application_data import DEFAULT_STORAGE_KEY
from runtime.form_list import FormField, create_form_list_view
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

    def __init__(self, values=None):
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.pubsubhub = PubSubHub(loop=self.loop)
        self.values = {} if values is None else values
        self.calls = []
        self.patches = []
        self.session = None
        self.defer_write_replies = False
        self.deferred_replies = []
        self.write_requested = asyncio.Event()

    def send_message(self, message):
        # Native transports encode every packet; this also records Flet's
        # structural snapshots used by subsequent incremental patches.
        encoded = self.encode([message.action, message.body])
        if message.action == MessageAction.PATCH_CONTROL:
            self.patches.append(encoded[1]["patch"])
        if message.action != MessageAction.INVOKE_METHOD:
            return
        request = message.body
        self.calls.append(request)
        if request.name == "get":
            result = self.values.get(request.args["key"])
        elif request.name == "set":
            self.values[request.args["key"]] = request.args["value"]
            result = True
            self.write_requested.set()
            if self.defer_write_replies:
                self.deferred_replies.append((request, result))
                return
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

    async def mount(self, **options):
        view = await create_form_list_view(self.page, **options)
        self.assertIsInstance(view, ft.View)
        self.page.views.append(view)
        self.page.update()
        return view

    async def test_validation_errors_reach_flutter_and_clear_after_valid_save(self):
        view = await self.mount(fields=(FormField("title", "Title", required=True,
                                                 max_length=4),))
        controls = view.controls[0].controls
        title = controls[1]
        save = controls[2].controls[0]

        async def submit(value):
            self.connection.patches.clear()
            self.session.apply_patch(title._i, {"value": value})
            await self.session.dispatch_event(save._i, "click", None)
            return [operation for patch in self.connection.patches for operation in patch
                    if len(operation) >= 4 and operation[-2] == "error"]

        required = await submit("")
        self.assertEqual(title.error, "Title is required")
        self.assertTrue(any(item[-1] == "Title is required" for item in required), required)
        too_long = await submit("Too long")
        self.assertTrue(any(item[-1] == "Use at most 4 characters" for item in too_long), too_long)
        self.assertEqual([call.name for call in self.connection.calls], ["get"])
        cleared = await submit("Mira")
        self.assertIsNone(title.error)
        self.assertTrue(any(item[-1] is None for item in cleared), cleared)
        self.assertEqual(json.loads(self.connection.values[DEFAULT_STORAGE_KEY])["records"][0]
                         ["values"]["title"], "Mira")

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

    async def test_cancelled_native_save_requires_reload_before_resubmission(self):
        view = await self.mount()
        fields = view.controls[0].controls
        title = fields[1]
        save, cancel, reload = fields[3].controls
        status, records = fields[4:]
        title.value = "Committed before cancellation"
        self.connection.defer_write_replies = True
        task = asyncio.create_task(self.session.dispatch_event(save._i, "click", None))
        try:
            await asyncio.wait_for(self.connection.write_requested.wait(), 3)
        finally:
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
        self.assertTrue(save.disabled)
        self.assertFalse(reload.disabled)
        self.assertIn("Reload", status.value)
        self.assertEqual(title.value, "Committed before cancellation")
        await self.session.dispatch_event(save._i, "click", None)
        self.assertEqual(sum(call.name == "set" for call in self.connection.calls), 1)
        self.connection.defer_write_replies = False
        for request, result in self.connection.deferred_replies:
            self.session.handle_invoke_method_results(request.control_id, request.call_id, result, None)
        await self.session.dispatch_event(reload._i, "click", None)
        self.assertFalse(save.disabled)
        self.assertEqual(len(json.loads(self.connection.values[DEFAULT_STORAGE_KEY])["records"]), 1)
        self.assertEqual(records.controls[0].content.controls[0].value,
                         "Title: Committed before cancellation")

    async def test_fresh_session_restores_native_preferences_without_rewriting(self):
        view = await self.mount()
        fields = view.controls[0].controls
        self.session.apply_patch(fields[1]._i, {"value": "Persisted across sessions"})
        await self.session.dispatch_event(fields[3].controls[0]._i, "click", None)
        saved = self.connection.values[DEFAULT_STORAGE_KEY]
        self.session.close()
        connection = PreferencesConnection(self.connection.values)
        session = Session(connection)
        connection.session = session
        token = _context_page.set(session.page)
        try:
            connection.encode(session.get_page_patch())
            restored = await create_form_list_view(session.page)
            records = restored.controls[0].controls[-1]
            self.assertEqual(records.controls[0].content.controls[0].value,
                             "Title: Persisted across sessions")
            self.assertEqual(connection.values[DEFAULT_STORAGE_KEY], saved)
            self.assertEqual([call.name for call in connection.calls], ["get"])
            self.assertIsNot(session.page._runner_application_data["preferences"],
                             self.page._runner_application_data["preferences"])
        finally:
            _context_page.reset(token)
            session.close()
            await asyncio.sleep(0)


if __name__ == "__main__":
    unittest.main()
