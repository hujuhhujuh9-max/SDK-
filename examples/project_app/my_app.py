"""Project-owned pages: edit a notebook, open a detail link, start/return a story."""

import flet as ft
from app_home import app_home_view as sdk_home


def initial_notebook():
    return {"draft": "", "selected": "mira", "entries": {
        "lighthouse": "The light comes on at dusk.", "balcony": "Mira watches the summer triangle."}}


def register(api):
    # No SDK routes are edited. State is shared deliberately between these views.
    api.register_screen("/app/notebook", notebook, state_factory=initial_notebook,
                        state_key="project.notebook", aliases=("/notebook",))
    api.register_screen("/app/entries/{entry_id}", entry, state_factory=initial_notebook,
                        state_key="project.notebook", parent="/app/notebook")


def app_home_view(page, navigate, status, request_story, *, route="/app", large_text=False):
    view = sdk_home(page, navigate, status, request_story, route=route, large_text=large_text)

    async def open_notebook(event):
        await navigate("/app/notebook")

    view.controls[0].controls.insert(1, ft.Button("Open notebook", on_click=open_notebook))
    return view


def notebook(ctx):
    draft = ft.TextField(label="Notebook draft", value=ctx.state["draft"], multiline=True)
    selection = ft.Text("Selected: " + ctx.state["selected"])
    message = ft.Text(ctx.story_status["message"])

    def changed(event):
        if ctx.is_current():
            ctx.state["draft"] = draft.value or ""

    draft.on_change = changed

    def select(name):
        async def clicked(event):
            if ctx.is_current():
                ctx.state["selected"] = name
                selection.value = "Selected: " + name
                ctx.page.update()
        return clicked

    async def details(event):
        await ctx.navigate("/app/entries/lighthouse?source=notebook")

    async def start(event):
        # Capture even if a native input patch arrived just before the click.
        if ctx.is_current():
            ctx.state["draft"] = draft.value or ""
            status = ctx.story_status
            if status["resume_available"]:
                async def replace(event):
                    ctx.dismiss_dialog()
                    ctx.start_story(replace=True)

                async def cancel(event):
                    ctx.dismiss_dialog()

                ctx.show_dialog(ft.AlertDialog(
                    title=ft.Text("Start a new story?"), content=ft.Text("Replace current story progress?"),
                    actions=[ft.Button("Start new story", on_click=replace),
                             ft.TextButton("Cancel", on_click=cancel)]))
            else:
                ctx.start_story()

    async def resume(event):
        ctx.resume_story()

    return ft.View(route=ctx.route, bgcolor="#101b2b", padding=24, controls=[ft.Column([
        ft.Row([ft.Text("Project notebook", size=28, expand=True), ft.TextButton("Back", on_click=ctx.back)]),
        draft, selection, ft.Row([ft.Button("Select Mira", on_click=select("mira")),
                                ft.Button("Select Rowan", on_click=select("rowan"))], wrap=True),
        ft.Button("Open lighthouse entry", on_click=details),
        ft.Row([ft.Button("Start notebook story", on_click=start, disabled=ctx.story_status["busy"]),
                ft.Button("Resume notebook story", on_click=resume,
                          disabled=ctx.story_status["busy"] or not ctx.story_status["resume_available"])], wrap=True),
        message,
    ], expand=True, scroll=ft.ScrollMode.AUTO)])


def entry(ctx):
    text = ctx.state["entries"].get(ctx.params["entry_id"], "Entry not found.")
    return ft.View(route=ctx.route, bgcolor="#101b2b", padding=24, controls=[ft.Column([
        ft.Text("Entry: " + ctx.params["entry_id"], size=28), ft.Text(text),
        ft.Text("Draft: " + ctx.state["draft"]), ft.Text("Selected: " + ctx.state["selected"]),
        ft.TextButton("Back", on_click=ctx.back),
    ])])
