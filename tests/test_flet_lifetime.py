"""Regressions for the prepared Flet source's resource lifetime."""

import asyncio
import contextlib
import gc
import importlib
import importlib.util
import os
import tempfile
import types
import unittest
import weakref
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    from flet.controls.context import _context_page
    from flet.controls.services.battery import Battery
    from flet.controls.core.raw_image import RawImage
    from flet.messaging.connection import Connection
    from flet.messaging.flet_socket_server import FletSocketServer
    from flet.messaging.session import Session
    from flet.pubsub.pubsub_hub import PubSubHub
else:
    Connection = object


async def wait_until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.01)


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class DataChannelLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix="flet-lifetime-")
        self.socket_path = str(Path(self.folder.name) / "flet.sock")
        self.server = FletSocketServer(
            loop=asyncio.get_running_loop(),
            uds_path=self.socket_path,
            executor=ThreadPoolExecutor(max_workers=1),
        )
        self.clients = []
        await self.server.start()

    async def asyncTearDown(self):
        for _, writer in self.clients:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()
        await self.server.close()
        await asyncio.sleep(0)
        self.folder.cleanup()

    async def connect_client(self):
        client = await asyncio.open_unix_connection(self.socket_path)
        self.clients.append(client)
        return client

    async def test_raw_image_remount_closes_only_the_previous_channel(self):
        self.server.session = Session(self.server)
        image = RawImage()
        self.server.session.page.controls = [image]
        self.server.session.get_page_patch()
        image._capture_channel(types.SimpleNamespace(channel_id=1))
        old_channel = image._channel
        pending_ack = asyncio.get_running_loop().create_future()
        image._pending_acks.append(pending_ack)

        image._capture_channel(types.SimpleNamespace(channel_id=2))
        new_channel = image._channel
        self.assertIsNot(old_channel, new_channel)
        self.assertTrue(old_channel._closed)
        self.assertIsNone(old_channel._handler)
        self.assertEqual(set(self.server._data_channels), {2})
        self.assertTrue(pending_ack.done())
        self.assertIsNone(pending_ack.result())

        image._capture_channel(types.SimpleNamespace(channel_id=2))
        self.assertIs(image._channel, new_channel)
        self.assertFalse(new_channel._closed)
        self.assertEqual(set(self.server._data_channels), {2})

    async def test_client_eof_releases_registered_channels(self):
        _, writer = await self.connect_client()
        await wait_until(lambda: self.server._FletSocketServer__connected)
        channel = self.server.data_channel_for(1)
        channel.on_bytes(lambda payload: None)

        writer.close()
        await writer.wait_closed()
        await wait_until(lambda: not self.server._FletSocketServer__connected)
        self.assertEqual(self.server._data_channels, {})
        self.assertTrue(channel._closed)
        self.assertIsNone(channel._handler)

    async def test_replacement_connection_cannot_reuse_a_stale_channel(self):
        await self.connect_client()
        await wait_until(lambda: self.server._FletSocketServer__connected)
        channel = self.server.data_channel_for(1)
        previous_token = self.server._FletSocketServer__connection_token

        await self.connect_client()
        await wait_until(
            lambda: self.server._FletSocketServer__connection_token > previous_token
        )
        self.assertTrue(channel._closed)
        self.assertEqual(self.server._data_channels, {})
        replacement = self.server.data_channel_for(1)
        self.assertIsNot(replacement, channel)
        self.assertFalse(replacement._closed)

    async def test_close_clears_channels_without_an_active_client(self):
        channel = self.server.data_channel_for(1)
        await self.server.close()
        self.assertTrue(channel._closed)
        self.assertEqual(self.server._data_channels, {})


class _RecordingConnection(Connection):
    def __init__(self):
        super().__init__()
        self.loop = asyncio.get_running_loop()
        self.pubsubhub = PubSubHub(loop=self.loop)
        self.messages = []
        self.message_ready = asyncio.Event()

    def send_message(self, message):
        self.messages.append(message)
        self.message_ready.set()



@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class ServiceRegistryOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = _RecordingConnection()
        self.session = Session(self.connection)
        self.page = self.session.page
        self.session.get_page_patch()
        self.token = _context_page.set(self.page)

    async def asyncTearDown(self):
        _context_page.reset(self.token)
        self.session.close()
        await asyncio.sleep(0)

    async def test_single_dictionary_reference_keeps_the_service_mounted_after_collection(self):
        self.page._owned_services = {"battery": Battery()}
        service_id = self.page._owned_services["battery"]._i
        gc.collect()
        await self.session.after_event(None)
        self.assertEqual([service._i for service in self.page._services._services], [service_id])
        self.assertIs(self.session.index.get(service_id), self.page._owned_services["battery"])

    async def test_unowned_service_is_removed_without_losing_the_owned_service(self):
        self.page._owned_services = {"battery": Battery()}
        owned_id = self.page._owned_services["battery"]._i
        orphan = Battery()
        orphan_ref = weakref.ref(orphan)
        orphan_id = orphan._i
        del orphan
        gc.collect()
        await self.session.after_event(None)
        self.assertEqual([service._i for service in self.page._services._services], [owned_id])
        self.assertNotIn(orphan_id, self.session.index)
        gc.collect()
        self.assertIsNone(orphan_ref())

    async def test_releasing_the_last_application_reference_unmounts_the_service(self):
        self.page._owned_battery = Battery()
        service_id = self.page._owned_battery._i
        service_ref = weakref.ref(self.page._owned_battery)
        gc.collect()
        await self.session.after_event(None)
        self.assertIn(service_id, self.session.index)
        del self.page._owned_battery
        gc.collect()
        await self.session.after_event(None)
        self.assertEqual(self.page._services._services, [])
        self.assertNotIn(service_id, self.session.index)
        gc.collect()
        self.assertIsNone(service_ref())

@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class InvokeMethodLifetimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = _RecordingConnection()
        self.session = Session(self.connection)

    async def asyncTearDown(self):
        self.session.close()
        await asyncio.sleep(0)

    async def begin_call(self, timeout=1):
        self.connection.message_ready.clear()
        task = asyncio.create_task(self.session.invoke_method(
            self.session.page._i, "probe", {}, timeout=timeout
        ))
        await asyncio.wait_for(self.connection.message_ready.wait(), 1)
        return task, self.connection.messages[-1].body.call_id

    def assert_no_waiters(self):
        self.assertEqual(self.session._Session__method_calls, {})
        self.assertEqual(self.session._Session__method_call_results, {})

    async def test_cancelled_call_drops_waiter_and_ignores_late_replies(self):
        task, call_id = await self.begin_call()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_no_waiters()

        self.session.handle_invoke_method_results(
            self.session.page._i, call_id, "late", None
        )
        # A cancelled control may already have been removed from the page.
        self.session.handle_invoke_method_results(-1, call_id, "late", None)
        self.assert_no_waiters()

    async def test_cancellation_after_reply_drops_the_buffered_result(self):
        task, call_id = await self.begin_call()
        self.session.handle_invoke_method_results(
            self.session.page._i, call_id, "result", None
        )
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assert_no_waiters()

    async def test_synchronous_transport_error_releases_waiter(self):
        def fail_send(message):
            raise ValueError("encoding failed")

        self.connection.send_message = fail_send
        with self.assertRaisesRegex(ValueError, "encoding failed"):
            await self.session.invoke_method(self.session.page._i, "probe", {})
        self.assert_no_waiters()

    async def test_success_returns_result_and_releases_waiter(self):
        task, call_id = await self.begin_call()
        self.session.handle_invoke_method_results(
            self.session.page._i, call_id, {"value": 7}, None
        )
        self.assertEqual(await task, {"value": 7})
        self.assert_no_waiters()

    async def test_native_error_still_reaches_the_caller(self):
        task, call_id = await self.begin_call()
        self.session.handle_invoke_method_results(
            self.session.page._i, call_id, None, "native failure"
        )
        with self.assertRaisesRegex(RuntimeError, "native failure"):
            await task
        self.assert_no_waiters()

    async def test_timeout_releases_waiter_and_ignores_late_reply(self):
        task, call_id = await self.begin_call(timeout=0.001)
        with self.assertRaises(TimeoutError):
            await task
        self.assert_no_waiters()
        self.session.handle_invoke_method_results(
            self.session.page._i, call_id, "late", None
        )
        self.assert_no_waiters()

    async def test_session_close_wakes_pending_calls_and_releases_waiter(self):
        task, _ = await self.begin_call()
        self.session.close()
        with self.assertRaisesRegex(RuntimeError, "Session closed"):
            await task
        self.assert_no_waiters()


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class ExecutorOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_run_async_supplies_one_executor_to_socket_and_pubsub(self):
        app = importlib.import_module("flet.app")
        executor = ThreadPoolExecutor(max_workers=1)
        server_ready = asyncio.Event()
        servers = []
        original_start = FletSocketServer.start

        async def started(server):
            await original_start(server)
            servers.append(server)
            server_ready.set()

        with tempfile.TemporaryDirectory(prefix="flet-executor-") as folder:
            environment = {
                "FLET_PLATFORM": "android",
                "FLET_FORCE_WEB_SERVER": "false",
                "FLET_DART_BRIDGE_PORT": "",
                "FLET_SERVER_UDS_PATH": str(Path(folder) / "flet.sock"),
            }
            with patch.dict(os.environ, environment), patch.object(
                FletSocketServer, "start", started
            ):
                task = asyncio.create_task(app.run_async(
                    lambda page: None, view=None, executor=executor
                ))
                try:
                    await asyncio.wait_for(server_ready.wait(), 3)
                    server = servers[0]
                    self.assertIs(server.executor, executor)
                    self.assertIs(server.pubsubhub._PubSubHub__executor, executor)
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    with self.assertRaises(RuntimeError):
                        executor.submit(lambda: None)
                finally:
                    task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await task
                    executor.shutdown(wait=True, cancel_futures=True)

    async def test_web_transport_rejects_a_supplied_executor(self):
        await self.assert_unsupported({
            "FLET_PLATFORM": "android",
            "FLET_FORCE_WEB_SERVER": "true",
            "FLET_DART_BRIDGE_PORT": "",
        })

    async def test_dart_bridge_rejects_a_supplied_executor(self):
        await self.assert_unsupported({
            "FLET_PLATFORM": "android",
            "FLET_FORCE_WEB_SERVER": "false",
            "FLET_DART_BRIDGE_PORT": "7",
        })

    async def test_pyodide_rejects_a_supplied_executor(self):
        app = importlib.import_module("flet.app")
        with patch.object(app, "is_pyodide", return_value=True):
            await self.assert_unsupported({})

    async def assert_unsupported(self, environment):
        app = importlib.import_module("flet.app")
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with patch.dict(os.environ, environment):
                with self.assertRaisesRegex(
                    ValueError, "only supported by the socket transport"
                ):
                    await app.run_async(lambda page: None, view=None, executor=executor)
            # No server was created, so the caller still owns the rejected pool.
            self.assertTrue(executor.submit(lambda: True).result(timeout=1))
        finally:
            executor.shutdown(wait=True, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
