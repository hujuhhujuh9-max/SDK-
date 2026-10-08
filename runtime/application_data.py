"""Small application record collections persisted with Flet SharedPreferences."""

import asyncio
import json
import math
import uuid


DEFAULT_STORAGE_KEY = "sdk.runner.application.records"
DEFAULT_NATIVE_TIMEOUT = 10.0


class ApplicationDataError(RuntimeError):
    """Saved data could not be read or written safely."""


class UnconfirmedWriteError(ApplicationDataError):
    """A native write was requested, but its persisted result is unknown."""


class ReloadRequiredError(ApplicationDataError):
    """Records are unreadable or stale; reload before another mutation."""


def _validate_key(key):
    if not isinstance(key, str) or not key.strip():
        raise ValueError("A nonempty storage key is required")


def _validate_values(values):
    if not isinstance(values, dict) or any(
        not isinstance(name, str) or not name.strip() or not isinstance(value, str)
        for name, value in values.items()
    ):
        raise ValueError("Record values must map nonempty field names to strings")


class ApplicationDataStore:
    """Serialize read/modify/write operations for one small record collection.

    Mutations return the saved list, so the UI needs no second read after a write.
    Reuse one store per key on a page; separate processes are not coordinated.
    """

    def __init__(self, preferences, key=DEFAULT_STORAGE_KEY, *, timeout=DEFAULT_NATIVE_TIMEOUT):
        _validate_key(key)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0):
            raise ValueError("Native preferences timeout must be positive and finite")
        self.preferences = preferences
        self.key = key
        self.timeout = timeout
        self._lock = asyncio.Lock()

    async def _read(self):
        try:
            async with asyncio.timeout(self.timeout):
                raw = await self.preferences.get(self.key)
        except TimeoutError:
            raise
        except Exception as error:
            raise ReloadRequiredError("Saved records could not be read") from error
        if raw is None:
            return []
        try:
            if not isinstance(raw, str):
                raise ValueError("Expected JSON text")
            data = json.loads(raw)
            if (not isinstance(data, dict) or type(data.get("version")) is not int
                    or data["version"] != 1 or not isinstance(data.get("records"), list)):
                raise ValueError("Unsupported record collection")
            identifiers = set()
            for record in data["records"]:
                if (not isinstance(record, dict) or not isinstance(record.get("id"), str)
                        or not record["id"].strip() or record["id"] in identifiers):
                    raise ValueError("Invalid or duplicate record ID")
                _validate_values(record.get("values"))
                identifiers.add(record["id"])
            return data["records"]
        except ValueError as error:
            raise ReloadRequiredError("Saved records have an unsupported format") from error

    async def _write(self, records):
        payload = json.dumps({"version": 1, "records": records}, ensure_ascii=False)
        try:
            async with asyncio.timeout(self.timeout):
                accepted = await self.preferences.set(self.key, payload)
        except Exception as error:
            raise UnconfirmedWriteError("The native write result could not be confirmed") from error
        if not accepted:
            # Native preferences can update their cache before a rejected write.
            raise UnconfirmedWriteError("The native write result could not be confirmed")
        return records

    async def load(self):
        """Read fresh records without writing or replacing invalid saved data."""
        async with self._lock:
            return await self._read()

    async def save(self, values, record_id=None):
        """Add a record or edit an existing ID, retaining unedited fields."""
        _validate_values(values)
        values = dict(values)
        async with self._lock:
            records = await self._read()
            if record_id is None:
                records.append({"id": uuid.uuid4().hex, "values": values})
            else:
                record = next((item for item in records if item["id"] == record_id), None)
                if record is None:
                    raise ReloadRequiredError("The record no longer exists; reload before editing")
                record["values"].update(values)
            return await self._write(records)

    async def delete(self, record_id):
        """Remove only the selected record; an already absent ID is a no-op."""
        async with self._lock:
            records = await self._read()
            remaining = [item for item in records if item["id"] != record_id]
            if len(remaining) == len(records):
                return records
            return await self._write(remaining)


def get_application_data_store(page, key=DEFAULT_STORAGE_KEY):
    """Reuse one Flet service per page and one locked store per storage key.

    Call from a Flet page/event context, where services register themselves.
    """
    _validate_key(key)
    state = getattr(page, "_runner_application_data", None)
    if state is None:
        import flet as ft

        state = {"preferences": ft.SharedPreferences(), "stores": {}}
        page._runner_application_data = state
    if key not in state["stores"]:
        state["stores"][key] = ApplicationDataStore(state["preferences"], key)
    return state["stores"][key]
