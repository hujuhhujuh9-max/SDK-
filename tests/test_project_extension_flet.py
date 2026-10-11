"""Use the pinned Flet encoder and dispatch for the project's actual wire API."""

import asyncio
import importlib
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build_android as build
from scripts.flet_protocol import walk
from test_app_home_flet import AppConnection, control_tree
import test_project_extensions as extension_fixtures


FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
if FLET_AVAILABLE:
    import flet as ft
    from flet.controls.context import _context_page
    from flet.messaging.session import Session


@unittest.skipUnless(FLET_AVAILABLE, "Requires prepared pinned Flet")
class ProjectExtensionFletTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        project = extension_fixtures.example.materialize(self.root / "project")
        self.private = self.root / "runtime"
        build.stage_runtime(self.private, "app", project)
        sys.path.insert(0, str(self.private))
        self.addCleanup(sys.path.remove, str(self.private))
        self.pulse = importlib.import_module("project_pulse")
        self.app = importlib.import_module("my_app")
        self.addCleanup(sys.modules.pop, "project_pulse", None)
        self.addCleanup(sys.modules.pop, "my_app", None)
        self.connection = AppConnection()
        self.session = Session(self.connection)
        self.page = self.session.page
        self.token = _context_page.set(self.page)
        self.connection.encode(self.session.get_page_patch())

    async def asyncTearDown(self):
        _context_page.reset(self.token)
        self.session.close()
        await asyncio.sleep(0)

    async def settle(self):
        for _ in range(3):
            await asyncio.sleep(0)

    async def test_real_encoder_typed_event_and_plain_model_survive_control_reconstruction(self):
        state = {"value": 25.0, "intensity": 0.7, "running": True, "mounted": True,
                 "draft": "Working note", "changes": 0, "lifecycle": "Waiting"}
        ctx = SimpleNamespace(state=state, page=self.page, route="/app/pulse",
                              is_current=lambda: True, back=lambda event: None,
                              start_story=lambda: None, resume_story=lambda: None)
        first = self.app.pulse_screen(ctx)
        self.page.views[:] = [first]
        self.page.update()
        dial = next(control for control in control_tree(first) if isinstance(control, self.pulse.PulseDial))
        encoded = list(walk(self.connection.messages))
        self.assertIn("project_pulse.PulseDial", encoded)
        self.assertIn("Working note", encoded)
        with patch("builtins.print") as receipt:
            await self.session.dispatch_event(dial._i, "change", {"value": 67.5, "source": "tap"})
            await self.settle()
            await self.session.dispatch_event(dial._i, "lifecycle", {"phase": "paused", "running": False})
            await self.settle()
        events = [json.loads(call.args[1]) for call in receipt.call_args_list
                  if call.args[0] == "SDK_CAP_PULSE_EVENT"]
        self.assertEqual([event["phase"] for event in events], ["selection", "paused"])
        self.assertEqual(events[0], {"phase": "selection", "running": True, "value": 67.5,
                                   "intensity": 0.7, "changes": 1, "mounted": True,
                                   "pid": os.getpid()})
        self.assertFalse(events[1]["running"])
        self.assertTrue(state["running"])
        self.assertEqual(state["value"], 67.5)
        self.assertEqual(state["changes"], 1)
        self.assertEqual(dial.value, 67.5)
        self.assertEqual(state["lifecycle"], "paused: paused")
        # The SDK keeps this dictionary when a native story hides/removes Flet.
        self.page.views[:] = []
        self.page.update()
        rebuilt = self.app.pulse_screen(ctx)
        self.page.views[:] = [rebuilt]
        self.page.update()
        replacement = next(control for control in control_tree(rebuilt) if isinstance(control, self.pulse.PulseDial))
        self.assertIsNot(replacement, dial)
        self.assertEqual(replacement.value, 67.5)
        self.assertEqual(next(control for control in control_tree(rebuilt) if isinstance(control, ft.TextField)).value, "Working note")
        self.assertEqual(json.loads(json.dumps(state)), state)
        ctx.is_current = lambda: False
        with patch("builtins.print") as receipt:
            await self.session.dispatch_event(replacement._i, "change", {"value": 81, "source": "tap"})
            await self.session.dispatch_event(replacement._i, "lifecycle", {"phase": "resumed", "running": True})
            await self.settle()
        receipt.assert_not_called()
        self.assertEqual(state["value"], 67.5)

    async def test_invalid_game_properties_fail_before_serialization(self):
        for properties in ({"value": float("nan")}, {"value": -1}, {"intensity": 2},
                           {"period_ms": 10}, {"running": "yes"}):
            with self.subTest(properties=properties):
                dial = self.pulse.PulseDial(**properties)
                with self.assertRaises(ValueError):
                    dial.before_update()


if __name__ == "__main__":
    unittest.main()
