"""Run Flet inside Ren'Py's interpreter and share state between both UIs."""

import asyncio
import logging
import os
import sys
import threading
from pathlib import Path

_lock = threading.Lock()
_count = 0
_thread = None
_loop = None
_task = None
_stopping = threading.Event()
_quitting = threading.Event()


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


async def _page(page):
    import flet as ft

    value = ft.Text(f"Count: {counter()}", size=24)

    def clicked(event):
        value.value = f"Count: {increment()}"
        page.update()

    async def capabilities(event):
        from capability_demo import open_page
        await open_page(page)

    async def popped(event):
        if len(page.views) > 1:
            page.views.pop()
            await page.push_route(page.views[-1].route)

    page.on_view_pop = popped
    async def route_changed(event):
        if event.route == "/capabilities" and page.views[-1].route != "/capabilities":
            await capabilities(event)

    page.on_route_change = route_changed
    page.controls = [ft.Text("Connected", size=24), value, ft.Row([
        ft.Button("Increment", on_click=clicked),
        ft.Button("Capabilities", on_click=capabilities),
        ft.Button("Quit runner", on_click=request_quit),
    ], wrap=True)]
    page.update()
    # Flet registers the initial route in page state without a route_change event.
    if page.route == "/capabilities" and page.views[-1].route != "/capabilities":
        await capabilities(None)
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
    for name, folder in [("DATA", private / "data"), ("CACHE", cache), ("TEMP", cache / "tmp")]:
        folder.mkdir(parents=True, exist_ok=True)
        os.environ["FLET_APP_STORAGE_" + name] = str(folder)
    os.environ["FLET_PLATFORM"] = "android"
    os.environ["FLET_SERVER_UDS_PATH"] = os.path.join(os.environ["ANDROID_PRIVATE"], "flet.sock")
    os.environ["MSGPACK_PUREPYTHON"] = "1"
    os.environ.pop("FLET_DART_BRIDGE_PORT", None)

    async def serve():
        global _loop, _task
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
