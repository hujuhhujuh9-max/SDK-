"""Configured app homes keep the real Flet protocol and native command boundary."""

import asyncio
import importlib.util
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from runtime import app_home, sdk_bridge

FLET_AVAILABLE = importlib.util.find_spec("flet") is not None
ROOT = Path(__file__).resolve().parents[1]

if FLET_AVAILABLE:
    import flet as ft

from test_app_starter_protocol import AppStarterPageCase


class CustomAppLoaderTests(unittest.TestCase):
    def load(self, target=..., **attributes):
        config = types.SimpleNamespace(STARTUP_TEMPLATE="app")
        if target is not ...:
            config.APP_HOME = target
        module = types.ModuleType("custom_home_fixture")
        vars(module).update(attributes)
        with mock.patch.dict(sys.modules, {"runtime.project_config": config,
                                           "custom_home_fixture": module}):
            return sdk_bridge._configured_app_home()

    def test_missing_or_none_setting_preserves_default(self):
        self.assertIsNone(self.load())
        self.assertIsNone(self.load(None))

    def test_top_level_factory_is_resolved(self):
        factory = mock.Mock()
        self.assertIs(self.load("custom_home_fixture:home", home=factory), factory)

    def test_malformed_module_function_is_rejected(self):
        for target in ("", "home", "package.module:home", "module:home:extra", "module:home()", True):
            with self.subTest(target=target), self.assertRaisesRegex(ValueError, "module:function"):
                self.load(target)

    def test_missing_or_noncallable_factory_is_rejected(self):
        for attributes in ({}, {"home": "not a function"}):
            with self.subTest(attributes=attributes), self.assertRaisesRegex(TypeError, "synchronous"):
                self.load("custom_home_fixture:home", **attributes)

    def test_async_factory_is_rejected_before_calling_it(self):
        async def home(*args, **kwargs):
            self.fail("An async factory must not be called")
        with self.assertRaisesRegex(TypeError, "synchronous"):
            self.load("custom_home_fixture:home", home=home)

    def test_missing_module_is_not_replaced_with_default(self):
        with self.assertRaises(ModuleNotFoundError):
            self.load("missing_project_home_fixture:home")


@unittest.skipUnless(FLET_AVAILABLE, "Requires the prepared, pinned Flet source")
class CustomAppProtocolTests(AppStarterPageCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self.config = types.SimpleNamespace(STARTUP_TEMPLATE="app", APP_HOME="my_app:app_home_view")
        self.modules = mock.patch.dict(sys.modules, {
            "runtime.project_config": self.config, "app_home": app_home})
        self.modules.start()
        sys.modules.pop("my_app", None)
        self.paths = mock.patch.object(sys, "path", [str(ROOT / "templates/app/app"), *sys.path])
        self.paths.start()

    async def asyncTearDown(self):
        await self.close_page()
        self.paths.stop()
        self.modules.stop()
        await super().asyncTearDown()

    def assert_custom_home(self):
        self.assertIn("My RenFletPy App", self.visible_text())
        images = [c for c in self.all_controls() if isinstance(c, ft.Image)]
        self.assertEqual([(c.src, c.width, c.height, c.fit) for c in images],
                         [("runner.svg", 180, 48, ft.BoxFit.CONTAIN)])
        semantics = [c.identifier for c in self.all_controls() if isinstance(c, ft.Semantics)]
        self.assertIn("project-home-asset", semantics)

    async def test_template_serializes_heading_and_local_asset_without_services(self):
        await self.open_page("/app?entry=custom")
        self.assert_custom_home()
        self.assertEqual(self.page.views[0].route, "/app?entry=custom")
        self.assertEqual(list(self.page._services._services), [])
        from scripts.flet_protocol import walk
        values = list(walk(self.connection.patches))
        for value in ("My RenFletPy App", "runner.svg", "project-home-asset", "Image"):
            self.assertIn(value, values)
        self.assertIsNone(sdk_bridge.app_session.take_request())

    async def test_module_import_runs_on_flet_loop(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, "loop_home_fixture.py").write_text(
                "import asyncio\n"
                "IMPORTED_LOOP = asyncio.get_running_loop()\n"
                "from my_app import app_home_view\n")
            self.config.APP_HOME = "loop_home_fixture:app_home_view"
            with mock.patch.object(sys, "path", [folder, *sys.path]):
                await self.open_page()
            self.assertIs(sys.modules["loop_home_fixture"].IMPORTED_LOOP, asyncio.get_running_loop())
            self.assert_custom_home()

    async def test_cached_factory_survives_status_reading_and_route_refresh(self):
        await self.open_page()
        sys.modules["my_app"].app_home_view = mock.Mock(
            side_effect=AssertionError("A mounted page must keep its resolved factory"))
        sdk_bridge.app_session.restore(phase="ready", resume_kind="unavailable", showing_story=False,
                                       message="Fresh native status")
        await self.settled()
        self.assert_custom_home()
        self.assertIn("Fresh native status", self.visible_text())
        sdk_bridge.update_reading_status(True, "instant", "Reading choices kept.")
        await self.settled()
        self.assert_custom_home()
        heading = next(c for c in self.all_controls()
                       if isinstance(c, ft.Text) and c.value == "My RenFletPy App")
        self.assertEqual(heading.size, 38)
        await self.navigate("/app?entry=again")
        self.assert_custom_home()

    async def test_non_view_factory_return_is_rejected(self):
        module = types.ModuleType("wrong_home_fixture")
        module.home = mock.Mock(return_value=ft.Text("Not a view"))
        self.config.APP_HOME = "wrong_home_fixture:home"
        with mock.patch.dict(sys.modules, {"wrong_home_fixture": module}):
            with self.assertRaisesRegex(TypeError, "must return a Flet View"):
                await self.open_page()

    async def test_template_preserves_data_routes_and_native_acknowledgement(self):
        await self.open_page()
        old_start = self.button("Start story")
        await self.click("Application records")
        self.assertEqual(self.page.route, "/app/records")
        await old_start.on_click(None)
        self.assertIsNone(sdk_bridge.app_session.take_request())
        await self.navigate("/app")
        self.assert_custom_home()
        await self.click("Start story")
        await self.click("Start story")
        self.assertEqual(self.page.route, "/app")
        command = sdk_bridge.app_session.take_request()
        self.assertEqual(command["action"], "start")
        self.assertIsNone(sdk_bridge.app_session.take_request())
        self.assertTrue(sdk_bridge.app_session.finish(command["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/")
        await self.navigate("/menu")
        await self.click("Return to app")
        self.assertEqual(self.page.route, "/menu")
        returning = sdk_bridge.app_session.take_request()
        self.assertEqual(returning["action"], "return")
        self.assertTrue(sdk_bridge.app_session.finish(returning["command_id"]))
        await self.settled()
        self.assertEqual(self.page.route, "/app")
        self.assert_custom_home()

    async def test_story_mode_does_not_import_configured_home(self):
        self.config.STARTUP_TEMPLATE = "story"
        self.config.APP_HOME = "missing_project_home_fixture:home"
        await self.open_page("/")
        self.assertNotIn("My RenFletPy App", self.visible_text())
        self.assertEqual(self.page.route, "/")
