"""Run Flet inside Ren'Py's interpreter and share state between both UIs."""

import asyncio
import logging
import os
import threading

_lock = threading.Lock()
_count = 0
_thread = None
_loop = None
_task = None
_stopping = threading.Event()


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

    page.controls = [ft.Text("Connected", size=24), value, ft.Button("Increment", on_click=clicked)]
    page.update()
    print(f"SDK_RUNNER_FLET_READY pid={os.getpid()}", flush=True)


def start():
    global _thread
    if _thread is not None and _thread.is_alive():
        return
    _stopping.clear()
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
            await ft.run_async(_page, view=None, assets_dir=None)
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
