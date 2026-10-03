"""Exercise JNI executor contracts without Android or installed Flet."""

import asyncio
import contextvars
import sys
import threading
import types
import unittest
from unittest.mock import patch

from runtime.android_jni_executor import AppClassLoaderExecutor


class NativeCallbackStub:
    def __init__(self):
        self.prepared = []
        self.executed = []

    def app_loader_callback(self, handler):
        self.prepared.append(threading.get_ident())

        def execute():
            self.executed.append(threading.get_ident())
            return handler()

        return execute

    def module(self):
        module = types.ModuleType("android_jni")
        module.app_loader_callback = self.app_loader_callback
        return module


class ExecutorTests(unittest.TestCase):
    def setUp(self):
        self.callback = NativeCallbackStub()
        self.enterContext(patch.dict(sys.modules, {"android_jni": self.callback.module()}))

    def test_return_identity_kwargs_and_owner_preparation(self):
        owner = threading.get_ident()
        result = object()

        def handler(value, *, fn):
            self.assertEqual(value, "runner")
            self.assertIs(fn, result)
            return fn

        with AppClassLoaderExecutor(max_workers=1) as executor:
            future = executor.submit(handler, "runner", fn=result)
            self.assertIs(future.result(timeout=5), result)
        self.assertEqual(self.callback.prepared, [owner])
        self.assertEqual(len(self.callback.executed), 1)
        self.assertNotEqual(self.callback.executed[0], owner)

    def test_base_exception_identity_is_preserved(self):
        class CallbackError(BaseException):
            pass

        error = CallbackError("native callback failed")

        def fail():
            raise error

        with AppClassLoaderExecutor(max_workers=1) as executor:
            future = executor.submit(fail)
            self.assertIs(future.exception(timeout=5), error)

    def test_invalid_callable_fails_in_future(self):
        with AppClassLoaderExecutor(max_workers=1) as executor:
            future = executor.submit(None)
            self.assertIsInstance(future.exception(timeout=5), TypeError)

    def test_cancelling_queued_work_prevents_native_execution(self):
        started = threading.Event()
        release = threading.Event()
        invoked = threading.Event()

        def block():
            started.set()
            if not release.wait(5):
                raise TimeoutError("test did not release worker")

        executor = AppClassLoaderExecutor(max_workers=1)
        try:
            first = executor.submit(block)
            self.assertTrue(started.wait(5))
            queued = executor.submit(invoked.set)
            self.assertTrue(queued.cancel())
            release.set()
            first.result(timeout=5)
            self.assertFalse(invoked.is_set())
            self.assertEqual(len(self.callback.executed), 1)
        finally:
            release.set()
            executor.shutdown(wait=True, cancel_futures=True)

    def test_shutdown_cancels_queue_and_can_be_joined_afterward(self):
        started = threading.Event()
        release = threading.Event()
        invoked = threading.Event()

        def block():
            started.set()
            if not release.wait(5):
                raise TimeoutError("test did not release worker")

        executor = AppClassLoaderExecutor(max_workers=1)
        try:
            running = executor.submit(block)
            self.assertTrue(started.wait(5))
            queued = executor.submit(invoked.set)
            executor.shutdown(wait=False, cancel_futures=True)
            self.assertTrue(queued.cancelled())
            self.assertFalse(running.cancel())
            with self.assertRaises(RuntimeError):
                executor.submit(invoked.set)
            release.set()
            running.result(timeout=5)
        finally:
            release.set()
            executor.shutdown(wait=True, cancel_futures=True)
        self.assertFalse(invoked.is_set())
        self.assertEqual(len(self.callback.executed), 1)


class AsyncExecutorTests(unittest.IsolatedAsyncioTestCase):
    async def test_to_thread_uses_native_default_pool_and_copies_context(self):
        callback = NativeCallbackStub()
        owner = threading.get_ident()
        marker = contextvars.ContextVar("runner_marker")
        marker.set("runner")
        with patch.dict(sys.modules, {"android_jni": callback.module()}):
            executor = AppClassLoaderExecutor(max_workers=1)
            asyncio.get_running_loop().set_default_executor(executor)
            try:
                self.assertEqual(await asyncio.to_thread(marker.get), "runner")
            finally:
                # Flet owns non-blocking close; the event loop can still join it.
                executor.shutdown(wait=False, cancel_futures=True)
                await asyncio.get_running_loop().shutdown_default_executor()
        self.assertEqual(callback.prepared, [owner])
        self.assertEqual(len(callback.executed), 1)
        self.assertNotEqual(callback.executed[0], owner)


if __name__ == "__main__":
    unittest.main()
