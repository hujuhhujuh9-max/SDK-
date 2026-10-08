"""An optional Flet app home; its caller owns routes and native story execution."""

import logging

if __package__:
    from .story_ui import font_size
else:
    from story_ui import font_size


def app_home_view(page, navigate, status, request_story, *, route="/app", large_text=False):
    """Build a View without mounting it, navigating or registering services.

    status is a plain native snapshot, or None while it is being discovered.
    request_story(action, revision, *, replace=False) synchronously queues a
    command and returns bool acceptance. Only native acknowledgement may change
    the route. Call again with fresh status to release a submitted UI command.
    """
    import flet as ft

    snapshot = {} if status is None else dict(status)
    revision = snapshot.get("revision")
    initialized = (snapshot.get("story_id") == "app-recipe"
                   and type(revision) is int
                   and snapshot.get("phase") in ("ready", "active", "completed"))
    busy = not initialized or bool(snapshot.get("busy", True))
    resume_kind = snapshot.get("resume_kind", "unavailable")
    can_resume = bool(snapshot.get("resume_available")) and resume_kind in ("live", "saved")
    replaces_progress = (snapshot.get("phase") == "active" or can_resume)
    submitted = False
    confirming = False
    message = ft.Text(snapshot.get("message", "Getting the story ready…"),
                      color="#b9c5d0", size=font_size(16, large_text))
    progress = ft.ProgressRing(visible=busy, semantics_label="Waiting for the story")

    def update_actions():
        start_button.disabled = busy or submitted or confirming
        resume_button.disabled = busy or submitted or confirming or not can_resume
        records_button.disabled = busy or submitted
        confirm_button.disabled = busy or submitted
        cancel_button.disabled = busy or submitted
        confirmation.visible = confirming
        progress.visible = busy or submitted

    def submit(action, *, replace=False):
        nonlocal submitted, confirming
        if busy or submitted or (action == "resume" and not can_resume):
            return
        # Capture the rendered revision and latch before calling the mailbox.
        # Late or repeated control events must not enqueue another command.
        submitted = True
        confirming = False
        try:
            accepted = request_story(action, revision, replace=replace)
        except Exception:
            logging.exception("App story request could not be submitted")
            submitted = False
            message.value = "The story request could not be sent. Try again."
        else:
            if accepted:
                message.value = "Starting story…" if action == "start" else "Resuming story…"
            else:
                submitted = False
                message.value = "The story status changed. Wait for its update and try again."
        update_actions()
        page.update()

    async def start(event):
        nonlocal confirming
        if busy or submitted or confirming:
            return
        if replaces_progress:
            confirming = True
            update_actions()
            page.update()
        else:
            submit("start")

    async def confirm(event):
        if confirming:
            submit("start", replace=True)

    async def cancel(event):
        nonlocal confirming
        if busy or submitted or not confirming:
            return
        confirming = False
        update_actions()
        page.update()

    async def resume(event):
        if not confirming:
            submit("resume")

    async def records(event):
        if not busy and not submitted:
            await navigate("/app/records")

    start_button = ft.Button("Start story", on_click=start)
    resume_button = ft.Button("Resume story", on_click=resume)
    records_button = ft.Button("Application records", on_click=records)
    confirm_button = ft.Button("Start new story", on_click=confirm)
    cancel_button = ft.TextButton("Cancel", on_click=cancel)
    confirmation = ft.Column([
        ft.Text("Start again from the beginning?", size=font_size(20, large_text)),
        ft.Text("This replaces your current story progress.", color="#b9c5d0"),
        ft.Row([confirm_button, cancel_button], wrap=True),
    ], visible=False, spacing=12)
    if can_resume and resume_kind == "live":
        resume_note = "Your story is kept in this session. Quick save in the story menu keeps a saved place."
    elif can_resume and resume_kind == "saved":
        resume_note = "Resume from your saved place."
    else:
        resume_note = "Start a short story at the lighthouse."

    completion = []
    result = snapshot.get("result")
    if (snapshot.get("phase") == "completed" and isinstance(result, dict)
            and result.get("story_id") == snapshot.get("story_id")
            and result.get("outcome") == "completed" and isinstance(result.get("value"), str)):
        completion = [ft.Text("Story complete", size=font_size(22, large_text)),
                      ft.Text(result["value"], size=font_size(18, large_text))]
    update_actions()
    return ft.View(route=route, bgcolor="#101b2b", padding=24, controls=[ft.Column([
        ft.Text("App home", size=font_size(30, large_text), color="#f4f0e8"),
        records_button,
        ft.Text("The Lighthouse Note", size=font_size(24, large_text), color="#b9d7de"),
        ft.Text(resume_note, size=font_size(16, large_text), color="#b9c5d0"),
        ft.Row([start_button, resume_button], wrap=True),
        confirmation,
        ft.Row([progress, message], wrap=True),
        *completion,
    ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO)])
