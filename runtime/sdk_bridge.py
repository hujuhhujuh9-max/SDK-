"""Run Flet inside Ren'Py's interpreter and share state between both UIs."""

import asyncio
import copy
import json
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
_page_owner = None
_menu_request = None
_resume_request = None
_save_refresh = None
_save_command = None
_save_status = {"available": False, "busy": False, "message": "No saved game yet."}
_transcript = ()
_history_refresh = None
_reading_refresh = None
_reading_command = None
_reading_status = {"large_text": False, "text_speed": "instant", "busy": False,
                   "message": "These choices are kept for your next visit."}
_story_sequence = 0
_story_revision = 0
_story_command = None
_story_pending = None
_story_refresh = None
_story_error = None
_story_loading = False
_story_config = {"story_id": "before-the-first-light", "story_title": "Before the First Light", "native_host": False}
_story_status = {"story_id": None, "session_id": None, "state": "idle",
                 "return_route": "/app", "busy": False, "request_id": None,
                 "action": None, "message": "Choose a story to begin.", "result": None}
APP_ROUTES = ("/app", "/app/story", "/app/records", "/app/settings",
              "/app/story/start", "/app/story/cancel", "/app/story/result")
STORY_ROUTES = ("", "/", "/menu", "/history", "/restart", "/settings")
CONFIRMED_STATES = {"start": "active", "resume": "active", "return": "suspended",
                    "cancel": "cancelled", "native_return": "suspended",
                    "completed": "completed", "cancelled": "cancelled"}


def story_status():
    """Return confirmed native state, plus the pending operation, as plain data."""
    with _lock:
        return copy.deepcopy(_story_status)


def configure_app_story(story_id, story_title, *, initializing=False, native_host=False):
    """Bind an optional project's native story before accepting app commands."""
    global _story_revision, _story_loading
    _validate_story_id(story_id)
    if not isinstance(story_title, str) or not story_title.strip():
        raise ValueError("A story title is required")
    if type(initializing) is not bool or type(native_host) is not bool:
        raise ValueError("Story initialization must be a boolean")
    with _lock:
        if _story_pending is not None or _story_status["state"] in ("active", "suspended"):
            raise ValueError("Cannot replace a live story's configuration")
        _story_config.update(story_id=story_id, story_title=story_title, native_host=native_host)
        _story_loading = initializing
        _story_revision += 1
    _refresh_story_status()


def app_story_status():
    """C's view contract; raw native JSON remains available in story_status()."""
    with _lock:
        status = copy.deepcopy(_story_status)
        revision, error, config, loading = _story_revision, _story_error, dict(_story_config), _story_loading
        busy = status["busy"] or _save_status["busy"] or _reading_status["busy"]
        busy = busy or _quitting.is_set() or story.restarting()
    result = None
    if status["state"] in ("completed", "cancelled"):
        raw = status["result"]
        values = raw if type(raw) is dict else {} if raw is None else {"Result": raw}
        result = {"status": status["state"], "story_title": config["story_title"],
                  "summary": status["message"], "values": {
                      key: value if type(value) in (str, int, float, bool, type(None))
                      else json.dumps(value, ensure_ascii=False)
                      for key, value in values.items()}}
    return {"revision": revision, "loading": loading, "busy": busy,
            "active": status["state"] == "active",
            "resume_available": status["state"] in ("active", "suspended"),
            "resume_reason": "No live story to resume.", "message": status["message"],
            "error": error, "result": result, "story_title": config["story_title"]}


def _refresh_story_status(command=None):
    callback = _story_refresh
    if callback is not None:
        callback(command)


def _validate_story_id(story_id):
    if not isinstance(story_id, str) or not story_id.strip():
        raise ValueError("A story ID is required")


def _validate_app_route(return_route):
    if not isinstance(return_route, str):
        raise ValueError("Story return route must be an app route")
    route = urlsplit(return_route)
    if route.scheme or route.netloc or route.path not in APP_ROUTES:
        raise ValueError("Story return route must be an app route")


def request_story(action, story_id="before-the-first-light", *, return_route="/app",
                  expected_revision=None, replace=False):
    """Submit plain data; only a confirmed view can replace a live story."""
    global _story_sequence, _story_revision, _story_command, _story_pending, _story_error
    if action not in ("start", "resume", "return", "cancel"):
        raise ValueError("Unknown story action")
    if type(replace) is not bool or (replace and (action != "start" or expected_revision is None)):
        raise ValueError("Replacing a story requires a revision-checked Start")
    _validate_story_id(story_id)
    _validate_app_route(return_route)
    with _lock:
        if expected_revision is not None and (type(expected_revision) is not int
                                               or expected_revision != _story_revision):
            return None
        if (_story_loading or _story_pending is not None or _save_status["busy"] or _reading_status["busy"]
                or _quitting.is_set() or story.restarting()):
            return None
        state = _story_status["state"]
        if action == "start":
            if state in ("active", "suspended") and not replace:
                return None
        elif (_story_status["story_id"] != story_id or state not in ("active", "suspended")
              or (action == "return" and state != "active")):
            return None
        _story_sequence += 1
        request_id = _story_sequence
        command = {"request_id": request_id, "session_id": request_id if action == "start"
                   else _story_status["session_id"], "action": action,
                   "story_id": story_id, "return_route": return_route}
        _story_pending = _story_command = command
        _story_revision += 1
        _story_error = None
        _story_status.update(busy=True, request_id=request_id, action=action,
                             message={"start": "Starting story…", "resume": "Resuming story…",
                                      "return": "Returning to app…", "cancel": "Cancelling story…"}[action])
    _refresh_story_status()
    _refresh_save_menu()
    return request_id


def take_story_command():
    """Consume once without releasing busy or losing the confirmation identity."""
    global _story_command
    with _lock:
        command, _story_command = _story_command, None
        return dict(command) if command is not None else None


def confirm_story_command(request_id, *, success, message="", navigate=True):
    """Confirm a consumed operation. Old or duplicate replies have no effect."""
    global _story_pending, _story_revision, _story_error
    if type(success) is not bool or type(navigate) is not bool or not isinstance(message, str):
        raise ValueError("Story confirmation requires a boolean and a text message")
    with _lock:
        command = _story_pending
        if (type(request_id) is not int or command is None or _story_command is not None
                or command["request_id"] != request_id):
            return False
        _story_pending = None
        _story_revision += 1
        _story_error = None if success else message or "Could not change story. Try again."
        if success:
            _story_status.update(story_id=command["story_id"], session_id=command["session_id"],
                                 return_route=command["return_route"], result=None,
                                 state={"return": "suspended", "cancel": "cancelled"}.get(command["action"], "active"))
        _story_status.update(busy=False, action=None,
                             message=message or ("Story ready." if success else "Could not change story. Try again."))
    _refresh_story_status(command if success and navigate else None)
    _refresh_save_menu()
    return True


def _plain_result(value):
    # Validate recursively so tuples, objects, non-string keys and NaN do not
    # enter the command/status contract or a caller's saveable result data.
    def validate(item):
        if type(item) in (str, bool, int, float, type(None)):
            return
        if type(item) is list:
            for child in item:
                validate(child)
        elif type(item) is dict and all(type(key) is str for key in item):
            for child in item.values():
                validate(child)
        else:
            raise ValueError("Story result must contain only JSON data")
    try:
        validate(value)
        return json.loads(json.dumps(value, allow_nan=False))
    except (TypeError, RecursionError) as error:
        raise ValueError("Story result must contain only JSON data") from error


def finish_story(session_id, *, outcome="completed", result=None, message=""):
    """Publish one terminal native result for the current session."""
    global _story_command, _story_pending, _story_revision, _story_error
    if outcome not in ("completed", "cancelled") or not isinstance(message, str):
        raise ValueError("Unknown story outcome")
    result = _plain_result(result)
    with _lock:
        if (type(session_id) is not int or session_id != _story_status["session_id"]
                or _story_status["state"] not in ("active", "suspended")):
            return False
        # A replacement Start belongs to a new session. Its native reply owns
        # the next state; an ending from the preceding session cannot retire it.
        if _story_pending is not None and _story_pending["session_id"] != session_id:
            return False
        _story_command = _story_pending = None
        _story_revision += 1
        _story_error = None
        _story_status.update(state=outcome, busy=False, action=None, result=result,
                             message=message or ("Story completed." if outcome == "completed" else "Story cancelled."))
        command = {"action": outcome, "session_id": session_id,
                   "request_id": _story_status["request_id"]}
    _refresh_story_status(command)
    _refresh_save_menu()
    return True


def return_from_story(session_id, *, message="Story paused."):
    """Confirm native Return outside the mailbox, preserving the live session."""
    global _story_revision, _story_error
    if not isinstance(message, str):
        raise ValueError("Story message must be text")
    with _lock:
        if (type(session_id) is not int or session_id != _story_status["session_id"]
                or _story_status["state"] != "active" or _story_pending is not None):
            return False
        _story_revision += 1
        _story_error = None
        _story_status.update(state="suspended", message=message)
        command = {"action": "native_return", "session_id": session_id,
                   "request_id": _story_status["request_id"], "return_route": _story_status["return_route"]}
    _refresh_story_status(command)
    _refresh_save_menu()
    return True


def restore_story_status(story_id=None, *, state="suspended", message="", return_route="/app", result=None):
    """Publish recovery truth with fresh IDs; never restore callbacks or navigate."""
    global _story_sequence, _story_revision, _story_command, _story_pending, _story_error, _story_loading
    if story_id is not None:
        _validate_story_id(story_id)
    if state not in ("active", "suspended", "completed", "cancelled") or not isinstance(message, str):
        raise ValueError("Unknown restored story state")
    _validate_app_route(return_route)
    result = _plain_result(result)
    with _lock:
        _story_sequence += 1
        _story_revision += 1
        _story_error = None
        _story_loading = False
        session_id = _story_sequence if story_id is not None else None
        _story_command = _story_pending = None
        _story_status.update(story_id=story_id, session_id=session_id,
                             state=state if story_id is not None else "idle", result=result,
                             return_route=return_route, busy=False, request_id=None, action=None,
                             message=message or ("Story restored." if story_id is not None else "Choose a story to begin."))
    _refresh_story_status()
    _refresh_save_menu()
    return session_id


def reading_status():
    with _lock:
        return dict(_reading_status)


def initialize_reading(large_text, text_speed):
    with _lock:
        _reading_status.update(large_text=large_text, text_speed=text_speed)
    _refresh_reading()


def _refresh_reading():
    callback = _reading_refresh
    if callback is not None:
        callback()


def request_reading(name, value):
    """Queue preferences for Ren'Py's thread, which owns persistent storage."""
    global _reading_command, _story_revision
    if not ((name == "large_text" and type(value) is bool)
            or (name == "text_speed" and value in ("instant", "animated"))):
        raise ValueError("Unknown reading preference")
    with _lock:
        if (_reading_status["busy"] or _save_status["busy"] or _story_pending is not None
                or _quitting.is_set() or story.restarting()):
            return False
        if _reading_status[name] == value:
            return False
        _reading_command = (name, value)
        _story_revision += 1
        _reading_status.update(busy=True, message="Keeping your reading choice…")
    _refresh_reading()
    return True


def take_reading_request():
    global _reading_command
    with _lock:
        command, _reading_command = _reading_command, None
        return command


def update_reading_status(large_text, text_speed, message):
    global _reading_command, _story_revision
    with _lock:
        if _reading_status["busy"]:
            _story_revision += 1
        _reading_command = None
        _reading_status.update(large_text=large_text, text_speed=text_speed,
                               busy=False, message=message)
    _refresh_reading()


def transcript():
    with _lock:
        return _transcript


def publish_transcript(entries):
    """Publish plain native history data without reading Ren'Py on Flet's loop."""
    global _transcript
    entries = tuple(entries)
    with _lock:
        if entries == _transcript:
            return
        _transcript = entries
    callback = _history_refresh
    if callback is not None:
        callback()


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
    global _save_command, _story_revision
    if action not in ("save", "load"):
        raise ValueError("Unknown save action")
    with _lock:
        if (_save_status["busy"] or _reading_status["busy"] or _story_pending is not None
                or _quitting.is_set() or story.restarting()
                or (action == "load" and not _save_status["available"])):
            return False
        _save_command = action
        _story_revision += 1
        _save_status.update(busy=True, message="Saving…" if action == "save" else "Loading…")
    _refresh_save_menu()
    return True


def take_save_request():
    global _save_command
    with _lock:
        command, _save_command = _save_command, None
        return command


def update_save_status(available, message):
    global _save_command, _story_revision
    with _lock:
        if _save_status["busy"]:
            _story_revision += 1
        _save_command = None
        _save_status.update(available=available, busy=False, message=message)
    _refresh_save_menu()


def resume_story():
    callback = _resume_request
    if callback is not None:
        callback()


def request_quit(event=None):
    global _story_revision
    with _lock:
        if _save_status["busy"] or _reading_status["busy"] or _story_pending is not None or story.restarting():
            return False
        _quitting.set()
        _story_revision += 1
    return True


def request_restart():
    global _story_revision
    with _lock:
        if (_story_config["native_host"] or _save_status["busy"] or _reading_status["busy"] or _story_pending is not None
                or _quitting.is_set() or story.restarting()):
            return False
        story.request_restart()
        _story_revision += 1
    return True


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


def story_presentation(dialogue):
    return "interlude" if dialogue is not None and dialogue.kind != "tactics" else "scene"


async def _page(page):
    global _page_owner, _story_detach, _menu_request, _resume_request, _save_refresh, _history_refresh, _reading_refresh, _story_refresh
    import flet as ft
    if __package__:
        from . import story_ui, application_screens as app_ui
    else:
        import story_ui
        import application_screens as app_ui

    page.theme_mode = ft.ThemeMode.DARK
    loop = asyncio.get_running_loop()
    owner = _page_owner = object()
    if _story_detach is not None:
        _story_detach()
        _story_detach = None
    _menu_request = _resume_request = _save_refresh = _history_refresh = _reading_refresh = _story_refresh = None
    connection_open = True
    detach = None
    lifecycle_revision = 1
    route_revision = 0
    navigation_revision = 0
    rendered_route = None
    story_requests = {}

    def owns_page():
        return connection_open and _page_owner is owner and detach is not None and _story_detach is detach

    def schedule(callback):
        """Retire already queued work when the connection or page is replaced."""
        generation = lifecycle_revision
        def run():
            if owns_page() and generation == lifecycle_revision:
                callback()
        if not loop.is_closed():
            loop.call_soon_threadsafe(run)

    def apply_reading_theme():
        large = reading_status()["large_text"]
        page.theme = ft.Theme(color_scheme_seed="#b9d7de", text_theme=ft.TextTheme(
            body_medium=ft.TextStyle(size=18 if large else 14),
            label_large=ft.TextStyle(size=18 if large else 14)))

    def menu():
        status = save_status()
        reading = reading_status()
        session = story_status()
        status["busy"] = status["busy"] or reading["busy"] or session["busy"]
        revision, generation = navigation_revision, lifecycle_revision
        async def menu_navigate(route):
            if route == "/restart" and _story_config["native_host"]:
                route = "/app/story/start"
            await navigate(route, generation=generation, revision=revision)
        async def menu_return(event):
            if urlsplit(page.route).path == "/menu":
                submit_story("return", origin_revision=revision, generation=generation)
        return story_ui.menu_view(menu_navigate, request_quit, status, request_save, reading["large_text"],
                                  on_return_to_app=menu_return if session["state"] == "active" else None)

    def submit_story(action, *, origin_revision=None, generation=None, expected_revision=None,
                     replace=False):
        if (not owns_page() or (origin_revision is not None and origin_revision != navigation_revision)
                or (generation is not None and generation != lifecycle_revision)):
            return None
        status = story_status()
        return_route = status["return_route"] if action in ("return", "cancel") else (
            page.views[0].route if urlsplit(page.views[0].route).path == "/app" else "/app")
        request_id = request_story(action, _story_config["story_id"], return_route=return_route,
                                   expected_revision=expected_revision, replace=replace)
        if request_id is not None:
            story_requests.clear()
            story_requests[request_id] = (navigation_revision, lifecycle_revision, page.route)
        return request_id

    async def return_to_app(event=None):
        submit_story("return")

    async def navigate(route, *, generation=None, revision=None, command=None):
        if (not connection_open or _page_owner is not owner
                or (generation is not None and generation != lifecycle_revision)
                or (revision is not None and revision != navigation_revision)):
            return
        if command is not None:
            current = story_status()
            if (current["busy"] or current["request_id"] != command["request_id"]
                    or current["session_id"] != command["session_id"]
                    or current["state"] != CONFIRMED_STATES[command["action"]]):
                return
        if route == "/app" and urlsplit(page.views[0].route).path == "/app":
            route = page.views[0].route
        await page.push_route(route)

    def view_navigate():
        revision, generation = navigation_revision, lifecycle_revision
        async def guarded(route):
            await navigate(route, generation=generation, revision=revision)
        return guarded

    def settings(app=False):
        guarded = view_navigate()
        revision, generation = navigation_revision, lifecycle_revision
        async def settings_navigate(route):
            await guarded("/app" if app and route == "/menu" else route)
        def change_reading(name, value):
            if owns_page() and revision == navigation_revision and generation == lifecycle_revision:
                return request_reading(name, value)
            return False
        reading = reading_status()
        reading["busy"] = app_story_status()["busy"]
        return story_ui.settings_view(settings_navigate, reading, change_reading)

    def app_view(route):
        """Unmounted C views use the same guarded navigation and mailbox owner."""
        revision, generation = navigation_revision, lifecycle_revision
        path = urlsplit(route).path
        if path == "/restart" and _story_config["native_host"]:
            path = "/app/story/start"

        async def app_navigate(target):
            await navigate(target, generation=generation, revision=revision)

        def submit(action, expected_revision):
            return submit_story(action, origin_revision=revision, generation=generation,
                                expected_revision=expected_revision,
                                replace=action == "start" and path == "/app/story/start") is not None

        async def reload_status():
            if owns_page() and revision == navigation_revision and generation == lifecycle_revision:
                await render_app_status(generation=generation)

        options = dict(route=route, large_text=reading_status()["large_text"])
        if path == "/app/story/result":
            return app_ui.app_result_view(app_navigate, app_story_status()["result"], **options)
        if path in ("/app/story/start", "/app/story/cancel"):
            return app_ui.app_confirmation_view(page, app_navigate, app_story_status, submit,
                action="start" if path.endswith("/start") else "cancel", refresh_status=reload_status, **options)
        if path == "/app/story":
            return app_ui.app_story_view(page, app_navigate, app_story_status, submit,
                                         refresh_status=reload_status, **options)
        return app_ui.app_home_view(page, app_navigate, app_story_status, submit,
            refresh_status=reload_status, story_title=_story_config["story_title"], **options)

    def dialogue_controls(dialogue):
        revision, generation = navigation_revision, lifecycle_revision

        def accepts_input():
            return (owns_page() and revision == navigation_revision and generation == lifecycle_revision
                    and urlsplit(page.route).path in ("", "/") and not app_story_status()["busy"])

        async def native_return(event):
            submit_story("return", origin_revision=revision, generation=generation)

        async def story_navigate(route):
            await navigate(route, generation=generation, revision=revision)

        status = story_status()
        return story_ui.dialogue_controls(story_navigate, dialogue, reading_status()["large_text"],
            on_return_to_app=native_return if status["state"] == "active" else None,
            return_to_app_busy=app_story_status()["busy"], accepts_input=accepts_input)

    def request_menu():
        revision = navigation_revision
        generation = lifecycle_revision
        def open_current_menu():
            if revision == navigation_revision and urlsplit(page.route).path in STORY_ROUTES:
                asyncio.create_task(navigate("/menu", generation=generation, revision=revision))
        schedule(open_current_menu)

    def request_resume():
        revision = navigation_revision
        generation = lifecycle_revision
        async def resume():
            # Automatic mobile recovery must respect an explicit app/diagnostics
            # link. Read page state only on the Flet loop.
            if (owns_page() and revision == navigation_revision
                    and urlsplit(page.route).path in STORY_ROUTES):
                await navigate("/", generation=generation, revision=revision)
        schedule(lambda: asyncio.create_task(resume()))

    def render_save_menu():
        if not owns_page():
            return
        reading = reading_status()
        busy = save_status()["busy"] or reading["busy"] or story_status()["busy"]
        refreshed_any = False
        for index, view in enumerate(page.views):
            path = urlsplit(view.route).path
            if path == "/menu":
                refreshed = menu()
            elif path in ("/settings", "/app/settings"):
                refreshed = settings(app=path == "/app/settings")
            elif path in APP_ROUTES and path not in ("/app/records", "/app/settings"):
                refreshed = app_view(view.route)
            elif path == "/restart":
                refreshed = app_view(view.route) if _story_config["native_host"] else story_ui.restart_view(
                    navigate, request_restart, busy, reading["large_text"])
            else:
                continue
            refreshed.route = view.route
            page.views[index] = refreshed
            refreshed_any = True
        if refreshed_any:
            page.update()

    def save_changed():
        schedule(render_save_menu)

    def render_history():
        if not owns_page() or urlsplit(page.views[-1].route).path != "/history":
            return
        history = story_ui.transcript_view(navigate, transcript(), reading_status()["large_text"])
        history.route = page.views[-1].route
        page.views[-1] = history
        page.update()

    def history_changed():
        schedule(render_history)

    async def render_app_status(command=None, *, generation, event_revision=None):
        if not owns_page() or generation != lifecycle_revision:
            return
        status = story_status()
        for index, view in enumerate(page.views):
            path = urlsplit(view.route).path
            if path in APP_ROUTES and path not in ("/app/records", "/app/settings"):
                refreshed = app_view(view.route)
            else:
                continue
            refreshed.route = view.route
            page.views[index] = refreshed
        if urlsplit(page.views[0].route).path == "/":
            page.views[0].controls = dialogue_controls(story.current())
        page.update()
        if command is None:
            return
        if command["action"] in ("native_return", "completed", "cancelled"):
            if (event_revision != navigation_revision or urlsplit(page.route).path not in ("", "/") or status["busy"]
                    or status["session_id"] != command["session_id"]
                    or status["request_id"] != command["request_id"]
                    or status["state"] != CONFIRMED_STATES[command["action"]]):
                return
            target = command.get("return_route", "/app/story/result")
            await navigate(target, generation=generation, revision=navigation_revision, command=command)
            return
        origin = story_requests.pop(command["request_id"], None)
        if (origin != (navigation_revision, lifecycle_revision, page.route)
                or status["busy"] or status["session_id"] != command["session_id"]
                or status["request_id"] != command["request_id"]
                or status["state"] != CONFIRMED_STATES[command["action"]]):
            return
        target = command["return_route"] if command["action"] in ("return", "cancel") else "/"
        await navigate(target, generation=generation, revision=origin[0], command=command)

    def story_status_changed(command=None):
        generation = lifecycle_revision
        revision = navigation_revision
        schedule(lambda: asyncio.create_task(render_app_status(command, generation=generation, event_revision=revision)))

    value = ft.Text(f"Count: {counter()}", size=24)

    def clicked(event):
        value.value = f"Count: {increment()}"
        page.update()

    def diagnostics_controls():
        return [ft.Text("Connected", size=24), value, ft.Row([
            ft.Button("Increment", on_click=clicked),
            ft.Button("Capabilities", on_click=story_ui.route_handler(navigate, "/capabilities")),
            ft.Button("Application records", on_click=story_ui.route_handler(navigate, "/records")),
            ft.Button("Return to story", on_click=story_ui.route_handler(navigate, "/")),
            ft.Button("Quit runner", on_click=request_quit),
        ], wrap=True)]

    async def popped(event):
        if not connection_open or _page_owner is not owner:
            return
        path = urlsplit(page.route).path
        if path == "/app":
            return
        if path == "/" and story_status()["state"] == "active":
            await return_to_app()
        elif path in ("/app/story/start", "/app/story/cancel") or (path == "/restart" and _story_config["native_host"]):
            await navigate("/app/story")
        elif path in APP_ROUTES:
            await navigate(page.views[0].route if urlsplit(page.views[0].route).path == "/app" else "/app")
        elif path == "/records" and len(page.views) == 1:
            await navigate("/diagnostics")
        elif len(page.views) > 1:
            page.views.pop()
            await navigate(page.views[-1].route)
        else:
            await navigate("/menu")

    page.on_view_pop = popped
    last_dialogue = None
    record_view_task = None
    record_path = None
    async def render_route(route):
        nonlocal last_dialogue, record_view_task, record_path, route_revision, navigation_revision, rendered_route
        if not connection_open or _page_owner is not owner:
            return
        route_revision += 1
        revision = route_revision
        if route != rendered_route:
            navigation_revision += 1
            rendered_route = route
        apply_reading_theme()
        reading = reading_status()
        path = urlsplit(route).path
        records = path in ("/records", "/app/records")
        if (not records or path != record_path) and record_view_task is not None:
            if not record_view_task.done():
                record_view_task.cancel()
            record_view_task = None
            record_path = None
        app = path in APP_ROUTES
        diagnostic = path in ("/diagnostics", "/capabilities", "/records")
        base_path = "/app" if app else "/diagnostics" if diagnostic else "/"
        if urlsplit(page.views[0].route).path != base_path:
            page.views[:] = [ft.View(route=base_path)]
        root = page.views[0]
        root.bgcolor = "#101b2b" if diagnostic or app else "transparent"
        root.padding = 24 if app else 10 if diagnostic else 12
        if app:
            root.controls = app_view(root.route).controls
        elif diagnostic:
            root.controls = diagnostics_controls()
        else:
            last_dialogue = story.current()
            root.controls = dialogue_controls(last_dialogue)
        if records:
            set_presentation("page")
            if record_view_task is None:
                record_path = path
                if __package__:
                    from .form_list import create_form_list_view
                else:
                    from form_list import create_form_list_view
                record_view_task = asyncio.create_task(
                    app_ui.create_app_records_view(page, view_navigate(), route=route) if path == "/app/records"
                    else create_form_list_view(page, route=route,
                        on_back=story_ui.route_handler(view_navigate(), "/diagnostics")))
            try:
                view = await asyncio.shield(record_view_task)
            except asyncio.CancelledError:
                if revision != route_revision:
                    return
                raise
            # A native preferences read can finish after a newer route request.
            if revision != route_revision or not connection_open or _page_owner is not owner:
                return
            view.route = route
            # Keep fields/services on a reused form, but retire its prior Back
            # callback after a query change or reconnect.
            back_control = getattr(view, "_runner_back_control", None)
            if back_control is not None:
                back_control.on_click = story_ui.route_handler(view_navigate(),
                    "/app" if path == "/app/records" else "/diagnostics")
            page.views[:] = [root, view]
        elif app:
            set_presentation("page")
            page.views[:] = [root]
            if path in ("/app/story", "/app/story/start", "/app/story/cancel", "/app/story/result"):
                page.views.append(app_view(route))
            elif path == "/app/settings":
                page.views.append(settings(app=True))
            page.views[-1].route = route
        elif path == "/capabilities":
            set_presentation("diagnostics")
            if urlsplit(page.views[-1].route).path != path:
                from capability_demo import open_page
                await open_page(page, route=route)
            else:
                page.views[-1].route = route
        elif path in ("/menu", "/history", "/restart", "/settings"):
            set_presentation("page")
            page.views[:] = [root, menu()]
            if path == "/history":
                page.views.append(story_ui.transcript_view(navigate, transcript(), reading["large_text"]))
            elif path == "/restart":
                page.views.append(app_view(route) if _story_config["native_host"] else story_ui.restart_view(
                    navigate, request_restart,
                    save_status()["busy"] or reading["busy"] or story_status()["busy"], reading["large_text"]))
            elif path == "/settings":
                page.views.append(settings())
            page.views[-1].route = route
        else:
            page.views[:] = [root]
            root.route = route if path in ("", "/", "/diagnostics") else base_path
            set_presentation("diagnostics" if diagnostic else story_presentation(last_dialogue))
        page.update()

    async def route_changed(event):
        await render_route(event.route)

    page.on_route_change = route_changed

    async def render_reading(generation):
        if owns_page() and generation == lifecycle_revision:
            await render_route(page.route)

    def reading_changed():
        generation = lifecycle_revision
        schedule(lambda: asyncio.create_task(render_reading(generation)))

    def render_story():
        nonlocal last_dialogue
        dialogue = story.current()
        if not owns_page() or dialogue == last_dialogue or urlsplit(page.views[0].route).path != "/":
            return
        last_dialogue = dialogue
        page.views[0].controls = dialogue_controls(dialogue)
        if len(page.views) == 1:
            set_presentation(story_presentation(dialogue))
        page.update()

    def changed():
        schedule(render_story)

    async def connected(event=None):
        nonlocal detach, last_dialogue, lifecycle_revision, connection_open
        global _story_detach, _menu_request, _resume_request, _save_refresh, _history_refresh, _reading_refresh, _story_refresh
        if _page_owner is not owner:
            return
        if detach is not None or not connection_open:
            lifecycle_revision += 1
        connection_open = True
        if detach is not None:
            detach()
        if _story_detach is not None:
            _story_detach()
        detach = story.subscribe(changed)
        _story_detach = detach
        _menu_request = request_menu
        _resume_request = request_resume
        _save_refresh = save_changed
        _history_refresh = history_changed
        _reading_refresh = reading_changed
        _story_refresh = story_status_changed
        # Reconcile native changes missed during the initial async mount, but
        # keep unchanged first-render controls alive for their first events.
        # Reconnect always refreshes, including events without a payload.
        if lifecycle_revision > 1 or status_snapshot() != initial_status:
            last_dialogue = object()
            await render_reading(lifecycle_revision)
        render_story()

    async def disconnected(event):
        nonlocal detach, record_view_task, record_path, route_revision, navigation_revision, lifecycle_revision, connection_open
        global _story_detach, _menu_request, _resume_request, _save_refresh, _history_refresh, _reading_refresh, _story_refresh
        route_revision += 1
        navigation_revision += 1
        lifecycle_revision += 1
        connection_open = False
        story_requests.clear()
        if record_view_task is not None and not record_view_task.done():
            record_view_task.cancel()
            record_view_task = None
            record_path = None
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
        if _history_refresh is history_changed:
            _history_refresh = None
        if _reading_refresh is reading_changed:
            _reading_refresh = None
        if _story_refresh is story_status_changed:
            _story_refresh = None

    page.on_connect = connected
    page.on_disconnect = page.on_close = disconnected
    def status_snapshot():
        return reading_status(), save_status(), story_status(), app_story_status(), transcript(), story.current()
    # Flet registers the initial route in page state without a route_change event.
    initial_status = status_snapshot()
    initial_lifecycle_revision = lifecycle_revision
    await render_route(page.route)
    if lifecycle_revision != initial_lifecycle_revision or _page_owner is not owner:
        return
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
        global _loop, _task, _page_owner, _story_detach, _menu_request, _resume_request, _save_refresh, _history_refresh, _reading_refresh, _story_refresh
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
            _history_refresh = None
            _reading_refresh = None
            _story_refresh = None
            _page_owner = None
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
