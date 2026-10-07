"""Application data survives fresh stores and rejects unsafe replacements."""

import asyncio
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from runtime.application_data import (
    ApplicationDataError, ApplicationDataStore, DEFAULT_STORAGE_KEY,
    get_application_data_store,
)


def preferences_service(values):
    async def write(key, value):
        values[key] = value
        return True

    return types.SimpleNamespace(get=AsyncMock(side_effect=values.get),
                                 set=AsyncMock(side_effect=write))


class ApplicationDataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.values = {"runner.capability": "working"}
        self.preferences = preferences_service(self.values)
        self.store = ApplicationDataStore(self.preferences)

    async def test_create_edit_delete_survive_fresh_service_instances(self):
        self.assertEqual(await self.store.load(), [])
        self.preferences.set.assert_not_awaited()
        records = await self.store.save({"title": "星図", "details": "First\nsecond"})
        record_id = records[0]["id"]
        restored = ApplicationDataStore(preferences_service(self.values))
        self.assertEqual(await restored.load(), records)
        edited = await restored.save({"title": "星図 updated"}, record_id)
        self.assertEqual(edited, [{"id": record_id, "values": {
            "title": "星図 updated", "details": "First\nsecond"}}])
        self.assertEqual(await restored.delete(record_id), [])
        self.assertEqual(await ApplicationDataStore(preferences_service(self.values)).load(), [])
        self.assertEqual(self.values["runner.capability"], "working")

    async def test_independent_keys_keep_collections_separate(self):
        other = ApplicationDataStore(self.preferences, "sdk.runner.application.contacts")
        first = await self.store.save({"title": "A"})
        second = await other.save({"name": "B"})
        self.assertEqual(await self.store.load(), first)
        self.assertEqual(await other.load(), second)
        self.assertNotEqual(first[0]["id"], second[0]["id"])

    async def test_malformed_or_future_data_is_never_overwritten(self):
        invalid = [
            "", "broken JSON", True, [],
            json.dumps([]),
            json.dumps({"version": 2, "records": []}),
            json.dumps({"version": True, "records": []}),
            json.dumps({"version": 1, "records": {}}),
            json.dumps({"version": 1, "records": [None]}),
            json.dumps({"version": 1, "records": [{"id": "", "values": {}}]}),
            json.dumps({"version": 1, "records": [{"id": "a", "values": {"title": 4}}]}),
            json.dumps({"version": 1, "records": [{"id": "a", "values": {"": "bad"}}]}),
            json.dumps({"version": 1, "records": [{"id": "a", "values": {}}] * 2}),
        ]
        for raw in invalid:
            with self.subTest(raw=raw):
                self.values[DEFAULT_STORAGE_KEY] = raw
                for operation in (self.store.load,
                                  lambda: self.store.save({"title": "New"}),
                                  lambda: self.store.delete("a")):
                    with self.assertRaises(ApplicationDataError):
                        await operation()
                self.assertEqual(self.values[DEFAULT_STORAGE_KEY], raw)
        self.preferences.set.assert_not_awaited()

    async def test_failed_write_keeps_previously_saved_records(self):
        records = await self.store.save({"title": "Original"})
        original = self.values[DEFAULT_STORAGE_KEY]
        self.preferences.set.side_effect = None
        self.preferences.set.return_value = False
        for operation in (lambda: self.store.save({"title": "New"}),
                          lambda: self.store.save({"title": "Edited"}, records[0]["id"]),
                          lambda: self.store.delete(records[0]["id"])):
            with self.assertRaisesRegex(ApplicationDataError, "could not save"):
                await operation()
            self.assertEqual(self.values[DEFAULT_STORAGE_KEY], original)

    async def test_native_read_error_propagates_without_writing(self):
        self.preferences.get.side_effect = RuntimeError("native read failed")
        with self.assertRaisesRegex(RuntimeError, "native read failed"):
            await self.store.save({"title": "New"})
        self.preferences.set.assert_not_awaited()

    async def test_stale_edit_cannot_recreate_a_deleted_record(self):
        records = await self.store.save({"title": "Original"})
        record_id = records[0]["id"]
        await self.store.delete(record_id)
        self.preferences.set.reset_mock()
        with self.assertRaisesRegex(ApplicationDataError, "no longer exists"):
            await self.store.save({"title": "Stale edit"}, record_id)
        self.assertEqual(await self.store.load(), [])
        self.assertEqual(await self.store.delete(record_id), [])
        self.preferences.set.assert_not_awaited()

    async def test_simultaneous_mutations_do_not_lose_records(self):
        entered = asyncio.Event()
        release = asyncio.Event()
        write = self.preferences.set.side_effect

        async def paused_write(key, value):
            entered.set()
            await release.wait()
            return await write(key, value)

        self.preferences.set.side_effect = paused_write
        first = asyncio.create_task(self.store.save({"title": "First"}))
        second = None
        try:
            await asyncio.wait_for(entered.wait(), 3)
            second = asyncio.create_task(self.store.save({"title": "Second"}))
            await asyncio.sleep(0)
            self.assertEqual(self.preferences.get.await_count, 1)
            release.set()
            await asyncio.wait_for(asyncio.gather(first, second), 3)
        finally:
            release.set()
            await asyncio.gather(first, *([second] if second else []), return_exceptions=True)
        self.assertEqual([record["values"]["title"] for record in await self.store.load()],
                         ["First", "Second"])

    async def test_cancelled_write_releases_lock_for_retry(self):
        entered = asyncio.Event()
        write = self.preferences.set.side_effect

        async def paused_write(key, value):
            entered.set()
            await asyncio.Future()

        self.preferences.set.side_effect = paused_write
        task = asyncio.create_task(self.store.save({"title": "Cancelled"}))
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.preferences.set.side_effect = write
        records = await asyncio.wait_for(self.store.save({"title": "Retry"}), 3)
        self.assertEqual([record["values"]["title"] for record in records], ["Retry"])

    async def test_returned_records_do_not_mutate_saved_data(self):
        records = await self.store.save({"title": "Original"})
        records[0]["values"]["title"] = "Changed outside store"
        self.assertEqual((await self.store.load())[0]["values"]["title"], "Original")

    async def test_invalid_values_are_rejected_before_native_io(self):
        for values in (None, [], {"": "value"}, {"title": None}, {1: "value"}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                await self.store.save(values)
        self.preferences.get.assert_not_awaited()
        self.preferences.set.assert_not_awaited()


class ApplicationDataOwnershipTests(unittest.TestCase):
    def test_reopening_collections_reuses_page_service_and_per_key_store(self):
        page = types.SimpleNamespace()
        factory = Mock(return_value=preferences_service({}))
        flet = types.ModuleType("flet")
        flet.SharedPreferences = factory
        with patch.dict(sys.modules, {"flet": flet}):
            first = get_application_data_store(page)
            self.assertIs(get_application_data_store(page), first)
            other = get_application_data_store(page, "other")
            self.assertIs(get_application_data_store(page, "other"), other)
            self.assertIsNot(first, other)
            self.assertIs(first.preferences, other.preferences)
            factory.assert_called_once_with()
            second_page = get_application_data_store(types.SimpleNamespace())
            self.assertIsNot(first, second_page)
            self.assertEqual(factory.call_count, 2)

    def test_invalid_key_creates_no_native_service(self):
        for key in (None, "", "   ", 4):
            with self.subTest(key=key), self.assertRaises(ValueError):
                get_application_data_store(types.SimpleNamespace(), key)


if __name__ == "__main__":
    unittest.main()
