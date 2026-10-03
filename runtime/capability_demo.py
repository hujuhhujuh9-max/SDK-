"""A device-check page for the fixed Flet/Flutter integration."""

import asyncio
import importlib
import json
import logging
import os
from pathlib import Path


async def open_page(page, route="/capabilities"):
    import flet as ft
    from flet_audio import Audio
    from flet_charts import BarChart, BarChartGroup, BarChartRod
    from flet_local_auth import LocalAuthentication
    from flet_permission_handler import Permission, PermissionHandler
    from flet_secure_storage import SecureStorage
    from flet_video import Video, VideoMedia
    from flet_webview import WebView

    assets = Path(os.environ["FLET_ASSETS_DIR"])
    status = ft.Text("Ready to check device services")
    services = getattr(page, "_runner_capability_services", None)
    if services is None:
        # Services register with the Flet page, not with a View. Keep one set
        # per page so navigation never creates more native players/services.
        audio_loaded = asyncio.Event()
        services = {
            "clipboard": ft.Clipboard(), "preferences": ft.SharedPreferences(),
            "storage": ft.StoragePaths(), "secure": SecureStorage(),
            "auth": LocalAuthentication(), "permissions": PermissionHandler(),
            "picker": ft.FilePicker(), "sharing": ft.Share(),
            "audio_loaded": audio_loaded,
            "audio": Audio(src="runner.wav", volume=0, on_loaded=lambda event: audio_loaded.set()),
            "checking": False, "picking": False,
        }
        page._runner_capability_services = services
    clipboard, preferences, storage, secure, auth, permissions, picker, sharing, audio = (
        services[name] for name in ("clipboard", "preferences", "storage", "secure",
                                    "auth", "permissions", "picker", "sharing", "audio"))
    audio_loaded = services["audio_loaded"]
    web_loaded = asyncio.Event()
    video_loaded = asyncio.Event()
    web = WebView(url=(assets / "webview.html").as_uri(), height=96,
                  on_page_ended=lambda event: web_loaded.set())
    video = Video(playlist=[VideoMedia(resource="runner.mp4")], height=180,
                  volume=0, on_duration_change=lambda event: video_loaded.set())

    def passed(name):
        print("SDK_RUNNER_CAPABILITY_OK name=" + name, flush=True)

    async def checks(event):
        if services["checking"]:
            status.value = "Device checks are already running"
            page.update()
            return
        services["checking"] = True
        button = event.control
        button.disabled = True
        try:
            status.value = "Checking..."
            page.update()
            names = json.loads(Path(__file__).with_name("flet_extensions.json").read_text())
            for name in names:
                importlib.import_module(name.replace("-", "_"))
            passed("python_extensions_19")
            await clipboard.set("runner integration")
            assert await clipboard.get() == "runner integration"
            passed("clipboard")
            from storage_checks import check_persistence
            receipt = await check_persistence(preferences, secure, os.environ["FLET_APP_STORAGE_DATA"])
            print("SDK_RUNNER_STORAGE_CHECK " + json.dumps(receipt, sort_keys=True), flush=True)
            passed("storage_persistence")
            assert await preferences.set("runner.capability", "working")
            assert await preferences.get("runner.capability") == "working"
            passed("preferences")
            await secure.set("runner.capability", "working")
            assert await secure.get("runner.capability") == "working"
            passed("secure_storage")
            from core_capability_checks import check_core_services
            await check_core_services(passed, page)
            support = Path(await storage.get_application_support_directory())
            cache = Path(await storage.get_application_cache_directory())
            temporary = Path(await storage.get_temporary_directory())
            for name, directory in (("DATA", support / "data"), ("CACHE", cache),
                                    ("TEMP", temporary)):
                assert Path(os.environ["FLET_APP_STORAGE_" + name]).resolve() == directory.resolve()
            for folder in {support, cache, temporary}:
                probe = folder / "runner-capability.txt"
                probe.write_text("working")
                assert probe.read_text() == "working"
                probe.unlink()
            passed("storage_paths")
            assert isinstance(await auth.is_device_supported(), bool)
            passed("local_auth_query")
            assert await permissions.get_status(Permission.CAMERA) is not None
            passed("permission_query")
            await asyncio.wait_for(web_loaded.wait(), 20)
            assert await web.get_title() == "Runner WebView asset"
            passed("webview_local_asset")
            await asyncio.wait_for(audio_loaded.wait(), 20)
            try:
                await audio.play()
                assert (await audio.get_duration()).in_milliseconds > 0
            finally:
                await audio.pause()
            passed("audio_local_asset")
            try:
                await video.play()
                await asyncio.wait_for(video_loaded.wait(), 20)
                assert (await video.get_duration()).in_milliseconds > 0
            finally:
                await video.pause()
            passed("video_local_asset")
            status.value = "Device checks passed"
            print("SDK_RUNNER_CAPABILITIES_PASSED", flush=True)
        except Exception:
            logging.exception("SDK_RUNNER_CAPABILITY_ERROR")
            status.value = "Device check failed; see logs"
        finally:
            services["checking"] = False
            button.disabled = False
            page.update()

    async def back(event):
        page.views.pop()
        await page.push_route(page.views[-1].route)

    async def pick(event):
        if services["picking"]:
            status.value = "File picker is already open"
            page.update()
            return
        services["picking"] = True
        button = event.control
        button.disabled = True
        try:
            status.value = "Opening file picker..."
            page.update()
            files = await picker.pick_files()
            from storage_checks import picked_file_receipt
            for selected in files or []:
                receipt = await asyncio.to_thread(picked_file_receipt, selected)
                print("SDK_RUNNER_PICKER_FILE " + json.dumps(receipt, sort_keys=True), flush=True)
                status.value = "Selected " + receipt["name"] + " (" + str(receipt["size"]) + " bytes)"
            if not files:
                status.value = "File selection cancelled"
            print("SDK_RUNNER_PICKER_RETURNED count=" + str(len(files or [])), flush=True)
        except Exception:
            logging.exception("SDK_RUNNER_PICKER_ERROR")
            status.value = "File selection failed; see logs"
        finally:
            services["picking"] = False
            button.disabled = False
            page.update()

    async def share(event):
        result = await sharing.share_files([ft.ShareFile.from_path(str(assets / "runner.svg"))])
        print("SDK_RUNNER_SHARE_RETURNED status=" + result.status.value, flush=True)

    async def request_permission(event):
        result = await permissions.request(Permission.CAMERA)
        print("SDK_RUNNER_PERMISSION_RETURNED status=" + result.value, flush=True)

    def typed(event):
        if event.control.value == "runner_test":
            print("SDK_RUNNER_TEXT_INPUT_PASSED", flush=True)

    run_button = ft.Button("Run checks", on_click=checks)
    pick_button = ft.Button("Open file picker", on_click=pick)
    page.views.append(ft.View(route=route, controls=[ft.Column([
        ft.Text("Capabilities", size=20),
        ft.Row([run_button, ft.Button("Back", on_click=back)]),
        status,
        pick_button,
        ft.Button("Share local file", on_click=share),
        ft.Button("Request camera permission", on_click=request_permission),
        ft.TextField(label="Input probe", on_change=typed),
        ft.Image(src="runner.svg", height=48, semantics_label="Local asset image",
                 error_content=ft.Text("Asset failed")),
        BarChart(groups=[BarChartGroup(x=0, rods=[BarChartRod(to_y=2)]),
                         BarChartGroup(x=1, rods=[BarChartRod(to_y=4)])], height=100),
        web,
        video,
    ], expand=True, scroll=ft.ScrollMode.AUTO)]))
    await page.push_route(route)
    print("SDK_RUNNER_CAPABILITY_VIEW_READY", flush=True)
