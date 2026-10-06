"""Run Flet inside Ren'Py's interpreter and share state between both UIs."""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path
from urllib.parse import urlsplit

if __package__:
    from .renfletpy import story
else:
    from renfletpy import story

_lock = threading.Lock()
_count = 0
_thread = None
_loop = None
_task = None
_stopping = threading.Event()
_quitting = threading.Event()
_presentation = "scene"
_story_detach = None
_menu_request = None
_resume_request = None
_save_refresh = None
_save_command = None
_save_status = {"available": False, "busy": False, "message": "No saved game yet."}


def save_status():
    with _lock:
        return dict(_save_status)


def initialize_save_status(available):
    with _lock:
        _save_status["available"] = available
        # The first native timer may run after an early Flet save click. Slot
        # discovery must not cancel that pending command or its busy state.
        if not _save_status["busy"]:
            _save_status["message"] = "Saved game available." if available else "No saved game yet."
    _refresh_save_menu()


def _refresh_save_menu():
    callback = _save_refresh
    if callback is not None:
        callback()


def request_save(action):
    """Flet submits a command; only Ren'Py's thread may execute save/load."""
    global _save_command
    if action not in ("save", "load"):
        raise ValueError("Unknown save action")
    with _lock:
        if _save_status["busy"] or (action == "load" and not _save_status["available"]):
            return False
        _save_command = action
        _save_status.update(busy=True, message="Saving…" if action == "save" else "Loading…")
    _refresh_save_menu()
    return True


def take_save_request():
    global _save_command
    with _lock:
        command, _save_command = _save_command, None
        return command


def update_save_status(available, message):
    global _save_command
    with _lock:
        _save_command = None
        _save_status.update(available=available, busy=False, message=message)
    _refresh_save_menu()


def resume_story():
    callback = _resume_request
    if callback is not None:
        callback()


def request_quit(event=None):
    _quitting.set()


def quitting():
    return _quitting.is_set()


def counter():
    with _lock:
        return _count


def increment():
    global _count
    with _lock:
        _count += 1
        return _count


def presentation():
    with _lock:
        return _presentation


def set_presentation(mode):
    global _presentation
    if mode not in ("scene", "interlude", "page", "diagnostics"):
        raise ValueError("Unknown runner presentation")
    with _lock:
        _presentation = mode
    if getattr(sys.modules.get("renpy"), "android", False):
        from jnius import autoclass, cast
        activity = cast("org.sdk.runner.RunnerActivity",
                        autoclass("org.renpy.android.PythonSDLActivity").mActivity)
        activity.setRunnerPresentation(mode)
    print(f"SDK_RUNNER_PRESENTATION mode={mode} pid={os.getpid()}", flush=True)


def open_menu():
    """Queue a shared menu from a Ren'Py screen action, on Flet's own loop."""
    if _menu_request is not None:
        _menu_request()


async def _page(page):
    global _story_detach, _menu_request, _resume_request, _save_refresh
    import flet as ft
    if __package__:
        from . import story_ui
    else:
        import story_ui

    page.theme_mode = ft.ThemeMode.DARK
    page.theme = ft.Theme(color_scheme_seed="#b9d7de")
    loop = asyncio.get_running_loop()

    async def navigate(route):
        await page.push_route(route)

    def request_menu():
        if not loop.is_closed():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(navigate("/menu")))

    def request_resume():
        if not loop.is_closed():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(navigate("/")))

    def render_save_menu():
        if detach is None:
            return
        for index, view in enumerate(page.views):
            if urlsplit(view.route).path == "/menu":
                menu = story_ui.menu_view(navigate, request_quit, save_status(), request_save)
                menu.route = view.route
                page.views[index] = menu
                page.update()
                break

    def save_changed():
        if not loop.is_closed():
            loop.call_soon_threadsafe(render_save_menu)

    value = ft.Text(f"Count: {counter()}", size=24)

    def clicked(event):
        value.value = f"Count: {increment()}"
        page.update()

    def diagnostics_controls():
        return [ft.Text("Connected", size=24), value, ft.Row([
            ft.Button("Increment", on_click=clicked),
            ft.Button("Capabilities", on_click=story_ui.route_handler(navigate, "/capabilities")),
            ft.Button("Return to story", on_click=story_ui.route_handler(navigate, "/")),
            ft.Button("Quit runner", on_click=request_quit),
        ], wrap=True)]

    async def popped(event):
        if len(page.views) > 1:
            page.views.pop()
            await page.push_route(page.views[-1].route)
        else:
            await navigate("/menu")

    page.on_view_pop = popped
    last_dialogue = None
    async def render_route(route):
        nonlocal last_dialogue
        path = urlsplit(route).path
        diagnostic = path in ("/diagnostics", "/capabilities")
        base_path = "/diagnostics" if diagnostic else "/"
        if urlsplit(page.views[0].route).path != base_path:
            page.views[:] = [ft.View(route=base_path)]
        root = page.views[0]
        root.bgcolor = "#101b2b" if diagnostic else "transparent"
        root.padding = 10 if diagnostic else 12
        if diagnostic:
            root.controls = diagnostics_controls()
        else:
            last_dialogue = story.current()
            root.controls = story_ui.dialogue_controls(navigate, last_dialogue)
        if path == "/capabilities":
            set_presentation("diagnostics")
            if urlsplit(page.views[-1].route).path != path:
                from capability_demo import open_page
                await open_page(page, route=route)
            else:
                page.views[-1].route = route
        elif path in ("/menu", "/history", "/restart"):
            set_presentation("page")
            page.views[:] = [root, story_ui.menu_view(navigate, request_quit, save_status(), request_save)]
            if path == "/history":
                page.views.append(story_ui.transcript_view(navigate))
            elif path == "/restart":
                page.views.append(story_ui.restart_view(navigate))
            page.views[-1].route = route
        else:
            page.views[:] = [root]
            root.route = route if path in ("", "/", "/diagnostics") else base_path
            set_presentation("diagnostics" if diagnostic else
                             "interlude" if last_dialogue is not None else "scene")
        page.update()

    async def route_changed(event):
        await render_route(event.route)

    page.on_route_change = route_changed

    def render_story():
        nonlocal last_dialogue
        dialogue = story.current()
        if detach is None or dialogue == last_dialogue or urlsplit(page.views[0].route).path != "/":
            return
        last_dialogue = dialogue
        page.views[0].controls = story_ui.dialogue_controls(navigate, dialogue)
        if len(page.views) == 1:
            set_presentation("interlude" if dialogue is not None else "scene")
        page.update()

    def changed():
        if not loop.is_closed():
            loop.call_soon_threadsafe(render_story)

    detach = None
    async def connected(event=None):
        nonlocal detach, last_dialogue
        global _story_detach, _menu_request, _resume_request, _save_refresh
        if detach is not None:
            detach()
        if _story_detach is not None:
            _story_detach()
        detach = story.subscribe(changed)
        _story_detach = detach
        _menu_request = request_menu
        _resume_request = request_resume
        _save_refresh = save_changed
        if event is not None:
            last_dialogue = object()
        render_story()

    async def disconnected(event):
        nonlocal detach
        global _story_detach, _menu_request, _resume_request, _save_refresh
        if detach is not None:
            detach()
            if _story_detach is detach:
                _story_detach = None
            detach = None
        if _menu_request is request_menu:
            _menu_request = None
        if _resume_request is request_resume:
            _resume_request = None
        if _save_refresh is save_changed:
            _save_refresh = None

    page.on_connect = connected
    page.on_disconnect = page.on_close = disconnected
    # Flet registers the initial route in page state without a route_change event.
    await render_route(page.route)
    await connected()
    print(f"SDK_RUNNER_FLET_READY pid={os.getpid()}", flush=True)


def start():
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stopping.clear()
    _quitting.clear()
    private = Path(os.environ["ANDROID_PRIVATE"])
    cache = Path(os.environ.get("ANDROID_CACHE", private.parent / "cache"))
    os.environ["FLET_ASSETS_DIR"] = str(private / "flet-assets")
    for name, folder in [("DATA", private / "data"), ("CACHE", cache), ("TEMP", cache)]:
        folder.mkdir(parents=True, exist_ok=True)
        os.environ["FLET_APP_STORAGE_" + name] = str(folder)
    os.environ["FLET_PLATFORM"] = "android"
    os.environ["FLET_SERVER_UDS_PATH"] = os.path.join(os.environ["ANDROID_PRIVATE"], "flet.sock")
    os.environ["MSGPACK_PUREPYTHON"] = "1"
    os.environ.pop("FLET_DART_BRIDGE_PORT", None)

    async def serve():
        global _loop, _task, _story_detach, _menu_request, _resume_request, _save_refresh
        import flet as ft
        _loop = asyncio.get_running_loop()
        _task = asyncio.current_task()
        try:
            if _stopping.is_set():
                return
            executor = None
            if getattr(sys.modules.get("renpy"), "android", False):
                from android_jni_executor import AppClassLoaderExecutor
                executor = AppClassLoaderExecutor(thread_name_prefix="flet-native")
                # Page.run_thread, synchronous pubsub and asyncio.to_thread share
                # the pool. Flet cancels queued work; asyncio.run joins workers.
                _loop.set_default_executor(executor)
            await ft.run_async(_page, view=None, assets_dir=os.environ["FLET_ASSETS_DIR"],
                               executor=executor)
        except asyncio.CancelledError:
            pass
        finally:
            if _story_detach is not None:
                _story_detach()
                _story_detach = None
            _menu_request = None
            _resume_request = None
            _save_refresh = None
            _loop = None
            _task = None

    def worker():
        try:
            asyncio.run(serve())
        except Exception:
            logging.exception("Flet startup failed in the Ren'Py interpreter")

    if getattr(sys.modules.get("renpy"), "android", False):
        from android_jni import app_loader_callback
        worker = app_loader_callback(worker)
    _thread = threading.Thread(target=worker, name="flet-ui", daemon=True)
    _thread.start()


def stop():
    _stopping.set()
    loop, task, thread = _loop, _task, _thread
    if loop is not None and task is not None:
        loop.call_soon_threadsafe(task.cancel)
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Flet did not stop before Ren'Py shutdown")
    print("SDK_RUNNER_FLET_STOPPED", flush=True)
