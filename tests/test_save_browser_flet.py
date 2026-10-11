"""Real pinned-Flet events across the shared named-save/browser boundary."""

import unittest
from types import SimpleNamespace

from runtime import app_session, sdk_bridge
from test_app_starter_protocol import AppStarterPageCase, FLET_AVAILABLE

if FLET_AVAILABLE:
    import flet as ft


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class SaveBrowserFletTests(AppStarterPageCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        sdk_bridge._stopping.clear()
        sdk_bridge._slot_status.update(ready=False, slots=(), revision=sdk_bridge._slot_status["revision"] + 1)
        app_session.session.restore(phase="active", resume_kind="live", showing_story=False)
        self.row = {"slot": "renfletpy-manual-" + "a" * 32, "name": "Before the choice",
                    "mtime": 10, "scene": "The lighthouse", "fingerprint": "a" * 64, "loadable": True}

    async def browser(self):
        await self.open_page("/app/saves")
        self.assertEqual(sdk_bridge.take_save_request(), "list")
        sdk_bridge.publish_save_slots((self.row,))
        sdk_bridge.update_save_status(False, "Saved games loaded.")
        await self.settled()
        return self.page.views[-1]

    def field(self):
        return next(control for control in self.all_controls()
                    if isinstance(control, ft.TextField) and control.label == "Save name")

    async def test_create_validation_busy_and_failed_write_preserve_name_draft(self):
        await self.browser()
        field = self.field()
        self.transport.apply_patch(field._i, {"value": ""})
        await self.click("Create save")
        self.assertIsNotNone(field.error)
        self.assertIsNone(sdk_bridge.take_save_request())
        self.transport.apply_patch(field._i, {"value": "Mira’s lighthouse"})
        await self.click("Create save")
        self.assertIsNone(field.error)
        self.assertEqual(sdk_bridge.take_save_request(), {"action": "create", "name": "Mira’s lighthouse"})
        self.assertTrue(self.button("Create save").disabled)
        await self.click("Create save")
        self.assertIsNone(sdk_bridge.take_save_request())
        sdk_bridge.update_save_status(False, "Could not create. Please try again.")
        await self.settled()
        self.assertEqual(field.value, "Mira’s lighthouse")
        self.assertFalse(self.button("Create save").disabled)
        self.assertIn("Could not create. Please try again.", self.visible_text())

    async def test_load_overwrite_and_delete_need_confirmation_and_reject_old_controls(self):
        await self.browser()
        for action, label in (("load", "Load"), ("overwrite", "Overwrite"), ("delete", "Delete")):
            await self.click(label)
            self.assertIsNone(sdk_bridge.take_save_request())
            await self.click("Cancel")
            self.assertIsNone(sdk_bridge.take_save_request())
            await self.click(label)
            confirmed = self.button({"load": "Load save", "overwrite": "Overwrite save",
                                     "delete": "Delete save"}[action])
            await self.click(confirmed.content)
            self.assertEqual(sdk_bridge.take_save_request(), {"action": action, "slot": self.row["slot"],
                                                            "expected": self.row["fingerprint"]})
            sdk_bridge.update_save_status(False, "Operation finished.")
            await self.settled()
        await self.click("Delete")
        old = self.button("Delete save")
        sdk_bridge.publish_save_slots((dict(self.row, fingerprint="b" * 64),))
        await self.settled()
        await old.on_click(None)
        self.assertIsNone(sdk_bridge.take_save_request())

    async def test_query_navigation_keeps_draft_and_disconnected_controls_are_retired(self):
        view = await self.browser()
        field = self.field()
        self.transport.apply_patch(field._i, {"value": "Keep this draft"})
        old_create = self.button("Create save")
        await self.navigate("/app/saves?source=menu")
        self.assertIs(self.page.views[-1], view)
        self.assertEqual(self.field().value, "Keep this draft")
        await self.page.on_disconnect(None)
        await old_create.on_click(None)
        self.assertIsNone(sdk_bridge.take_save_request())
        await self.page.on_connect(SimpleNamespace())
        await self.settled()
        self.assertIsNot(self.page.views[-1], view)
        self.assertEqual(sdk_bridge.take_save_request(), "list")

    async def test_automatic_recovery_preserves_browser_and_explicit_named_load_returns_to_story(self):
        await self.browser()
        sdk_bridge.resume_story()
        await self.settled()
        self.assertEqual(self.page.route, "/app/saves")
        await self.click("Load")
        await self.click("Load save")
        sdk_bridge.take_save_request()
        self.assertTrue(sdk_bridge.mark_save_restored())
        app_session.session.restore(phase="active", resume_kind="live", showing_story=True)
        sdk_bridge.update_save_status(False, "Loaded saved game.")
        sdk_bridge.resume_story(manual_load=True)
        await self.settled()
        self.assertEqual(self.page.route, "/")

    async def test_opening_browser_during_quick_save_reads_slots_after_it_finishes(self):
        self.assertTrue(sdk_bridge.request_save("save"))
        self.assertEqual(sdk_bridge.take_save_request(), "save")
        await self.open_page("/app/saves")
        self.assertIsNone(sdk_bridge.take_save_request())
        sdk_bridge.update_save_status(True, "Saved.")
        await self.settled()
        self.assertEqual(sdk_bridge.take_save_request(), "list")
        sdk_bridge.publish_save_slots((self.row,))
        sdk_bridge.update_save_status(True, "Saved games loaded.")
        await self.settled()
        self.assertIn(self.row["name"], self.visible_text())
        self.assertIsNone(sdk_bridge.take_save_request())


if __name__ == "__main__":
    unittest.main()
