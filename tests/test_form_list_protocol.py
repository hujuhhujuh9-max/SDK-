"""Drive the optional screen over the runner's actual Flet socket transport."""

import asyncio
import importlib.util
import json
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from runtime.application_data import DEFAULT_STORAGE_KEY, get_application_data_store
from runtime.form_list import create_form_list_view
from scripts.flet_protocol import walk

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import msgpack
    from flet.controls.context import _context_page
    from flet.messaging.flet_socket_server import FletSocketServer
    from flet.messaging.protocol import decode_ext_from_msgpack


class PreferenceClient:
    """A wire client emulating the native preferences service, including lost replies."""

    def __init__(self, reader, writer, values):
        self.reader = reader
        self.writer = writer
        self.values = values
        self.calls = []
        self.drop_replies = set()
        self.write_error = None

    async def send(self, action, body):
        packet = b"\x00" + msgpack.packb([action, body])
        self.writer.write(len(packet).to_bytes(4, "little") + packet)
        await self.writer.drain()

    async def receive(self):
        async with asyncio.timeout(3):
            size = int.from_bytes(await self.reader.readexactly(4), "little")
            if not 0 < size <= 1024 * 1024:
                raise AssertionError("Invalid Flet packet size")
            packet = await self.reader.readexactly(size)
        if packet[0] != 0:
            raise AssertionError("Unexpected Flet data-channel packet")
        message = msgpack.unpackb(packet[1:], strict_map_key=False,
                                  ext_hook=decode_ext_from_msgpack)
        if message[0] == 6:
            raise AssertionError("Flet session crashed: " + str(message[1]))
        return message

    async def reply(self, request, result, error=None):
        await self.send(5, {"control_id": request["control_id"],
                            "call_id": request["call_id"], "result": result, "error": error})

    async def until(self, predicate):
        for _ in range(100):
            message = await self.receive()
            if message[0] == 5:
                request = message[1]
                self.calls.append(request)
                if request["name"] == "get":
                    result = self.values.get(request["args"]["key"])
                    error = None
                elif request["name"] == "set":
                    self.values[request["args"]["key"]] = request["args"]["value"]
                    result = True
                    error = self.write_error
                else:
                    raise AssertionError("Unexpected native method: " + request["name"])
                if request["name"] not in self.drop_replies:
                    await self.reply(request, result, error)
            if predicate(message):
                return message
        raise AssertionError("Expected Flet message was not received")

    async def click(self, control_id):
        await self.send(3, {"target": control_id, "name": "click", "data": None})

    async def type(self, control_id, value):
        await self.send(4, {"id": control_id, "props": {"value": value}})

    async def close(self):
        self.writer.close()
        await self.writer.wait_closed()


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class FormListProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="form-list-protocol-")
        self.socket_path = str(Path(self.folder.name) / "flet.sock")
        self.native_values = {"runner.capability": "working"}
        self.clients = []
        self.server = None
        await self.start_server()

    async def asyncTearDown(self):
        for client in self.clients:
            await client.close()
        if self.server is not None:
            await self.server.close()
        await asyncio.sleep(0)
        self.folder.cleanup()

    async def start_server(self):
        async def mount(session):
            token = _context_page.set(session.page)
            try:
                store = get_application_data_store(session.page)
                store.timeout = 0.1
                view = await create_form_list_view(session.page, route=session.page.route)
                session.page.views.append(view)
                session.page.update()
            finally:
                _context_page.reset(token)

        self.server = FletSocketServer(loop=asyncio.get_running_loop(),
                                       uds_path=self.socket_path, on_session_created=mount,
                                       executor=ThreadPoolExecutor(max_workers=1))
        await self.server.start()

    async def connect(self):
        reader, writer = await asyncio.open_unix_connection(self.socket_path)
        client = PreferenceClient(reader, writer, self.native_values)
        self.clients.append(client)
        await client.send(1, {"session_id": "", "page_name": "", "page": {
            "platform": "android", "width": 411.0, "height": 731.0,
            "route": "/records?source=wire"}})
        registered = await client.receive()
        self.assertEqual(registered[0], 1)
        self.assertFalse(registered[1].get("error"))
        return client

    def control(self, message, kind, property_name, value):
        matches = [item for item in walk(message) if isinstance(item, dict)
                   and item.get("_c") == kind and item.get(property_name) == value]
        self.assertEqual(len(matches), 1, (kind, property_name, value))
        return matches[0]

    async def ready(self, client):
        return await client.until(lambda message: "Records loaded" in walk(message))

    async def test_expanded_children_use_flex_layout_in_the_native_protocol(self):
        client = await self.connect()
        mounted = await self.ready(client)
        expanded = []
        for parent in walk(mounted):
            if not isinstance(parent, dict) or parent.get("_c") not in ("Row", "Column", "View"):
                continue
            for child in parent.get("controls", []):
                if isinstance(child, dict) and child.get("expand"):
                    expanded.append(child)
                    # Flet wraps these children in Flutter Expanded. Wrap uses
                    # different parent data and produces a gray ErrorWidget in release.
                    self.assertFalse(parent.get("wrap", False), parent)
        self.assertTrue(expanded, "The native protocol must exercise an expanded child")

    async def test_wire_input_create_edit_delete_and_validation(self):
        client = await self.connect()
        mounted = await self.ready(client)
        self.assertIn("/records?source=wire", walk(mounted))
        title_id = self.control(mounted, "TextField", "label", "Title")["_i"]
        details_id = self.control(mounted, "TextField", "label", "Details")["_i"]
        save_id = self.control(mounted, "Button", "content", "Add record")["_i"]
        await client.click(save_id)
        invalid = await client.until(lambda message: "Check the highlighted fields" in walk(message))
        self.assertIn("Title is required", walk(invalid))
        self.assertEqual([call["name"] for call in client.calls], ["get"])
        await client.type(title_id, "  星図  ")
        await client.type(details_id, "First\nSecond")
        await client.click(save_id)
        saved = await client.until(lambda message: "Record saved" in walk(message))
        records = json.loads(self.native_values[DEFAULT_STORAGE_KEY])["records"]
        record_id = records[0]["id"]
        self.assertEqual(records[0]["values"], {"title": "星図", "details": "First\nSecond"})
        edit_id = self.control(saved, "TextButton", "content", "Edit")["_i"]
        await client.click(edit_id)
        await client.until(lambda message: "Editing record" in walk(message))
        await client.type(title_id, "Updated")
        await client.click(save_id)
        edited = await client.until(lambda message: "Record saved" in walk(message))
        self.assertIn("Title: Updated", walk(edited))
        self.assertEqual(json.loads(self.native_values[DEFAULT_STORAGE_KEY])["records"][0]["id"],
                         record_id)
        delete_id = self.control(edited, "TextButton", "content", "Delete")["_i"]
        await client.click(delete_id)
        await client.until(lambda message: "Record deleted" in walk(message))
        self.assertEqual(json.loads(self.native_values[DEFAULT_STORAGE_KEY])["records"], [])
        self.assertEqual(self.native_values["runner.capability"], "working")
        self.assertEqual(len({call["control_id"] for call in client.calls}), 1)

    async def test_backend_restart_restores_data_from_native_client(self):
        client = await self.connect()
        mounted = await self.ready(client)
        title_id = self.control(mounted, "TextField", "label", "Title")["_i"]
        save_id = self.control(mounted, "Button", "content", "Add record")["_i"]
        await client.type(title_id, "Survives backend restart")
        await client.click(save_id)
        await client.until(lambda message: "Record saved" in walk(message))
        persisted = self.native_values[DEFAULT_STORAGE_KEY]
        await client.close()
        await self.server.close()
        await self.start_server()
        restored_client = await self.connect()
        restored = await self.ready(restored_client)
        self.assertIn("Title: Survives backend restart", walk(restored))
        self.assertEqual(self.native_values[DEFAULT_STORAGE_KEY], persisted)
        self.assertEqual([call["name"] for call in restored_client.calls], ["get"])

    async def test_disconnect_after_native_commit_restores_one_record(self):
        client = await self.connect()
        mounted = await self.ready(client)
        title_id = self.control(mounted, "TextField", "label", "Title")["_i"]
        save_id = self.control(mounted, "Button", "content", "Add record")["_i"]
        client.drop_replies.add("set")
        await client.type(title_id, "Committed before disconnect")
        await client.click(save_id)
        await client.until(lambda message: message[0] == 5 and message[1]["name"] == "set")
        await client.close()
        restored_client = await self.connect()
        restored = await self.ready(restored_client)
        self.assertIn("Title: Committed before disconnect", walk(restored))
        self.assertEqual(len(json.loads(self.native_values[DEFAULT_STORAGE_KEY])["records"]), 1)
        self.assertEqual([call["name"] for call in restored_client.calls], ["get"])

    async def test_missing_read_reply_returns_reloadable_view(self):
        client = await self.connect()
        client.drop_replies.add("get")
        with self.assertLogs(level="ERROR"):
            failed = await client.until(lambda message: "Saved records could not be loaded. Reload to try again."
                                        in walk(message))
        save = self.control(failed, "Button", "content", "Add record")
        reload = self.control(failed, "TextButton", "content", "Reload")
        self.assertTrue(save["disabled"])
        self.assertFalse(reload.get("disabled", False))
        client.drop_replies.clear()
        await client.click(reload["_i"])
        await self.ready(client)
        self.assertNotIn(DEFAULT_STORAGE_KEY, self.native_values)

    async def test_missing_write_reply_requires_reload_and_keeps_committed_record(self):
        client = await self.connect()
        mounted = await self.ready(client)
        title_id = self.control(mounted, "TextField", "label", "Title")["_i"]
        save_id = self.control(mounted, "Button", "content", "Add record")["_i"]
        reload_id = self.control(mounted, "TextButton", "content", "Reload")["_i"]
        client.drop_replies.add("set")
        await client.type(title_id, "Committed without a reply")
        await client.click(save_id)
        with self.assertLogs(level="ERROR"):
            await client.until(lambda message: "Save interrupted. Reload to check saved records before continuing."
                               in walk(message))
        await client.click(save_id)
        client.drop_replies.clear()
        await client.click(reload_id)
        loaded = await self.ready(client)
        self.assertIn("Title: Committed without a reply", walk(loaded))
        self.assertEqual(sum(call["name"] == "set" for call in client.calls), 1)
        self.assertEqual(len(json.loads(self.native_values[DEFAULT_STORAGE_KEY])["records"]), 1)

    async def test_native_write_error_after_commit_requires_reload(self):
        client = await self.connect()
        mounted = await self.ready(client)
        title_id = self.control(mounted, "TextField", "label", "Title")["_i"]
        save_id = self.control(mounted, "Button", "content", "Add record")["_i"]
        reload_id = self.control(mounted, "TextButton", "content", "Reload")["_i"]
        client.write_error = "Native write result could not be confirmed"
        await client.type(title_id, "Kept despite reply error")
        await client.click(save_id)
        with self.assertLogs(level="ERROR"):
            await client.until(lambda message: "Save interrupted. Reload to check saved records before continuing."
                               in walk(message))
        await client.click(save_id)
        client.write_error = None
        await client.click(reload_id)
        restored = await self.ready(client)
        self.assertIn("Title: Kept despite reply error", walk(restored))
        self.assertEqual(sum(call["name"] == "set" for call in client.calls), 1)

    async def test_corrupt_data_after_mount_blocks_mutations_and_preserves_draft(self):
        client = await self.connect()
        mounted = await self.ready(client)
        title_id = self.control(mounted, "TextField", "label", "Title")["_i"]
        save_id = self.control(mounted, "Button", "content", "Add record")["_i"]
        reload_id = self.control(mounted, "TextButton", "content", "Reload")["_i"]
        await client.type(title_id, "Original")
        await client.click(save_id)
        await client.until(lambda message: "Record saved" in walk(message))
        saved = self.native_values[DEFAULT_STORAGE_KEY]
        await client.type(title_id, "Retained draft")
        self.native_values[DEFAULT_STORAGE_KEY] = "broken JSON"
        await client.click(save_id)
        with self.assertLogs(level="ERROR"):
            await client.until(lambda message: "Saved records are unavailable or changed. Reload before continuing."
                               in walk(message))
        self.assertEqual(self.native_values[DEFAULT_STORAGE_KEY], "broken JSON")
        await client.click(save_id)
        self.native_values[DEFAULT_STORAGE_KEY] = saved
        await client.click(reload_id)
        await self.ready(client)
        self.assertEqual([call["name"] for call in client.calls], ["get", "get", "set", "get", "get"])
        self.assertEqual(self.native_values[DEFAULT_STORAGE_KEY], saved)
        await client.click(save_id)
        await client.until(lambda message: "Record saved" in walk(message))
        self.assertEqual([item["values"]["title"] for item in
                          json.loads(self.native_values[DEFAULT_STORAGE_KEY])["records"]],
                         ["Original", "Retained draft"])


if __name__ == "__main__":
    unittest.main()
