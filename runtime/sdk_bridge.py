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
    from .app_session import app_mode, session as app_session
else:
    from renfletpy import story
    from app_session import app_mode, session as app_session

_lock = app_session.operation_lock
_count = 0
_thread = None
_loop = None
_task = None
_stopping = threading.Event()
_quitting = threading.Event()
_presentation = "scene"
_requested_presentation = "scene"
_app_story_load_command = None
_save_load_token = None
_story_detach = None
_menu_request = None
_resume_request = None
_save_refresh = None
_save_command = None
_taken_save_action = None
_save_status = {"available": False, "busy": False, "message": "No saved game yet."}
_transcript = ()
_history_refresh = None
_reading_refresh = None
_reading_command = None
_reading_status = {"large_text": False, "text_speed": "instant", "busy": False,
                   "message": "These choices are kept for your next visit."}
_app_detach = None
_app_refresh = None


def _app_blocked():
    return (_save_status["busy"] or _reading_status["busy"]
            or _quitting.is_set() or story.restarting())


app_session.bind_gate(_app_blocked)


def request_app_story(action, revision, *, replace=False):
    """Submit plain app-story intent; native code owns all flow and saves."""
    return app_session.request(action, revision, replace=replace)


def _refresh_app():
    if _app_refresh is not None:
        _app_refresh()


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
    _refresh_app()


def request_reading(name, value):
    """Queue preferences for Ren'Py's thread, which owns persistent storage."""
    global _reading_command
    if not ((name == "large_text" and type(value) is bool)
            or (name == "text_speed" and value in ("instant", "animated"))):
        raise ValueError("Unknown reading preference")
    with _lock:
        if (_reading_status["busy"] or _save_status["busy"] or _quitting.is_set()
                or story.restarting() or app_session.status()["busy"]):
            return False
        if _reading_status[name] == value:
            return False
        _reading_command = (name, value)
        _reading_status.update(busy=True, message="Keeping your reading choice…")
    _refresh_reading()
    return True


def take_reading_request():
    global _reading_command
    with _lock:
        command, _reading_command = _reading_command, None
        return command


def update_reading_status(large_text, text_speed, message):
    global _reading_command
    with _lock:
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
    _refresh_app()


def request_save(action):
    """Flet submits a command; only Ren'Py's thread may execute save/load."""
    global _save_command
    if action not in ("save", "load"):
        raise ValueError("Unknown save action")
    with _lock:
        if (_save_status["busy"] or _reading_status["busy"] or _quitting.is_set() or story.restarting()
                or app_session.status()["busy"]
                or (action == "load" and not _save_status["available"])):
            return False
        _save_command = action
        _save_status.update(busy=True, message="Saving…" if action == "save" else "Loading…")
    _refresh_save_menu()
    return True


def take_save_request():
    global _save_command, _taken_save_action
    with _lock:
        command, _save_command = _save_command, None
        if command is not None:
            _taken_save_action = command
        return command


def update_save_status(available, message):
    global _save_command, _taken_save_action
    with _lock:
        _save_command = None
        _taken_save_action = None
        _save_status.update(available=available, busy=False, message=message)
    _refresh_save_menu()


def resume_story():
    callback = _resume_request
    if callback is not None:
        callback()


def request_quit(event=None):
    with _lock:
        if (_save_status["busy"] or _reading_status["busy"] or story.restarting()
                or app_session.status()["busy"]):
            return False
        _quitting.set()
    return True


def request_restart():
    with _lock:
        if (_save_status["busy"] or _reading_status["busy"] or _quitting.is_set()
                or story.restarting() or app_session.status()["busy"]):
            return False
        story.request_restart()
        if app_mode():
            # Native full_restart discards the live interaction. The mailbox is
            # outside Ren'Py's store and must not advertise that old context.
            app_session.restore(phase="ready", resume_kind="unavailable", showing_story=False,
                                message="Ready to start a story.")
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


def _publish_presentation(mode):
    """Publish under _lock so native and Flet requests reach Android in order."""
    global _presentation
    _presentation = mode
    if getattr(sys.modules.get("renpy"), "android", False):
        from jnius import autoclass, cast
        activity = cast("org.sdk.runner.RunnerActivity",
                        autoclass("org.renpy.android.PythonSDLActivity").mActivity)
        activity.setRunnerPresentation(mode)
    print(f"SDK_RUNNER_PRESENTATION mode={mode} pid={os.getpid()}", flush=True)


def set_presentation(mode):
    global _requested_presentation
    if mode not in ("scene", "interlude", "page", "diagnostics"):
        raise ValueError("Unknown runner presentation")
    with _lock:
        _requested_presentation = mode
        _publish_presentation("scene" if _app_story_load_command is not None
                              or _save_load_token is not None else mode)


def begin_save_load():
    """Give a taken Quick load native input until its owner releases it."""
    global _save_load_token
    with _lock:
        if (_taken_save_action != "load" or not _save_status["busy"]
                or _save_command is not None or _stopping.is_set()
                or _save_load_token is not None or _app_story_load_command is not None):
            return None
        token = _save_load_token = object()
        try:
            _publish_presentation("scene")
        except Exception:
            _save_load_token = None
            raise
        return token


def end_save_load(token):
    """Restore the latest presentation without changing the current route."""
    global _save_load_token
    with _lock:
        if token is None or _save_load_token is not token:
            return False
        _save_load_token = None
        _publish_presentation(_requested_presentation)
        return True


def begin_app_story_load(command_id):
    """Give a taken saved Resume's native confirmation visible SDL input."""
    global _app_story_load_command
    with _lock:
        state = app_session.status()
        # Consumption and this check share the mailbox lock. The ownership token
        # is separate from its command, which after_load can acknowledge first.
        if (type(command_id) is not int or not state["app_mode"]
                or _stopping.is_set() or _story_detach is None
                or _app_story_load_command is not None or _save_load_token is not None or not app_session._taken
                or state["event"] != "requested" or state["action"] != "resume"
                or state["command_id"] != command_id or state["resume_kind"] != "saved"):
            return False
        _app_story_load_command = command_id
        try:
            _publish_presentation("scene")
        except Exception:
            _app_story_load_command = None
            raise
        return True


def end_app_story_load(command_id):
    """Release only this load's presentation; never navigate its Flet route."""
    global _app_story_load_command
    with _lock:
        if type(command_id) is not int or _app_story_load_command != command_id:
            return False
        _app_story_load_command = None
        _publish_presentation(_requested_presentation)
        return True


def _keep_native_load_visible():
    global _requested_presentation
    with _lock:
        if _app_story_load_command is not None or _save_load_token is not None:
            # A disconnected page must not cover an unanswered native prompt.
            # Its native owner still releases the scope in finally. Reconnect
            # records the latest logical presentation without covering it.
            _requested_presentation = "scene"
            _publish_presentation("scene")


def open_menu():
    """Queue a shared menu from a Ren'Py screen action, on Flet's own loop."""
    if _menu_request is not None:
        _menu_request()


def story_presentation(dialogue):
    return "interlude" if dialogue is not None and dialogue.kind != "tactics" else "scene"


async def _page(page):
    global _story_detach, _menu_request, _resume_request, _save_refresh, _history_refresh, _reading_refresh
    global _app_detach, _app_refresh
    import flet as ft
    if __package__:
        from . import story_ui
    else:
        import story_ui

    page.theme_mode = ft.ThemeMode.DARK
    loop = asyncio.get_running_loop()
    optional_app = app_mode()

    def apply_reading_theme():
        large = reading_status()["large_text"]
        page.theme = ft.Theme(color_scheme_seed="#b9d7de", text_theme=ft.TextTheme(
            body_medium=ft.TextStyle(size=18 if large else 14),
            label_large=ft.TextStyle(size=18 if large else 14)))

    def menu():
        status = save_status()
        reading = reading_status()
        status["busy"] = status["busy"] or reading["busy"] or app_session.status()["busy"]
        if optional_app:
            state = app_session.status()
            async def return_to_app(event):
                return submit_app_story("return", state["revision"])
            return story_ui.menu_view(navigate, request_quit, status, request_save, reading["large_text"],
                                     on_return_to_app=return_to_app if state["showing_story"] else None)
        return story_ui.menu_view(navigate, request_quit, status, request_save, reading["large_text"])

    async def navigate(route):
        nonlocal navigation_revision, intent_revision, intent_route
        # Button/Back intent wins immediately, before its client echo arrives.
        navigation_revision += 1
        intent_revision += 1
        intent_route = route
        await page.push_route(route)

    native_routes = []
    intent_revision = 0
    intent_route = page.route
    client_route = page.route

    def retire_native_route(request):
        if request["acked"] and request["processed"] and request in native_routes:
            native_routes.remove(request)

    async def send_route(route, *, repair_revision=None):
        nonlocal intent_revision, intent_route
        if ((detach is None and lifecycle_revision != 0)
                or (detach is not None and _story_detach is not detach)):
            return
        if repair_revision is not None:
            if repair_revision != intent_revision:
                return
        for request in native_routes:
            if (request["route"] == route and request["lifecycle"] == lifecycle_revision
                    and request["intent"] == intent_revision and not request["received"]):
                # Two equal RPCs produce only one route event on Flutter.
                # Only a still-current target can share that pending echo.
                return
        if repair_revision is None:
            intent_revision += 1
            intent_route = route
        if route == client_route:
            # RouteState suppresses equal-route events; no RPC/token is needed.
            page.route = route
            await render_route(route)
            return
        request = {"route": route, "intent": intent_revision, "lifecycle": lifecycle_revision,
                   "received": False, "processed": False, "acked": False}
        native_routes.append(request)
        try:
            await page.push_route(route)
        except Exception:
            # A rejected method has no route echo to consume. Do not let its
            # target intercept a later real navigation to the same route.
            native_routes.remove(request)
            if request["intent"] == intent_revision:
                intent_revision += 1
                intent_route = page.views[-1].route
                page.route = intent_route
            raise
        finally:
            # The method reply can arrive before its separately dispatched
            # route event. Keep its target until that event finishes as well.
            request["acked"] = True
            retire_native_route(request)

    app_navigation = None
    def submit_app_story(action, revision, *, replace=False):
        nonlocal app_navigation
        path = urlsplit(page.route).path
        if (detach is None or _story_detach is not detach
                or (action in ("start", "resume") and path != "/app")
                or (action == "return" and path not in ("/", "/menu", "/history", "/settings"))):
            return False
        accepted = request_app_story(action, revision, replace=replace)
        if accepted:
            app_navigation = (app_session.status()["command_id"], navigation_revision, lifecycle_revision)
        return accepted

    def request_menu():
        epoch, navigation = lifecycle_revision, navigation_revision
        async def open_requested_menu():
            if (detach is not None and _story_detach is detach and epoch == lifecycle_revision
                    and navigation == navigation_revision):
                await send_route("/menu")
        if not loop.is_closed():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(open_requested_menu()))

    def request_resume():
        epoch, navigation = lifecycle_revision, navigation_revision
        async def resume():
            # Automatic mobile recovery must respect an explicit app/diagnostics
            # link. Read page state only on the Flet loop.
            protected = ("/diagnostics", "/capabilities", "/records", "/recipes")
            if optional_app:
                protected += ("/app", "/app/records", "/app/recipes")
            if (detach is not None and _story_detach is detach and epoch == lifecycle_revision
                    and navigation == navigation_revision
                    and urlsplit(intent_route).path not in protected):
                await send_route("/")
        if not loop.is_closed():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(resume()))

    def render_save_menu():
        if detach is None:
            return
        reading = reading_status()
        busy = save_status()["busy"] or reading["busy"] or app_session.status()["busy"]
        refreshed_any = False
        for index, view in enumerate(page.views):
            path = urlsplit(view.route).path
            if path == "/menu":
                refreshed = menu()
            elif path == "/settings":
                reading["busy"] = busy
                refreshed = story_ui.settings_view(navigate, reading, request_reading)
            elif path == "/restart":
                refreshed = story_ui.restart_view(navigate, request_restart, busy, reading["large_text"])
            else:
                continue
            refreshed.route = view.route
            page.views[index] = refreshed
            refreshed_any = True
        if refreshed_any:
            page.update()

    def save_changed():
        if not loop.is_closed():
            loop.call_soon_threadsafe(render_save_menu)

    def render_history():
        if detach is None or urlsplit(page.views[-1].route).path != "/history":
            return
        history = story_ui.transcript_view(navigate, transcript(), reading_status()["large_text"])
        history.route = page.views[-1].route
        page.views[-1] = history
        page.update()

    def history_changed():
        if not loop.is_closed():
            loop.call_soon_threadsafe(render_history)

    value = ft.Text(f"Count: {counter()}", size=24)

    def clicked(event):
        value.value = f"Count: {increment()}"
        page.update()

    def diagnostics_controls():
        return [ft.Text("Connected", size=24), value, ft.Row([
            ft.Button("Increment", on_click=clicked),
            ft.Button("Capabilities", on_click=story_ui.route_handler(navigate, "/capabilities")),
            ft.Button("Application records", on_click=story_ui.route_handler(navigate, "/records")),
            ft.Button("Application recipes", on_click=story_ui.route_handler(navigate, "/recipes")),
            ft.Button("Return to story", on_click=story_ui.route_handler(navigate, "/")),
            ft.Button("Quit runner", on_click=request_quit),
        ], wrap=True)]

    async def popped(event):
        if optional_app and urlsplit(page.route).path in ("/app/records", "/app/recipes"):
            await navigate("/app")
        elif urlsplit(page.route).path == "/recipes":
            await navigate("/diagnostics")
        elif optional_app and urlsplit(page.route).path == "/app":
            request_quit()
        elif urlsplit(page.route).path == "/records" and len(page.views) == 1:
            await navigate("/diagnostics")
        elif len(page.views) > 1:
            page.views.pop()
            await navigate(page.views[-1].route)
        else:
            await navigate("/menu")

    page.on_view_pop = popped
    last_dialogue = None
    record_view_task = None
    record_view_path = None
    record_loading_view = None
    recipe_view = None
    recipe_view_path = None
    recipe_dispose = None
    def dispose_recipe():
        nonlocal recipe_view, recipe_view_path, recipe_dispose
        if recipe_dispose is not None:
            recipe_dispose()
        recipe_view = recipe_view_path = recipe_dispose = None

    route_revision = 0
    navigation_revision = 0
    async def render_route(route):
        nonlocal last_dialogue, record_view_task, record_view_path, record_loading_view, route_revision
        nonlocal recipe_view, recipe_view_path, recipe_dispose
        route_revision += 1
        revision = route_revision
        apply_reading_theme()
        reading = reading_status()
        path = urlsplit(route).path
        known_routes = ("", "/", "/app", "/app/records", "/app/recipes", "/diagnostics", "/capabilities",
                        "/records", "/recipes", "/menu", "/history", "/restart", "/settings")
        if optional_app and (path not in known_routes or
                            (path in ("", "/") and not app_session.status()["showing_story"])):
            # Neither a raw story link nor the unknown-route fallback may reveal
            # a returned interaction before native Resume acknowledgement.
            route, path = "/app", "/app"
            page.route = route
        app_route = optional_app and path in ("/app", "/app/records", "/app/recipes")
        records_route = path == "/records" or (optional_app and path == "/app/records")
        recipes_route = path == "/recipes" or (optional_app and path == "/app/recipes")
        if not recipes_route or path != recipe_view_path:
            dispose_recipe()
        if (not records_route or path != record_view_path) and record_view_task is not None:
            if not record_view_task.done():
                record_view_task.cancel()
            record_view_task = None
            record_view_path = None
            record_loading_view = None
        diagnostic = path in ("/diagnostics", "/capabilities", "/records", "/recipes")
        base_path = "/app" if app_route else "/diagnostics" if diagnostic else "/"
        if urlsplit(page.views[0].route).path != base_path:
            page.views[:] = [ft.View(route=base_path)]
        root = page.views[0]
        root.bgcolor = "#101b2b" if diagnostic or app_route else "transparent"
        root.padding = 10 if diagnostic or app_route else 12
        if app_route:
            if __package__:
                from .app_home import app_home_view
            else:
                from app_home import app_home_view
            root = app_home_view(page, navigate, app_session.status(), submit_app_story,
                                 route=route if path == "/app" else "/app", large_text=reading["large_text"])
            page.views[0] = root
        elif diagnostic:
            root.controls = diagnostics_controls()
        else:
            last_dialogue = story.current()
            root.controls = story_ui.dialogue_controls(navigate, last_dialogue, reading["large_text"])
        if records_route:
            set_presentation("page")
            if record_view_task is None:
                if __package__:
                    from .form_list import create_form_list_view
                else:
                    from form_list import create_form_list_view
                record_view_task = asyncio.create_task(create_form_list_view(
                    page, route=route, on_back=popped))
                record_view_path = path
            if path == "/app/records" and not record_view_task.done():
                if record_loading_view is None:
                    loading_task, epoch = record_view_task, lifecycle_revision
                    async def loading_back(event):
                        if (epoch == lifecycle_revision and record_view_task is loading_task
                                and not loading_task.done()):
                            await popped(event)
                    record_loading_view = ft.View(route=route, bgcolor="#101b2b", padding=24, controls=[
                        ft.Column(controls=[
                            ft.Row(controls=[ft.Text("Application records", size=24, expand=True),
                                             ft.TextButton("Back", on_click=loading_back)]),
                            ft.Text("Loading records…"),
                        ], spacing=18),
                    ])
                record_loading_view.route = route
                page.views[:] = [root, record_loading_view]
                page.update()
            try:
                view = await asyncio.shield(record_view_task)
            except asyncio.CancelledError:
                if revision != route_revision:
                    return
                raise
            # A native preferences read can finish after a newer route request.
            if revision != route_revision:
                return
            view.route = route
            page.views[:] = [root, view]
            record_loading_view = None
        elif recipes_route:
            set_presentation("page")
            if recipe_view is None:
                if __package__:
                    from .app_recipes import create_app_recipes_view
                else:
                    from app_recipes import create_app_recipes_view
                mounted_path, mounted_epoch = path, lifecycle_revision
                mounted_view = None
                def current_recipe():
                    return (detach is not None and _story_detach is detach
                            and lifecycle_revision == mounted_epoch
                            and urlsplit(intent_route).path == mounted_path
                            and page.views[-1] is mounted_view)
                mounted_view, recipe_dispose = create_app_recipes_view(
                    page, route=route, on_back=popped, is_current=current_recipe)
                recipe_view, recipe_view_path = mounted_view, path
            recipe_view.route = route
            page.views[:] = [root, recipe_view]
        elif app_route:
            page.views[:] = [root]
            set_presentation("page")
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
                page.views.append(story_ui.restart_view(navigate, request_restart,
                                  save_status()["busy"] or reading["busy"] or app_session.status()["busy"],
                                  reading["large_text"]))
            elif path == "/settings":
                reading["busy"] = reading["busy"] or save_status()["busy"] or app_session.status()["busy"]
                page.views.append(story_ui.settings_view(navigate, reading, request_reading))
            page.views[-1].route = route
        else:
            page.views[:] = [root]
            root.route = route if path in ("", "/", "/diagnostics") else base_path
            set_presentation("diagnostics" if diagnostic else story_presentation(last_dialogue))
        page.update()

    async def route_changed(event):
        nonlocal navigation_revision, intent_revision, intent_route, client_route
        client_route = event.route
        request = next((request for request in native_routes
                        if request["route"] == event.route and not request["received"]), None)
        stale = False
        route = event.route
        if request is not None:
            request["received"] = True
            stale = (request["intent"] != intent_revision
                     or request["lifecycle"] != lifecycle_revision)
            if stale:
                # A sent RPC cannot be cancelled on Flutter. Its late echo
                # must not replace a newer route, view, draft or presentation.
                route = intent_route
                page.route = route
        else:
            intent_revision += 1
            intent_route = route
        if not stale:
            navigation_revision += 1
        try:
            await render_route(route)
        finally:
            if request is not None:
                request["processed"] = True
                retire_native_route(request)
        if stale and detach is not None and _story_detach is detach:
            # Repair the client's RouteState, not only the Page property. Each
            # stale echo gets one guarded correction; newer intent also guards
            # that correction's own echo, without a retry loop.
            asyncio.create_task(send_route(intent_route, repair_revision=intent_revision))

    page.on_route_change = route_changed

    async def render_reading():
        if detach is not None:
            if native_routes:
                page.route = intent_route
            await render_route(page.route)

    def reading_changed():
        if not loop.is_closed():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(render_reading()))

    async def render_app(state=None, expected_lifecycle=None):
        nonlocal app_navigation
        if (not optional_app or detach is None or _story_detach is not detach
                or expected_lifecycle != lifecycle_revision):
            return
        current = app_session.status()
        if state is not None and state["revision"] == current["revision"]:
            if (state["event"] == "finished" and app_navigation is not None
                    and app_navigation == (state["command_id"], navigation_revision, lifecycle_revision)):
                app_navigation = None
                await send_route("/app" if state["action"] == "return" else "/")
            elif (state["event"] == "completed" and current["phase"] == "completed"
                    and urlsplit(intent_route if native_routes else page.route).path == "/"):
                await send_route("/app")
            elif (state["event"] == "restored" and current["phase"] == "ready"
                    and urlsplit(intent_route if native_routes else page.route).path == "/"):
                await send_route("/app")
        # Navigation awaits a transport reply. The page or generation may have
        # changed meanwhile; never publish its pre-await status on reconnect.
        if (detach is None or _story_detach is not detach
                or expected_lifecycle != lifecycle_revision):
            return
        current = app_session.status()
        # Status refresh is not a navigation revision: busy updates must not
        # invalidate the very command whose native acknowledgement is pending.
        if urlsplit(page.views[0].route).path == "/app":
            if __package__:
                from .app_home import app_home_view
            else:
                from app_home import app_home_view
            refreshed = app_home_view(page, navigate, current, submit_app_story,
                                      route=page.views[0].route, large_text=reading_status()["large_text"])
            page.views[0].controls = refreshed.controls
            page.update()
        render_save_menu()

    def app_changed(state, expected_lifecycle):
        if not loop.is_closed():
            loop.call_soon_threadsafe(lambda: asyncio.create_task(render_app(state, expected_lifecycle)))

    def app_refresh():
        app_changed(None, lifecycle_revision)

    def render_story():
        nonlocal last_dialogue
        dialogue = story.current()
        if detach is None or dialogue == last_dialogue or urlsplit(page.views[0].route).path != "/":
            return
        last_dialogue = dialogue
        page.views[0].controls = story_ui.dialogue_controls(navigate, dialogue, reading_status()["large_text"])
        if len(page.views) == 1:
            set_presentation(story_presentation(dialogue))
        page.update()

    def changed():
        if not loop.is_closed():
            loop.call_soon_threadsafe(render_story)

    detach = None
    app_detach = None
    lifecycle_revision = 0
    async def connected(event=None):
        nonlocal detach, app_detach, last_dialogue, intent_revision, intent_route, client_route
        global _story_detach, _menu_request, _resume_request, _save_refresh, _history_refresh, _reading_refresh
        global _app_detach, _app_refresh
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
        if app_detach is not None:
            app_detach()
        if _app_detach is not None:
            _app_detach()
        if optional_app:
            epoch = lifecycle_revision
            app_detach = app_session.subscribe(lambda state: app_changed(state, epoch))
            _app_detach = app_detach
            _app_refresh = app_refresh
        if event is not None:
            intent_revision += 1
            intent_route = client_route = page.route
            last_dialogue = object()
            await render_reading()
        render_story()
        if optional_app:
            await render_app(expected_lifecycle=lifecycle_revision)

    async def disconnected(event):
        nonlocal detach, app_detach, app_navigation, record_view_task, record_view_path, record_loading_view
        nonlocal route_revision, lifecycle_revision, intent_revision, intent_route
        global _story_detach, _menu_request, _resume_request, _save_refresh, _history_refresh, _reading_refresh
        global _app_detach, _app_refresh
        route_revision += 1
        lifecycle_revision += 1
        intent_revision += 1
        # Retain pending targets only to classify their late echoes. Their old
        # intended destination must not survive as reconnect's reading route.
        intent_route = page.views[-1].route if native_routes else page.route
        page.route = intent_route
        app_navigation = None
        dispose_recipe()
        if record_view_task is not None and not record_view_task.done():
            record_view_task.cancel()
            record_view_task = None
            record_view_path = None
            record_loading_view = None
        if app_detach is not None:
            app_detach()
            if _app_detach is app_detach:
                _app_detach = None
            app_detach = None
        if _app_refresh is app_refresh:
            _app_refresh = None
        if detach is not None:
            detach()
            if _story_detach is detach:
                _keep_native_load_visible()
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

    page.on_connect = connected
    page.on_disconnect = page.on_close = disconnected
    # Flet registers the initial route in page state without a route_change event.
    initial_lifecycle_revision = lifecycle_revision
    if optional_app and urlsplit(page.route).path in ("", "/"):
        page.route = "/app"
    await render_route(page.route)
    if lifecycle_revision != initial_lifecycle_revision:
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
        global _loop, _task, _story_detach, _menu_request, _resume_request, _save_refresh, _history_refresh, _reading_refresh
        global _app_detach, _app_refresh
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
            _keep_native_load_visible()
            if _story_detach is not None:
                _story_detach()
                _story_detach = None
            if _app_detach is not None:
                _app_detach()
                _app_detach = None
            _app_refresh = None
            _menu_request = None
            _resume_request = None
            _save_refresh = None
            _history_refresh = None
            _reading_refresh = None
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
    _keep_native_load_visible()
    loop, task, thread = _loop, _task, _thread
    if loop is not None and task is not None:
        loop.call_soon_threadsafe(task.cancel)
    if thread is not None and thread is not threading.current_thread():
        thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("Flet did not stop before Ren'Py shutdown")
    print("SDK_RUNNER_FLET_STOPPED", flush=True)
