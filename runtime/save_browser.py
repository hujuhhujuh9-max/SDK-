"""Reusable Flet save browser; it submits plain intent, never native calls."""

from datetime import datetime

if __package__:
    from .save_slots import save_name
else:
    from save_slots import save_name


def create_save_browser(page, *, route, on_back, get_status, request_save,
                        is_current, large_text=False, state=None):
    import flet as ft

    def size(value):
        return round(value * 1.25) if large_text else value
    state = {} if state is None else state
    name = ft.TextField(label="Save name", value=state.get("name", ""), max_length=80,
                        hint_text="For example: Before the lighthouse choice")
    message = ft.Text(color="#b9c5d0")
    writable_hint = ft.Text("Start or resume a story to create or overwrite a checkpoint.",
                            color="#b9c5d0")
    entries = ft.Column(spacing=12)
    confirmation = ft.Column(visible=False, spacing=10)
    pending = None

    def capture_state():
        # Confirmations are transient and must revalidate the current slot list.
        state["name"] = name.value or ""

    def changed(event):
        if is_current():
            capture_state()
    name.on_change = changed

    def status():
        return get_status()

    def submit(action, revision, **options):
        if not is_current():
            return False
        accepted = request_save(action, revision=revision, **options)
        if not accepted:
            message.value = "Your save list changed or an operation is running. Try again."
            page.update()
        return accepted

    async def create(event):
        if not is_current() or status()["busy"]:
            return
        try:
            title = save_name(name.value)
        except ValueError as error:
            name.error = str(error)
            page.update()
            return
        name.error = None
        capture_state()
        submit("create", status()["revision"], name=title)

    async def refresh(event):
        if is_current():
            request_save("list")

    async def cancel(event):
        nonlocal pending
        if is_current():
            pending = None
            render()
            page.update()

    async def confirm(event):
        nonlocal pending
        if pending is None or not is_current():
            return
        action, row, revision = pending
        if submit(action, revision, slot=row["slot"]):
            pending = None
            render()
            page.update()

    def choose(action, row, revision):
        async def clicked(event):
            nonlocal pending
            if not is_current() or status()["busy"] or status()["revision"] != revision:
                return
            pending = (action, row, revision)
            render()
            page.update()
        return clicked

    create_button = ft.Button("Create save", on_click=create)
    refresh_button = ft.TextButton("Refresh", on_click=refresh)
    confirm_button = ft.Button("Load save", on_click=confirm)
    cancel_button = ft.TextButton("Cancel", on_click=cancel)
    confirm_text = ft.Text(size=size(18), color="#f4f0e8")
    confirmation.controls = [confirm_text, ft.Row([confirm_button, cancel_button], wrap=True)]

    def render():
        nonlocal pending
        current = status()
        busy, revision = current["busy"], current["revision"]
        name.disabled = busy or not current["can_save"]
        writable_hint.visible = not current["can_save"]
        create_button.disabled = busy or not current["ready"] or not current["can_save"]
        refresh_button.disabled = busy
        message.value = current["message"]
        if pending is not None and pending[2] != revision:
            pending = None
        confirmation.visible = pending is not None
        if pending is not None:
            action, row, _ = pending
            wording = {"load": "Load this save? Unsaved story progress will be replaced.",
                       "overwrite": "Replace this save with your current story progress?",
                       "delete": "Delete this save permanently?"}
            confirm_text.value = row["name"] + "\n" + wording[action]
            confirm_button.content = {"load": "Load save", "overwrite": "Overwrite save",
                                      "delete": "Delete save"}[action]
            confirm_button.disabled = cancel_button.disabled = busy
        cards = []
        for row in current["slots"]:
            when = datetime.fromtimestamp(row["mtime"]).strftime("%Y-%m-%d %H:%M")
            cards.append(ft.Container(content=ft.Column([
                ft.Text(row["name"], size=size(20), color="#f4f0e8", weight=ft.FontWeight.W_600),
                ft.Text(when + (" · " + row["scene"] if row["scene"] else ""), color="#b9c5d0"),
                ft.Row([
                    ft.Button("Load", on_click=choose("load", row, revision),
                              disabled=busy or not row["loadable"]),
                    ft.TextButton("Overwrite", on_click=choose("overwrite", row, revision),
                                  disabled=busy or not current["can_save"]),
                    ft.TextButton("Delete", on_click=choose("delete", row, revision), disabled=busy),
                ], wrap=True),
            ], spacing=8), padding=16, border_radius=12, bgcolor="#1b2838"))
        entries.controls = cards or [ft.Text("No named saves yet." if current["ready"] else "Reading saved games…")]

    view = ft.View(route=route, bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Row([ft.Text("Saved games", size=size(28), expand=True, color="#f4f0e8"),
                    ft.TextButton("Back", on_click=on_back)]),
            ft.Text("Keep several named places in your story. Quick save and recovery stay separate.",
                    color="#b9c5d0"),
            name, ft.Row([create_button, refresh_button], wrap=True), writable_hint,
            message, confirmation, entries,
        ], spacing=16, expand=True, scroll=ft.ScrollMode.AUTO),
    ])
    view._runner_capture_state = capture_state

    def update():
        if is_current():
            render()
            page.update()

    render()
    return view, update
