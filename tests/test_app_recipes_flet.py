"""Exercise app recipes through the pinned controls, wire patches and events."""

import asyncio
import importlib.util
import json
import unittest
from unittest.mock import AsyncMock

from runtime.app_recipes import DEFAULT_ROWS, DEFAULT_SOURCE, create_app_recipes_view
from scripts.flet_protocol import walk
from test_app_home_flet import AppConnection, control_tree


FLET_AVAILABLE = all(importlib.util.find_spec(package) is not None for package in (
    "flet", "flet_code_editor", "flet_datatable2", "flet_color_pickers", "flet_spinkit"))
if FLET_AVAILABLE:
    import flet as ft
    from flet.controls.context import _context_page
    from flet.messaging.protocol import MessageAction
    from flet.messaging.session import Session


@unittest.skipUnless(FLET_AVAILABLE, "Requires pinned Flet and four prepared extensions")
class AppRecipesFletTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.connection = AppConnection()
        self.session = Session(self.connection)
        self.page = self.session.page
        self.token = _context_page.set(self.page)
        self.connection.encode(self.session.get_page_patch())
        self.disposers = []

    async def asyncTearDown(self):
        for dispose in self.disposers:
            dispose()
        await self.settle()
        _context_page.reset(self.token)
        self.session.close()
        await asyncio.sleep(0)

    async def settle(self):
        for _ in range(3):
            await asyncio.sleep(0)

    async def mount(self, **options):
        view, dispose = create_app_recipes_view(self.page, **options)
        self.disposers.append(dispose)
        self.page.views[:] = [view]
        self.page.update()
        return view, dispose

    def semantic(self, view, identifier):
        return next(control for control in control_tree(view)
                    if isinstance(control, ft.Semantics) and control.identifier == identifier)

    def content(self, view, identifier):
        return self.semantic(view, identifier).content

    def button(self, view, label):
        return next(control for control in control_tree(view)
                    if isinstance(control, (ft.Button, ft.TextButton))
                    and control.content == label)

    async def click(self, view, label):
        await self.session.dispatch_event(self.button(view, label)._i, "click", None)

    async def edit(self, view, source):
        editor = self.content(view, "recipe-editor")
        # The pinned Dart editor updates value before its full-string event.
        self.session.apply_patch(editor._i, {"value": source})
        await self.session.dispatch_event(editor._i, "change", source)

    def values(self):
        return list(walk(self.connection.messages))

    def table_rows(self, view):
        return [(row.cells[0].content.value, row.cells[1].content.value, row.selected)
                for row in self.content(view, "recipe-table").rows]

    def assert_status(self, view, identifier, expected):
        self.assertEqual(self.content(view, identifier).value, expected)
        self.assertIn(expected, self.values())

    async def test_factory_preserves_runner_and_serializes_actual_extensions(self):
        self.page.route = "/diagnostics"
        callbacks = {name: AsyncMock() for name in (
            "on_route_change", "on_view_pop", "on_connect", "on_disconnect", "on_close")}
        for name, callback in callbacks.items():
            setattr(self.page, name, callback)
        views = list(self.page.views)
        services = list(self.page._services._services)
        sent = len(self.connection.messages)
        view, dispose = create_app_recipes_view(self.page, route="/app/recipes?entry=home")
        self.disposers.append(dispose)
        self.assertIsInstance(view, ft.View)
        self.assertEqual(view.route, "/app/recipes?entry=home")
        self.assertEqual(self.page.route, "/diagnostics")
        self.assertEqual(self.page.views, views)
        self.assertEqual(self.page._services._services, services)
        self.assertEqual(len(self.connection.messages), sent)
        for name, callback in callbacks.items():
            self.assertIs(getattr(self.page, name), callback)
        self.page.views[:] = [view]
        self.page.update()
        values = self.values()
        for control_type in ("CodeEditor", "DataTable2", "DataColumn2", "DataRow2",
                             "BlockPicker", "SpinKitThreeBounce"):
            self.assertIn(control_type, values)
        self.assertIn(DEFAULT_SOURCE, values)
        self.assertEqual(self.content(view, "recipe-editor").height, 220)
        self.assertEqual(self.content(view, "recipe-table").height, 240)
        self.assertFalse(self.semantic(view, "recipe-loading").visible)
        self.assertEqual(self.table_rows(view), [("Harbor", "5", False),
                                                ("Lighthouse", "2", False),
                                                ("Observatory", "1", False)])

    async def test_native_editor_change_applies_plain_rows_and_publishes_output(self):
        view, _ = await self.mount()
        source = '[{"name":"Beacon Ω","count":7},{"name":"Harbor","count":2}]'
        self.connection.messages.clear()
        await self.edit(view, source)
        await self.click(view, "Apply JSON")
        self.assertEqual(self.content(view, "recipe-editor").value, source)
        self.assertEqual(self.table_rows(view), [("Beacon Ω", "7", False),
                                                ("Harbor", "2", False)])
        self.assert_status(view, "recipe-editor-result", "Applied 2 rows")
        self.assertIn("Beacon Ω", self.values())
        self.assertIn("7", self.values())
        self.assertEqual(self.page._services._services, [])

    async def test_bad_json_and_schema_keep_source_and_previously_applied_rows(self):
        view, _ = await self.mount()
        await self.edit(view, '[{"name":"Kept","count":4}]')
        await self.click(view, "Apply JSON")
        invalid = [
            ("{broken", "Invalid JSON"),
            ("{}", "1 to 8 rows"),
            ("[]", "1 to 8 rows"),
            (json.dumps([{"name": str(i), "count": i} for i in range(9)]), "1 to 8 rows"),
            ('[{"name":"A","count":true}]', "integer from 0 to 999"),
            ('[{"name":"A","count":1.2}]', "integer from 0 to 999"),
            ('[{"name":"A","count":-1}]', "integer from 0 to 999"),
            ('[{"name":"A","count":1000}]', "integer from 0 to 999"),
            ('[{"name":"A"}]', "needs only name and count"),
            ('[{"name":"A","count":1,"extra":null}]', "needs only name and count"),
            ('[null]', "needs only name and count"),
            ('[{"name":"  ","count":1}]', "name of 1 to 80 characters"),
            ('[{"name":"\\ud800","count":1}]', "valid Unicode text"),
            ('[{"name":"\\udfff","count":1}]', "valid Unicode text"),
            (json.dumps([{"name": "x" * 81, "count": 1}]), "name of 1 to 80 characters"),
            ('[{"name":"A","count":1},{"name":" A ","count":2}]', "Duplicate name"),
            ("[" * 2000 + "]" * 2000,
             ("simple list of name/count rows", "needs only name and count")),
            (" " * 4097, "4096 characters"),
        ]
        self.connection.messages.clear()
        for source, message in invalid:
            with self.subTest(source=source[:80]):
                await self.edit(view, source)
                await self.click(view, "Apply JSON")
                error = self.content(view, "recipe-editor-result").value
                expected = (message,) if isinstance(message, str) else message
                self.assertTrue(any(item in error for item in expected), error)
                self.assertIn(error, self.values())
                self.assertEqual(self.content(view, "recipe-editor").value, source)
                self.assertEqual(self.table_rows(view), [("Kept", "4", False)])
                self.assertFalse(any(packet[0] == MessageAction.SESSION_CRASHED
                                     for packet in self.connection.messages))

    async def test_table_uses_typed_sort_and_native_bool_selection(self):
        view, _ = await self.mount()
        await self.click(view, "Table")
        table = self.content(view, "recipe-table")
        await self.session.dispatch_event(table.rows[1]._i, "select_change", True)
        self.assert_status(view, "recipe-table-result",
                           "Order: Harbor, Lighthouse, Observatory; Selected: Lighthouse")
        for column, ascending, expected in (
            (1, True, ["Observatory", "Lighthouse", "Harbor"]),
            (1, False, ["Harbor", "Lighthouse", "Observatory"]),
            (0, False, ["Observatory", "Lighthouse", "Harbor"]),
            (0, True, ["Harbor", "Lighthouse", "Observatory"]),
        ):
            with self.subTest(column=column, ascending=ascending):
                self.connection.messages.clear()
                await self.session.dispatch_event(table.columns[column]._i, "sort",
                                                  {"ci": column, "asc": ascending})
                self.assertEqual([row[0] for row in self.table_rows(view)], expected)
                self.assertEqual(table.sort_column_index, column)
                self.assertEqual(table.sort_ascending, ascending)
                self.assertEqual([row[0] for row in self.table_rows(view) if row[2]],
                                 ["Lighthouse"])
                self.assert_status(view, "recipe-table-result",
                                   "Order: " + ", ".join(expected) + "; Selected: Lighthouse")
        row = next(row for row in table.rows if row.cells[0].content.value == "Lighthouse")
        for payload in (None, "false", "true", 1):
            await self.session.dispatch_event(row._i, "select_change", payload)
            self.assertTrue(row.selected)
        self.connection.messages.clear()
        await self.session.dispatch_event(row._i, "select_change", False)
        self.assertFalse(row.selected)
        self.assert_status(view, "recipe-table-result",
                           "Order: Harbor, Lighthouse, Observatory; Selected: none")

    async def test_section_changes_keep_drafts_table_and_selected_color(self):
        view, _ = await self.mount()
        await self.edit(view, "unfinished draft")
        await self.click(view, "Color")
        picker = self.content(view, "recipe-color-picker")
        self.connection.messages.clear()
        self.session.apply_patch(picker._i, {"color": "#ff4caf50"})
        await self.session.dispatch_event(picker._i, "color_change", "#ff4caf50")
        self.assert_status(view, "recipe-color-result", "Selected color: #4caf50")
        self.assertEqual(self.content(view, "recipe-color-preview").bgcolor, "#4caf50")
        self.assertIn("#4caf50", self.values())
        for color in ("#804caf50", "#ff000000", None, 1):
            await self.session.dispatch_event(picker._i, "color_change", color)
            self.assertEqual(self.content(view, "recipe-color-preview").bgcolor, "#4caf50")
        await self.click(view, "Table")
        table = self.content(view, "recipe-table")
        await self.session.dispatch_event(table.rows[0]._i, "select_change", True)
        await self.click(view, "Loading")
        await self.click(view, "Editor")
        self.assertEqual(self.content(view, "recipe-editor").value, "unfinished draft")
        self.assertEqual(self.table_rows(view)[0], ("Harbor", "5", True))
        self.assertEqual(picker.color, "#4caf50")
        sections = view.controls[0].controls[-4:]
        self.assertEqual([content.visible for content in sections], [True, False, False, False])

    async def test_hidden_and_superseded_row_events_cannot_change_data(self):
        view, _ = await self.mount()
        table = self.content(view, "recipe-table")
        old_row = table.rows[0]
        self.connection.messages.clear()
        await self.session.dispatch_event(old_row._i, "select_change", True)
        self.assertFalse(old_row.selected)
        await self.edit(view, '[{"name":"New","count":1}]')
        await self.click(view, "Apply JSON")
        await self.click(view, "Table")
        await self.session.dispatch_event(old_row._i, "select_change", True)
        self.assertEqual(self.table_rows(view), [("New", "1", False)])
        await self.click(view, "Editor")
        self.connection.messages.clear()
        await self.click(view, "Reset sample")
        self.assertEqual(self.content(view, "recipe-editor").value, DEFAULT_SOURCE)
        self.assertIn(DEFAULT_SOURCE, self.values())
        self.assertEqual([row[0] for row in self.table_rows(view)],
                         [row["name"] for row in DEFAULT_ROWS])

    async def test_pending_completion_and_duplicate_load_use_actual_patches(self):
        ready = asyncio.Event()
        rows = asyncio.get_running_loop().create_future()
        calls = []

        async def loader():
            calls.append(True)
            ready.set()
            return await rows

        view, _ = await self.mount(load_sample=loader)
        await self.click(view, "Loading")
        self.connection.messages.clear()
        await self.click(view, "Load sample")
        await asyncio.wait_for(ready.wait(), 2)
        self.assert_status(view, "recipe-loading-result", "Loading sample")
        self.assertTrue(self.semantic(view, "recipe-loading").visible)
        self.assertTrue(self.button(view, "Load sample").disabled)
        self.assertFalse(self.button(view, "Cancel load").disabled)
        await self.click(view, "Load sample")
        self.assertEqual(calls, [True])
        self.connection.messages.clear()
        rows.set_result([{"name": "Loaded", "count": 8}])
        await self.settle()
        self.assert_status(view, "recipe-loading-result", "Loaded 1 rows")
        self.assertFalse(self.semantic(view, "recipe-loading").visible)
        self.assertFalse(self.button(view, "Load sample").disabled)
        self.assertTrue(self.button(view, "Cancel load").disabled)
        self.assertEqual(self.table_rows(view), [("Loaded", "8", False)])
        self.assertEqual(json.loads(self.content(view, "recipe-editor").value),
                         [{"name": "Loaded", "count": 8}])

    async def test_cancelled_loader_that_ignores_cancellation_cannot_finish_retry(self):
        started = [asyncio.Event(), asyncio.Event()]
        cancelled = asyncio.Event()
        release_old = asyncio.Event()
        release_new = asyncio.Event()
        calls = []

        async def loader():
            index = len(calls)
            calls.append(index)
            started[index].set()
            if index == 0:
                try:
                    await asyncio.Event().wait()
                except asyncio.CancelledError:
                    cancelled.set()
                    await release_old.wait()
                return [{"name": "Obsolete", "count": 0}]
            await release_new.wait()
            return [{"name": "Current", "count": 9}]

        view, _ = await self.mount(load_sample=loader)
        await self.click(view, "Loading")
        await self.click(view, "Load sample")
        await asyncio.wait_for(started[0].wait(), 2)
        self.connection.messages.clear()
        await self.click(view, "Cancel load")
        await asyncio.wait_for(cancelled.wait(), 2)
        self.assert_status(view, "recipe-loading-result", "Loading cancelled")
        self.assertFalse(self.button(view, "Load sample").disabled)
        await self.click(view, "Load sample")
        await asyncio.wait_for(started[1].wait(), 2)
        self.connection.messages.clear()
        release_old.set()
        await self.settle()
        self.assertEqual(self.connection.messages, [])
        self.assertTrue(self.button(view, "Load sample").disabled)
        self.assertTrue(self.semantic(view, "recipe-loading").visible)
        self.assertEqual(self.content(view, "recipe-loading-result").value, "Loading sample")
        release_new.set()
        await self.settle()
        self.assert_status(view, "recipe-loading-result", "Loaded 1 rows")
        self.assertEqual(self.table_rows(view), [("Current", "9", False)])

    async def test_failure_and_invalid_loader_release_busy_and_allow_retry(self):
        for error in (RuntimeError("offline"), [{"name": "Bad", "count": True}],
                      [{"name": "\ud800", "count": 1}]):
            with self.subTest(error=error):
                calls = []

                async def loader():
                    calls.append(True)
                    if len(calls) == 1:
                        if isinstance(error, Exception):
                            raise error
                        return error
                    return [{"name": "Retried", "count": 6}]

                view, _ = await self.mount(load_sample=loader)
                await self.click(view, "Loading")
                self.connection.messages.clear()
                with self.assertLogs(level="ERROR"):
                    await self.click(view, "Load sample")
                    await self.settle()
                self.assert_status(view, "recipe-loading-result",
                                   "Could not load sample. Try again.")
                self.assertFalse(self.button(view, "Load sample").disabled)
                self.assertTrue(self.button(view, "Cancel load").disabled)
                self.assertFalse(self.semantic(view, "recipe-loading").visible)
                self.assertEqual(self.content(view, "recipe-editor").value, DEFAULT_SOURCE)
                await self.click(view, "Load sample")
                await self.settle()
                self.assertEqual(self.table_rows(view), [("Retried", "6", False)])

    async def test_bounded_unicode_and_escaped_loader_rows_round_trip_through_editor(self):
        for prefix in ("🌊" * 79, "\0" * 79):
            with self.subTest(prefix=repr(prefix[:1])):
                rows = [{"name": prefix + str(index), "count": 999} for index in range(8)]

                async def loader():
                    return rows

                view, _ = await self.mount(load_sample=loader)
                await self.click(view, "Loading")
                self.connection.messages.clear()
                await self.click(view, "Load sample")
                await self.settle()
                source = self.content(view, "recipe-editor").value
                self.assertLessEqual(len(source), 4096)
                self.assertEqual(json.loads(source), rows)
                self.assertIn(source, self.values())
                self.assert_status(view, "recipe-loading-result", "Loaded 8 rows")
                await self.click(view, "Editor")
                await self.edit(view, source)
                self.connection.messages.clear()
                await self.click(view, "Apply JSON")
                self.assertEqual(self.table_rows(view),
                                 [(row["name"], "999", False) for row in rows])
                self.assertEqual(self.content(view, "recipe-editor-result").value,
                                 "Applied 8 rows")

    async def test_apply_supersedes_load_and_late_result_cannot_replace_editor_rows(self):
        started = asyncio.Event()
        cancelled = asyncio.Event()
        release = asyncio.Event()

        async def loader():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                await release.wait()
            return [{"name": "Old load", "count": 0}]

        view, _ = await self.mount(load_sample=loader)
        await self.click(view, "Loading")
        await self.click(view, "Load sample")
        await asyncio.wait_for(started.wait(), 2)
        await self.click(view, "Editor")
        await self.edit(view, '[{"name":"Fresh edit","count":3}]')
        await self.click(view, "Apply JSON")
        await asyncio.wait_for(cancelled.wait(), 2)
        self.connection.messages.clear()
        release.set()
        await self.settle()
        self.assertEqual(self.connection.messages, [])
        self.assertEqual(self.table_rows(view), [("Fresh edit", "3", False)])
        self.assertEqual(self.content(view, "recipe-editor-result").value, "Applied 1 rows")
        self.assertEqual(self.content(view, "recipe-loading-result").value, "Loading cancelled")

    async def test_disposal_and_view_identity_guard_reject_late_results_and_callbacks(self):
        for dispose_first in (False, True):
            with self.subTest(dispose=dispose_first):
                started = asyncio.Event()
                release = asyncio.Event()
                cancelled = asyncio.Event()
                identity = {}

                async def loader():
                    started.set()
                    try:
                        await release.wait()
                    except asyncio.CancelledError:
                        cancelled.set()
                        await release.wait()
                    return [{"name": "Detached", "count": 0}]

                view, dispose = await self.mount(load_sample=loader,
                                                is_current=lambda: self.page.views[-1]
                                                is identity["view"])
                identity["view"] = view
                await self.click(view, "Loading")
                await self.click(view, "Load sample")
                await asyncio.wait_for(started.wait(), 2)
                if dispose_first:
                    dispose()
                    dispose()
                    await asyncio.wait_for(cancelled.wait(), 2)
                replacement, _ = await self.mount()
                self.connection.messages.clear()
                await self.click(view, "Editor")
                await self.click(view, "Reset sample")
                await self.click(view, "Cancel load")
                release.set()
                await self.settle()
                self.assertEqual(self.connection.messages, [])
                self.assertEqual(self.content(replacement, "recipe-editor").value, DEFAULT_SOURCE)
                self.assertEqual(self.content(replacement, "recipe-loading-result").value,
                                 "Ready to load sample.")

    async def test_back_uses_only_injected_navigation_and_stops_after_disposal(self):
        back = AsyncMock()
        view, dispose = await self.mount(on_back=back, route="/app/recipes")
        await self.click(view, "Back")
        back.assert_awaited_once()
        dispose()
        await self.click(view, "Back")
        back.assert_awaited_once()
        self.assertEqual(self.page.route, "/")


if __name__ == "__main__":
    unittest.main()
