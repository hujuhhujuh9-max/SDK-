"""Exercise the optional form/list workflow without a native Flet client."""

import asyncio
import json
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from runtime.application_data import DEFAULT_STORAGE_KEY
from runtime.form_list import FormField, create_form_list_view


class Control:
    def __init__(self, *args, **kwargs):
        self.controls = args[0] if args and isinstance(args[0], list) else []
        self.value = args[0] if args and not isinstance(args[0], list) else None
        self.content = self.value
        self.visible = True
        self.disabled = False
        self.error_text = None
        self.__dict__.update(kwargs)


class FormListTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.values = {}

        async def write(key, value):
            self.values[key] = value
            return True

        self.preferences = types.SimpleNamespace(
            get=AsyncMock(side_effect=self.values.get), set=AsyncMock(side_effect=write))
        flet = types.ModuleType("flet")
        for name in ("Text", "TextField", "TextButton", "Button", "Row", "Column", "Container", "View"):
            setattr(flet, name, Control)
        flet.ScrollMode = types.SimpleNamespace(AUTO="auto")
        flet.SharedPreferences = Mock(return_value=self.preferences)
        self.flet = flet
        patched = patch.dict(sys.modules, {"flet": flet})
        patched.start()
        self.addCleanup(patched.stop)
        self.page = types.SimpleNamespace(
            views=[Control(route="/")], route="/menu", update=Mock(),
            push_route=AsyncMock(), on_route_change=Mock(), on_view_pop=Mock())

    def parts(self, view):
        controls = view.controls[0].controls
        inputs = {control.label: control for control in controls if hasattr(control, "label")}
        actions = next(control.controls for control in controls if len(control.controls) == 3)
        return inputs, actions, controls[-2], controls[-1]

    async def create(self, **options):
        view = await create_form_list_view(self.page, **options)
        self.inputs, self.actions, self.status, self.records = self.parts(view)
        self.save, self.cancel, self.reload = self.actions
        return view

    async def add(self, title, details=""):
        self.inputs["Title"].value = title
        self.inputs["Details"].value = details
        await self.save.on_click(None)

    def row_actions(self, index=0):
        return self.records.controls[index].content.controls[-1].controls

    async def test_entry_returns_view_without_changing_existing_routes(self):
        views = list(self.page.views)
        route_changed = self.page.on_route_change
        view_popped = self.page.on_view_pop
        on_back = AsyncMock()
        view = await self.create(route="/notes?source=menu", title="Notes", on_back=on_back)
        self.assertEqual(view.route, "/notes?source=menu")
        heading = view.controls[0].controls[0].controls
        self.assertEqual(heading[0].value, "Notes")
        await heading[1].on_click(None)
        on_back.assert_awaited_once_with(None)
        self.assertEqual(self.page.views, views)
        self.assertEqual(self.page.route, "/menu")
        self.assertIs(self.page.on_route_change, route_changed)
        self.assertIs(self.page.on_view_pop, view_popped)
        self.page.push_route.assert_not_awaited()
        self.page.update.assert_not_called()
        self.preferences.set.assert_not_awaited()
        self.assertIn("No records yet", self.records.controls[0].value)

    async def test_add_edit_cancel_delete_and_reopen(self):
        await self.create()
        await self.add("  Observatory  ", "  First\nsecond  ")
        saved = json.loads(self.values[DEFAULT_STORAGE_KEY])["records"][0]
        self.assertEqual(saved["values"], {"title": "Observatory", "details": "First\nsecond"})
        self.assertEqual(self.inputs["Title"].value, "")
        self.assertEqual(self.status.value, "Record saved")
        edit, delete = self.row_actions()
        edit.on_click(None)
        self.assertEqual(self.inputs["Title"].value, "Observatory")
        self.assertTrue(self.cancel.visible)
        self.inputs["Title"].value = "Cancelled change"
        self.cancel.on_click(None)
        self.assertFalse(self.cancel.visible)
        self.assertEqual(self.save.content, "Add record")
        edit.on_click(None)
        self.inputs["Title"].value = "Updated"
        await self.save.on_click(None)
        edited = json.loads(self.values[DEFAULT_STORAGE_KEY])["records"]
        self.assertEqual(len(edited), 1)
        self.assertEqual(edited[0]["id"], saved["id"])
        await self.create()
        self.flet.SharedPreferences.assert_called_once_with()
        self.assertEqual(self.records.controls[0].content.controls[0].value, "Title: Updated")
        edit, delete = self.row_actions()
        edit.on_click(None)
        await delete.on_click(None)
        self.assertEqual(json.loads(self.values[DEFAULT_STORAGE_KEY])["records"], [])
        self.assertEqual(self.inputs["Title"].value, "")
        self.assertFalse(self.cancel.visible)
        self.assertIn("No records yet", self.records.controls[0].value)

    async def test_validation_and_custom_schema_keep_separate_collections(self):
        await self.create(fields=(FormField("name", "Name", required=True, max_length=4),),
                          storage_key="sdk.runner.application.contacts")
        await self.save.on_click(None)
        self.assertEqual(self.inputs["Name"].error_text, "Name is required")
        self.inputs["Name"].value = "Too long"
        await self.save.on_click(None)
        self.assertEqual(self.inputs["Name"].error_text, "Use at most 4 characters")
        self.preferences.set.assert_not_awaited()
        self.inputs["Name"].value = "Mira"
        await self.save.on_click(None)
        self.assertIsNone(self.inputs["Name"].error_text)
        await self.create()
        self.assertIn("No records yet", self.records.controls[0].value)
        self.flet.SharedPreferences.assert_called_once_with()

    async def test_failed_save_keeps_form_and_existing_list_for_retry(self):
        await self.create()
        await self.add("Original")
        write = self.preferences.set.side_effect
        self.preferences.set.side_effect = None
        self.preferences.set.return_value = False
        with self.assertLogs(level="ERROR"):
            await self.add("Retry me")
        self.assertEqual(self.inputs["Title"].value, "Retry me")
        self.assertIn("could not be saved", self.status.value)
        self.assertEqual(len(self.records.controls), 1)
        self.assertFalse(self.save.disabled)
        self.preferences.set.side_effect = write
        await self.save.on_click(None)
        self.assertEqual([item["values"]["title"] for item in
                          json.loads(self.values[DEFAULT_STORAGE_KEY])["records"]],
                         ["Original", "Retry me"])

    async def test_unconfirmed_delete_retains_record_and_edit_until_reload(self):
        await self.create()
        await self.add("Keep me")
        edit, delete = self.row_actions()
        edit.on_click(None)
        self.preferences.set.side_effect = RuntimeError("native write failed")
        with self.assertLogs(level="ERROR"):
            await delete.on_click(None)
        self.assertEqual(self.inputs["Title"].value, "Keep me")
        self.assertTrue(self.cancel.visible)
        self.assertEqual(len(self.records.controls), 1)
        self.assertTrue(delete.disabled)
        self.assertTrue(self.save.disabled)
        self.assertFalse(self.reload.disabled)
        self.assertIn("Reload", self.status.value)
        await self.reload.on_click(None)
        self.assertFalse(self.save.disabled)
        self.assertEqual(self.inputs["Title"].value, "Keep me")

    async def test_failed_load_blocks_mutations_until_reload_succeeds(self):
        self.preferences.get.side_effect = RuntimeError("native read failed")
        with self.assertLogs(level="ERROR"):
            await self.create()
        self.assertTrue(self.save.disabled)
        self.assertTrue(self.inputs["Title"].disabled)
        self.assertFalse(self.reload.disabled)
        await self.add("Unavailable")
        self.preferences.set.assert_not_awaited()
        self.preferences.get.side_effect = self.values.get
        await self.reload.on_click(None)
        self.assertFalse(self.save.disabled)
        self.assertEqual(self.inputs["Title"].value, "Unavailable")
        await self.save.on_click(None)
        self.assertEqual(self.status.value, "Record saved")

    async def test_corrupt_load_does_not_erase_existing_data(self):
        self.values[DEFAULT_STORAGE_KEY] = "broken JSON"
        with self.assertLogs(level="ERROR"):
            await self.create()
        await self.add("Cannot overwrite")
        self.preferences.set.assert_not_awaited()
        self.assertEqual(self.values[DEFAULT_STORAGE_KEY], "broken JSON")

    async def test_unreadable_data_after_open_requires_reload_and_keeps_draft(self):
        for failure in ("native read failed", "corrupt data", "future version"):
            with self.subTest(failure=failure):
                self.values.clear()
                self.preferences.get.side_effect = self.values.get
                await self.create()
                await self.add("Original")
                original = self.values[DEFAULT_STORAGE_KEY]
                self.preferences.set.reset_mock()
                if failure == "native read failed":
                    self.preferences.get.side_effect = RuntimeError(failure)
                elif failure == "corrupt data":
                    self.values[DEFAULT_STORAGE_KEY] = "broken JSON"
                else:
                    self.values[DEFAULT_STORAGE_KEY] = json.dumps({"version": 2, "records": []})
                current = self.values[DEFAULT_STORAGE_KEY]
                with self.assertLogs(level="ERROR"):
                    await self.add("Unsaved draft")
                self.assertTrue(self.save.disabled)
                self.assertTrue(all(button.disabled for button in self.row_actions()))
                self.assertFalse(self.reload.disabled)
                self.assertIn("Reload", self.status.value)
                self.assertEqual(self.inputs["Title"].value, "Unsaved draft")
                self.assertEqual(self.values[DEFAULT_STORAGE_KEY], current)
                self.preferences.set.assert_not_awaited()
                await self.save.on_click(None)
                self.preferences.set.assert_not_awaited()
                self.preferences.get.side_effect = self.values.get
                self.values[DEFAULT_STORAGE_KEY] = original
                await self.reload.on_click(None)
                self.assertFalse(self.save.disabled)
                self.assertEqual(self.inputs["Title"].value, "Unsaved draft")
                await self.save.on_click(None)
                self.assertEqual([item["values"]["title"] for item in
                                  json.loads(self.values[DEFAULT_STORAGE_KEY])["records"]],
                                 ["Original", "Unsaved draft"])

    async def test_busy_form_ignores_second_submit_and_restores_controls(self):
        await self.create()
        entered = asyncio.Event()
        release = asyncio.Event()
        write = self.preferences.set.side_effect

        async def paused_write(key, value):
            entered.set()
            await release.wait()
            return await write(key, value)

        self.preferences.set.side_effect = paused_write
        task = asyncio.create_task(self.add("One click"))
        try:
            await asyncio.wait_for(entered.wait(), 3)
            self.assertTrue(self.save.disabled)
            self.assertTrue(self.reload.disabled)
            self.assertTrue(self.inputs["Title"].disabled)
            await self.save.on_click(None)
            await self.reload.on_click(None)
            self.cancel.on_click(None)
            self.assertEqual(self.preferences.set.await_count, 1)
            release.set()
            await asyncio.wait_for(task, 3)
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)
        self.assertFalse(self.save.disabled)
        self.assertFalse(self.reload.disabled)
        self.assertEqual(len(json.loads(self.values[DEFAULT_STORAGE_KEY])["records"]), 1)

    async def test_cancelled_submit_keeps_draft_until_reload_allows_retry(self):
        await self.create()
        entered = asyncio.Event()
        write = self.preferences.set.side_effect

        async def paused_write(key, value):
            entered.set()
            await asyncio.Future()

        self.preferences.set.side_effect = paused_write
        task = asyncio.create_task(self.add("Draft"))
        await asyncio.wait_for(entered.wait(), 3)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.save.disabled)
        self.assertTrue(self.inputs["Title"].disabled)
        self.assertFalse(self.reload.disabled)
        self.assertTrue(self.cancel.visible)
        self.assertIn("Reload", self.status.value)
        self.assertEqual(self.inputs["Title"].value, "Draft")
        self.preferences.set.side_effect = write
        await self.save.on_click(None)
        self.assertNotIn(DEFAULT_STORAGE_KEY, self.values)
        await self.reload.on_click(None)
        self.assertFalse(self.save.disabled)
        self.assertFalse(self.inputs["Title"].disabled)
        self.assertEqual(self.inputs["Title"].value, "Draft")
        await self.save.on_click(None)
        self.assertEqual(self.status.value, "Record saved")

    async def test_reopened_views_share_store_and_do_not_overwrite_stale_lists(self):
        first = await self.create()
        second = await self.create()
        first_inputs, first_actions, _, _ = self.parts(first)
        second_inputs, second_actions, _, _ = self.parts(second)
        first_inputs["Title"].value = "First view"
        await first_actions[0].on_click(None)
        second_inputs["Title"].value = "Second view"
        await second_actions[0].on_click(None)
        self.assertEqual([item["values"]["title"] for item in
                          json.loads(self.values[DEFAULT_STORAGE_KEY])["records"]],
                         ["First view", "Second view"])
        await first_actions[2].on_click(None)
        _, _, _, first_records = self.parts(first)
        self.assertEqual(len(first_records.controls), 2)
        self.flet.SharedPreferences.assert_called_once_with()

    async def test_reload_recovers_draft_after_another_view_deletes_edited_record(self):
        await self.create()
        await self.add("Original")
        edit, _ = self.row_actions()
        edit.on_click(None)
        self.inputs["Title"].value = "Unsaved draft"
        record_id = json.loads(self.values[DEFAULT_STORAGE_KEY])["records"][0]["id"]
        other_view = await create_form_list_view(self.page)
        other_records = self.parts(other_view)[3]
        other_delete = other_records.controls[0].content.controls[-1].controls[1]
        await other_delete.on_click(None)
        with self.assertLogs(level="ERROR"):
            await self.save.on_click(None)
        self.assertTrue(self.save.disabled)
        self.assertIn("Reload", self.status.value)
        self.preferences.set.reset_mock()
        await self.save.on_click(None)
        self.preferences.set.assert_not_awaited()
        await self.reload.on_click(None)
        self.assertEqual(self.inputs["Title"].value, "Unsaved draft")
        self.assertEqual(self.save.content, "Add record")
        self.assertIn("deleted", self.status.value)
        self.assertTrue(self.cancel.visible)
        self.assertIn("No records yet", self.records.controls[0].value)
        await self.save.on_click(None)
        records = json.loads(self.values[DEFAULT_STORAGE_KEY])["records"]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["values"]["title"], "Unsaved draft")
        self.assertNotEqual(records[0]["id"], record_id)

    async def test_invalid_schema_creates_no_native_service(self):
        for fields in ((), ("bad",), (FormField("a", "A"), FormField("a", "Again"))):
            with self.subTest(fields=fields), self.assertRaises(ValueError):
                await self.create(fields=fields)
        self.flet.SharedPreferences.assert_not_called()
        for options in ({"name": "", "label": "Label"},
                        {"name": "a", "label": ""},
                        {"name": "a", "label": "Label", "max_length": True},
                        {"name": "a", "label": "Label", "max_length": 0}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                FormField(**options)


if __name__ == "__main__":
    unittest.main()
