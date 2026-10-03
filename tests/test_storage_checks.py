"""Exercise durable evidence and native file reads without Android services."""

import hashlib
import json
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from runtime.storage_checks import PERSISTENCE_KEY, RECEIPT_NAME, check_persistence, picked_file_receipt


def store_service(values):
    async def set_value(key, value):
        values[key] = value
        return True

    return types.SimpleNamespace(get=AsyncMock(side_effect=lambda key: values.get(key)),
                                 set=AsyncMock(side_effect=set_value))


class PersistenceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / "data"
        self.preferences = {}
        self.secure = {}

    async def seed(self):
        preferences = store_service(self.preferences)
        secure = store_service(self.secure)
        with patch("runtime.storage_checks.os.getpid", return_value=101):
            result = await check_persistence(preferences, secure, self.directory)
        return result, preferences, secure

    async def test_fresh_services_read_original_challenge_without_writing(self):
        seeded, _, _ = await self.seed()
        path = self.directory / RECEIPT_NAME
        contents = path.read_bytes()
        preferences = store_service(self.preferences)
        secure = store_service(self.secure)
        with patch("runtime.storage_checks.os.getpid", return_value=202):
            restored = await check_persistence(preferences, secure, self.directory)
        self.assertEqual(seeded["state"], "seeded")
        self.assertEqual(restored, {**seeded, "state": "restored", "pid": 202})
        self.assertEqual(path.read_bytes(), contents)
        preferences.set.assert_not_awaited()
        secure.set.assert_not_awaited()
        self.assertNotIn(self.preferences[PERSISTENCE_KEY], json.dumps(restored))

    async def test_lost_or_changed_service_value_is_not_repaired(self):
        await self.seed()
        contents = (self.directory / RECEIPT_NAME).read_bytes()
        for values in (self.preferences, self.secure):
            original = values[PERSISTENCE_KEY]
            for replacement in (None, "different"):
                with self.subTest(storage=id(values), replacement=replacement):
                    values[PERSISTENCE_KEY] = replacement
                    preferences = store_service(self.preferences)
                    secure = store_service(self.secure)
                    with self.assertRaisesRegex(RuntimeError, "disagree"):
                        await check_persistence(preferences, secure, self.directory)
                    preferences.set.assert_not_awaited()
                    secure.set.assert_not_awaited()
                    self.assertEqual((self.directory / RECEIPT_NAME).read_bytes(), contents)
            values[PERSISTENCE_KEY] = original

    async def test_missing_file_does_not_reseed_existing_native_values(self):
        await self.seed()
        (self.directory / RECEIPT_NAME).unlink()
        preferences = store_service(self.preferences)
        secure = store_service(self.secure)
        with self.assertRaisesRegex(RuntimeError, "receipt is missing"):
            await check_persistence(preferences, secure, self.directory)
        preferences.set.assert_not_awaited()
        secure.set.assert_not_awaited()
        self.assertFalse((self.directory / RECEIPT_NAME).exists())

    async def test_refused_preference_write_does_not_commit_receipt(self):
        preferences = store_service(self.preferences)
        preferences.set.return_value = False
        preferences.set.side_effect = None
        secure = store_service(self.secure)
        with self.assertRaisesRegex(RuntimeError, "refused"):
            await check_persistence(preferences, secure, self.directory)
        secure.set.assert_not_awaited()
        self.assertFalse((self.directory / RECEIPT_NAME).exists())

    async def test_failed_secure_write_cannot_be_mistaken_for_durable_success(self):
        preferences = store_service(self.preferences)
        secure = store_service(self.secure)
        secure.set.side_effect = RuntimeError("native storage failed")
        with self.assertRaisesRegex(RuntimeError, "native storage failed"):
            await check_persistence(preferences, secure, self.directory)
        self.assertFalse((self.directory / RECEIPT_NAME).exists())
        # A later run must expose the partial write instead of repairing its evidence.
        preferences.set.reset_mock()
        secure.set.reset_mock()
        with self.assertRaisesRegex(RuntimeError, "receipt is missing"):
            await check_persistence(preferences, secure, self.directory)
        preferences.set.assert_not_awaited()
        secure.set.assert_not_awaited()

    async def test_failed_readback_does_not_commit_receipt(self):
        preferences = store_service(self.preferences)
        secure = store_service(self.secure)
        secure.get.side_effect = None
        secure.get.return_value = None
        with self.assertRaisesRegex(RuntimeError, "readback failed"):
            await check_persistence(preferences, secure, self.directory)
        self.assertFalse((self.directory / RECEIPT_NAME).exists())

    async def test_invalid_receipt_is_not_overwritten(self):
        self.directory.mkdir()
        path = self.directory / RECEIPT_NAME
        for value in ([], {"token": "invalid", "source_pid": 101},
                      {"token": "0" * 64, "source_pid": True}):
            with self.subTest(value=value):
                contents = json.dumps(value)
                path.write_text(contents)
                preferences = store_service(self.preferences)
                secure = store_service(self.secure)
                with self.assertRaisesRegex(RuntimeError, "Invalid durable"):
                    await check_persistence(preferences, secure, self.directory)
                preferences.set.assert_not_awaited()
                secure.set.assert_not_awaited()
                self.assertEqual(path.read_text(), contents)


class PickedFileTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "picked.bin"

    def test_binary_file_larger_than_chunk_is_read_in_full(self):
        contents = bytes(range(256)) * 600 + "Runner café".encode()
        self.path.write_bytes(contents)
        selected = types.SimpleNamespace(name="picked.bin", size=len(contents), path=str(self.path))
        self.assertEqual(picked_file_receipt(selected),
                         {"name": "picked.bin", "size": len(contents),
                          "sha256": hashlib.sha256(contents).hexdigest()})

    def test_stale_picker_size_fails_instead_of_reporting_success(self):
        self.path.write_bytes(b"changed native file")
        selected = types.SimpleNamespace(name="picked.bin", size=1, path=str(self.path))
        with self.assertRaisesRegex(RuntimeError, "size differs"):
            picked_file_receipt(selected)

    def test_unavailable_native_path_is_explicit(self):
        selected = types.SimpleNamespace(name="picked.bin", size=0, path=None)
        with self.assertRaisesRegex(RuntimeError, "no native readable path"):
            picked_file_receipt(selected)


if __name__ == "__main__":
    unittest.main()
