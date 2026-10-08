"""Opt-in application views; the caller owns routes and native story commands."""

import inspect
import json
import logging

if __package__:
    from .application_data import DEFAULT_STORAGE_KEY
    from .form_list import DEFAULT_FIELDS, create_form_list_view
    from .story_ui import font_size, route_handler
else:
    from application_data import DEFAULT_STORAGE_KEY
    from form_list import DEFAULT_FIELDS, create_form_list_view
    from story_ui import font_size, route_handler


APP_ROUTE = "/app"
RECORDS_ROUTE = "/app/records"
STORY_ROUTE = "/app/story"
START_ROUTE = "/app/story/start"
CANCEL_ROUTE = "/app/story/cancel"
RESULT_ROUTE = "/app/story/result"


class StoryMailboxAdapter:
    """Map A's confirmed mailbox to screen callbacks without owning native flow.

    submit_story is the route owner's callback, which records the request's
    page/navigation origin. Do not bypass it with a global bridge call.
    """

    def __init__(self, read_mailbox_status, submit_story, *, read_busy=lambda: False,
                 story_title="Before the First Light"):
        self.read_mailbox_status = read_mailbox_status
        self.submit_story = submit_story
        self.read_busy = read_busy
        self.story_title = story_title

    def read_status(self):
        source = self.read_mailbox_status()
        state = source["state"]
        if state not in ("idle", "active", "suspended", "completed", "cancelled"):
            raise ValueError("Unknown confirmed mailbox state")
        other_busy = bool(self.read_busy())
        resumable = state in ("active", "suspended")
        result = None
        if state in ("completed", "cancelled"):
            payload = source["result"]
            if isinstance(payload, dict) and {
                "story_id", "run_id", "status", "phase", "result",
            }.issubset(payload):
                payload = payload["result"]  # B's handoff includes internal identity.
            values = dict(payload) if isinstance(payload, dict) else (
                {} if payload is None else {"Result": payload})
            result = {"status": state, "story_title": self.story_title,
                      "summary": source["message"], "values": values}
        return {
            # A supplies process-local session/request identities. Include the
            # entire detached snapshot so restored or terminal timelines cannot
            # authorize an event from a previously displayed state.
            "revision": json.dumps([source, other_busy], sort_keys=True, allow_nan=False),
            "loading": source.get("loading", False),
            "busy": source["busy"] or other_busy,
            "active": state == "active",
            "resume_available": resumable,
            "resume_reason": "No story is available to resume." if state == "idle" else (
                "This story has finished. Start a new story to continue." if not resumable else ""),
            "start_available": not resumable,
            "start_reason": "Finish the current story before starting another." if resumable else "",
            # A has Start/Resume/Return only; a Flet result publication is not
            # native cancellation, so do not offer a Cancel command here.
            "cancel_available": False,
            "cancel_reason": "Cancellation is unavailable for this story.",
            "story_title": self.story_title,
            "message": "Another operation is in progress…" if other_busy and not source["busy"] else source["message"],
            "error": source.get("error"),
            "result": result,
        }

    def request_story(self, action, revision):
        current = self.read_status()
        if (action not in ("start", "resume", "return")
                or current["revision"] != revision or not _available(action, current)):
            return False
        request_id = self.submit_story(action)
        return type(request_id) is int and request_id > 0


def _view(route, title, controls, large_text):
    import flet as ft

    return ft.View(route=route, bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Text(title, size=font_size(28, large_text), color="#f4f0e8"),
            *controls,
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])


def _available(action, status):
    if status["loading"] or status["busy"]:
        return False
    if action == "resume":
        return status["resume_available"]
    if action == "start":
        return status.get("start_available", True)
    if action == "cancel":
        return status["active"] and status.get("cancel_available", True)
    if action == "return":
        return status["active"]
    return True


class _StoryActions:
    """Guard this view's events while the command owner publishes a new snapshot."""

    def __init__(self, page, navigate, read_status, request_story, refresh_status):
        import flet as ft

        self.page = page
        self.navigate = navigate
        self.read_status = read_status
        self.request_story = request_story
        self.status = dict(read_status())
        self.locked = False
        self.buttons = []
        message = self.status.get("message", "")
        if self.status["loading"]:
            message = message or "Loading story status…"
        elif self.status["busy"]:
            message = message or "Story request in progress…"
        else:
            message = self.status.get("error") or message
        self.message = ft.Text(message, color="#b9c5d0")
        self.progress = ft.ProgressRing(visible=self.status["loading"] or self.status["busy"])

        async def reload_status(event):
            if self.reload.disabled:
                return
            self.locked = True
            for button in self.buttons:
                button.disabled = True
            self.reload.disabled = True
            self.message.value = "Loading story status…"
            self.progress.visible = True
            self.page.update()
            try:
                result = refresh_status()
                if inspect.isawaitable(result):
                    await result
            except Exception:
                logging.exception("Application story status refresh failed")
                self.fail("Story status could not be loaded. Try Reload again.")

        self.reload = ft.TextButton("Reload story status", visible=bool(self.status.get("error")),
                                    disabled=self.status["loading"] or self.status["busy"],
                                    on_click=reload_status)

    def fail(self, message):
        self.locked = True
        for button in self.buttons:
            button.disabled = True
        self.message.value = message
        self.progress.visible = False
        self.reload.visible = True
        self.reload.disabled = False
        self.page.update()

    def button(self, label, action, *, confirmation_route=None):
        import flet as ft

        async def clicked(event):
            if self.locked or not _available(action, self.status):
                return
            current = dict(self.read_status())
            if current["revision"] != self.status["revision"]:
                self.fail("Story status changed. Reload before continuing.")
                return
            if not _available(action, current):
                return
            if confirmation_route is not None:
                # Replacing active or resumable progress and cancelling need
                # confirmation. No native request is submitted here.
                if action == "cancel" or current["active"] or current["resume_available"]:
                    await self.navigate(confirmation_route)
                    return
            self.locked = True
            for button in self.buttons:
                button.disabled = True
            self.message.value = {
                "start": "Starting story…", "resume": "Resuming story…",
                "return": "Returning to app…", "cancel": "Cancelling story…",
            }[action]
            self.progress.visible = True
            self.reload.visible = False
            self.page.update()
            try:
                accepted = self.request_story(action, current["revision"])
            except Exception:
                logging.exception("Application story request failed")
                self.fail("Story request failed. Reload before trying again.")
                return
            if accepted is not True:
                self.fail("Story request was not accepted. Reload before continuing.")
            # Acceptance is only queue acceptance. The owner publishes the
            # native outcome and decides when to change presentation/routes.

        button = ft.Button(label, on_click=clicked, disabled=not _available(action, self.status))
        self.buttons.append(button)
        return button

    def feedback(self):
        import flet as ft

        return [ft.Row([self.progress, self.message], wrap=True), self.reload]


def app_home_view(page, navigate, read_status, request_story, *, refresh_status, title="Application",
                  story_title=None, route=APP_ROUTE, large_text=False):
    """Build an unmounted home from a plain story snapshot and command callbacks."""
    import flet as ft

    actions = _StoryActions(page, navigate, read_status, request_story, refresh_status)
    status = actions.status
    story_title = story_title or status.get("story_title") or "Before the First Light"
    controls = [
        ft.Button("Application records", on_click=route_handler(navigate, RECORDS_ROUTE)),
        ft.Text(story_title, size=font_size(22, large_text), color="#b9d7de"),
        ft.Row([
            actions.button("Start story", "start", confirmation_route=START_ROUTE),
            actions.button("Resume story", "resume"),
        ], wrap=True),
    ]
    if not status["loading"] and not status["resume_available"]:
        controls.append(ft.Text(status.get("resume_reason") or "No story is available to resume.",
                                color="#b9c5d0"))
    if status.get("start_available") is False and status.get("start_reason"):
        controls.append(ft.Text(status["start_reason"], color="#b9c5d0"))
    controls.extend([
        *actions.feedback(),
        ft.TextButton("Story controls", on_click=route_handler(navigate, STORY_ROUTE)),
    ])
    if status.get("result") is not None:
        controls.append(ft.TextButton("View story result", on_click=route_handler(navigate, RESULT_ROUTE)))
    return _view(route, title, controls, large_text)


def app_story_view(page, navigate, read_status, request_story, *, refresh_status, route=STORY_ROUTE,
                   large_text=False):
    """Controls for the one optional story session, including native return."""
    import flet as ft

    actions = _StoryActions(page, navigate, read_status, request_story, refresh_status)
    controls = ([ft.Text(actions.status["story_title"], size=font_size(22, large_text), color="#b9d7de")]
                if actions.status.get("story_title") else [])
    controls.extend([
        ft.Row([
            actions.button("Resume story", "resume"),
            actions.button("Start from beginning", "start", confirmation_route=START_ROUTE),
        ], wrap=True),
    ])
    if not actions.status["loading"] and not actions.status["resume_available"]:
        controls.append(ft.Text(actions.status.get("resume_reason") or "No story is available to resume.",
                                color="#b9c5d0"))
    if actions.status.get("start_available") is False and actions.status.get("start_reason"):
        controls.append(ft.Text(actions.status["start_reason"], color="#b9c5d0"))
    if actions.status["active"]:
        controls.append(actions.button("Return to app", "return"))
        if actions.status.get("cancel_available", True):
            controls.append(actions.button("Cancel story", "cancel", confirmation_route=CANCEL_ROUTE))
    else:
        controls.append(ft.TextButton("Return to app", on_click=route_handler(navigate, APP_ROUTE)))
    controls.extend(actions.feedback())
    if actions.status.get("result") is not None:
        controls.append(ft.TextButton("View story result", on_click=route_handler(navigate, RESULT_ROUTE)))
    return _view(route, "Story controls", controls, large_text)


def app_confirmation_view(page, navigate, read_status, request_story, *, action, refresh_status,
                          route=None, large_text=False):
    """Confirm restarting or cancelling; Back/Keep submits no story command."""
    import flet as ft

    if action not in ("start", "cancel"):
        raise ValueError("Only starting again and cancelling need confirmation")
    actions = _StoryActions(page, navigate, read_status, request_story, refresh_status)
    if action == "start":
        heading = "Start this story again?"
        explanation = "Current story progress will be replaced. Your application records are kept."
        label = "Start again"
        route = route or START_ROUTE
    else:
        heading = "Cancel this story?"
        explanation = "End the current story session and return to the app. Your application records are kept."
        label = "Confirm cancellation"
        route = route or CANCEL_ROUTE
    return _view(route, heading, [
        ft.Text(explanation, color="#b9c5d0"),
        *([ft.Text(actions.status[f"{action}_reason"], color="#b9c5d0")]
          if actions.status.get(f"{action}_available") is False and actions.status.get(f"{action}_reason") else []),
        actions.button(label, action),
        ft.TextButton("Keep current story", on_click=route_handler(navigate, STORY_ROUTE)),
        *actions.feedback(),
    ], large_text)


def app_result_view(navigate, result, *, route=RESULT_ROUTE, large_text=False):
    """Display a plain native result without consuming it or writing app data."""
    import flet as ft

    controls = []
    if result is None:
        title = "Story result"
        controls.append(ft.Text("No story result yet.", color="#b9c5d0"))
    else:
        titles = {"completed": "Story completed", "cancelled": "Story cancelled", "failed": "Story failed"}
        if result.get("status") not in titles:
            raise ValueError("Unknown story result status")
        title = titles[result["status"]]
        if result.get("story_title"):
            controls.append(ft.Text(result["story_title"], size=font_size(22, large_text), color="#b9d7de"))
        if result.get("summary"):
            controls.append(ft.Text(result["summary"], color="#f4f0e8"))
        for label, value in result.get("values", {}).items():
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)
            controls.append(ft.Text(f"{label}: {value}", color="#b9c5d0"))
    controls.extend([
        ft.Button("Return to app", on_click=route_handler(navigate, APP_ROUTE)),
        ft.TextButton("Application records", on_click=route_handler(navigate, RECORDS_ROUTE)),
    ])
    return _view(route, title, controls, large_text)


async def create_app_records_view(page, navigate, *, route=RECORDS_ROUTE,
                                  title="Application records", fields=DEFAULT_FIELDS,
                                  storage_key=DEFAULT_STORAGE_KEY):
    """Reuse the existing records view/store; do not install any route handlers."""
    return await create_form_list_view(
        page, route=route, title=title, fields=fields, storage_key=storage_key,
        on_back=route_handler(navigate, APP_ROUTE), back_label="Return to app",
    )
