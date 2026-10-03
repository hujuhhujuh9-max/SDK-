"""Check capability-page concurrency and cleanup with host-independent services."""

import asyncio
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from runtime.capability_demo import open_page


class Control:
    def __init__(self, *args, **kwargs):
        self.value = args[0] if args else None
        self.controls = kwargs.pop("controls", args[0] if args and isinstance(args[0], list) else [])
        self.disabled = False
        self.__dict__.update(kwargs)


def module(name, **members):
    result = types.ModuleType(name)
    result.__dict__.update(members)
    return result


class CapabilityDemoTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.clipboard = types.SimpleNamespace(set=AsyncMock(), get=AsyncMock(return_value="runner integration"))
        preferences = types.SimpleNamespace(set=AsyncMock(return_value=True), get=AsyncMock(return_value="working"))
        secure = types.SimpleNamespace(set=AsyncMock(), get=AsyncMock(return_value="working"))
        storage = types.SimpleNamespace(
            get_application_support_directory=AsyncMock(return_value="/fake/support"),
            get_application_cache_directory=AsyncMock(return_value="/fake/cache"),
            get_temporary_directory=AsyncMock(return_value="/fake/cache"))
        duration = types.SimpleNamespace(in_milliseconds=500)
        self.audio = types.SimpleNamespace(play=AsyncMock(), pause=AsyncMock(),
                                           get_duration=AsyncMock(return_value=duration))
        self.video = types.SimpleNamespace(play=AsyncMock(), pause=AsyncMock(),
                                           get_duration=AsyncMock(return_value=duration))
        web = types.SimpleNamespace(get_title=AsyncMock(return_value="Runner WebView asset"))

        def audio(**kwargs):
            kwargs["on_loaded"](None)
            return self.audio

        def video(**kwargs):
            kwargs["on_duration_change"](None)
            return self.video

        def webview(**kwargs):
            kwargs["on_page_ended"](None)
            return web

        flet = module("flet", Text=Control, Button=Control, Row=Control, Column=Control,
                      View=Control, TextField=Control, Image=Control,
                      ScrollMode=types.SimpleNamespace(AUTO="auto"),
                      Clipboard=lambda: self.clipboard, SharedPreferences=lambda: preferences,
                      StoragePaths=lambda: storage, FilePicker=Control, Share=Control)
        self.core = AsyncMock()
        modules = {
            "flet": flet,
            "flet_audio": module("flet_audio", Audio=audio),
            "flet_charts": module("flet_charts", BarChart=Control, BarChartGroup=Control, BarChartRod=Control),
            "flet_local_auth": module("flet_local_auth", LocalAuthentication=lambda: types.SimpleNamespace(
                is_device_supported=AsyncMock(return_value=False))),
            "flet_permission_handler": module("flet_permission_handler",
                Permission=types.SimpleNamespace(CAMERA="camera"),
                PermissionHandler=lambda: types.SimpleNamespace(get_status=AsyncMock(return_value="denied"))),
            "flet_secure_storage": module("flet_secure_storage", SecureStorage=lambda: secure),
            "flet_video": module("flet_video", Video=video, VideoMedia=Control),
            "flet_webview": module("flet_webview", WebView=webview),
            "core_capability_checks": module("core_capability_checks", check_core_services=self.core),
        }
        self.enterContext(patch.dict(sys.modules, modules))
        self.enterContext(patch.dict("os.environ", {
            "FLET_ASSETS_DIR": "/fake/assets", "FLET_APP_STORAGE_DATA": "/fake/support/data",
            "FLET_APP_STORAGE_CACHE": "/fake/cache", "FLET_APP_STORAGE_TEMP": "/fake/cache"}))
        self.enterContext(patch.object(Path, "read_text", autospec=True,
                                      side_effect=lambda path: "[]" if path.name == "flet_extensions.json" else "working"))
        self.enterContext(patch.object(Path, "write_text"))
        self.enterContext(patch.object(Path, "unlink"))
        self.printed = self.enterContext(patch("builtins.print"))
        self.page = types.SimpleNamespace(views=[Control(route="/")], update=Mock(), push_route=AsyncMock())

    async def asyncSetUp(self):
        await open_page(self.page)
        controls = self.page.views[-1].controls[0].controls
        self.button = controls[1].controls[0]
        self.status = controls[2]

    async def test_repeated_click_is_ignored_until_checks_finish(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def block(value):
            entered.set()
            await release.wait()

        self.clipboard.set.side_effect = block
        first = asyncio.create_task(self.button.on_click(None))
        try:
            await asyncio.wait_for(entered.wait(), 5)
            self.assertTrue(self.button.disabled)
            await self.button.on_click(None)
            self.assertEqual(self.clipboard.set.await_count, 1)
            release.set()
            await asyncio.wait_for(first, 5)
        finally:
            release.set()
            if not first.done():
                first.cancel()
                await asyncio.gather(first, return_exceptions=True)
        self.assertFalse(self.button.disabled)
        self.assertEqual(self.status.value, "Device checks passed")
        self.core.assert_awaited_once()
        self.assertIs(self.core.await_args.args[1], self.page)
        self.audio.pause.assert_awaited_once()
        self.video.pause.assert_awaited_once()

    async def test_audio_failure_pauses_and_allows_retry(self):
        self.audio.get_duration.side_effect = RuntimeError("audio duration failed")
        with self.assertLogs(level="ERROR"):
            await self.button.on_click(None)
        self.audio.pause.assert_awaited_once()
        self.video.play.assert_not_awaited()
        self.assertFalse(self.button.disabled)
        self.assertEqual(self.status.value, "Device check failed; see logs")
        self.assertFalse(any(call.args and call.args[0] == "SDK_RUNNER_CAPABILITIES_PASSED"
                             for call in self.printed.call_args_list))
        self.audio.get_duration.side_effect = None
        await self.button.on_click(None)
        self.assertEqual(self.status.value, "Device checks passed")
        self.assertFalse(self.button.disabled)
        self.assertEqual(self.audio.pause.await_count, 2)
        self.video.pause.assert_awaited_once()

    async def test_video_failure_pauses_both_media_controls(self):
        self.video.get_duration.side_effect = RuntimeError("video duration failed")
        with self.assertLogs(level="ERROR"):
            await self.button.on_click(None)
        self.audio.pause.assert_awaited_once()
        self.video.pause.assert_awaited_once()
        self.assertFalse(self.button.disabled)
        self.assertEqual(self.status.value, "Device check failed; see logs")

    async def test_failed_play_still_pauses_audio(self):
        self.audio.play.side_effect = RuntimeError("audio play failed")
        with self.assertLogs(level="ERROR"):
            await self.button.on_click(None)
        self.audio.pause.assert_awaited_once()
        self.assertFalse(self.button.disabled)

    async def test_cancellation_releases_guard_and_pauses_running_media(self):
        entered = asyncio.Event()

        async def block():
            entered.set()
            await asyncio.Future()

        self.video.get_duration.side_effect = block
        first = asyncio.create_task(self.button.on_click(None))
        await asyncio.wait_for(entered.wait(), 5)
        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        self.video.pause.assert_awaited_once()
        self.assertFalse(self.button.disabled)
        self.video.get_duration.side_effect = None
        await self.button.on_click(None)
        self.assertEqual(self.status.value, "Device checks passed")
        self.assertEqual(self.video.pause.await_count, 2)


if __name__ == "__main__":
    unittest.main()
