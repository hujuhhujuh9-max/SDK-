"""Project-owned registration and navigation across the five examples."""


def register(api):
    from notebook_app import register as register_notebook
    from pulse_app import register as register_pulse
    from scale_setup import register_scale

    register_notebook(api)
    register_pulse(api)
    register_scale(api)
    api.register_screen("/app/lab", lab)


def app_home_view(page, navigate, status, request_story, *, route="/app", large_text=False):
    import flet as ft
    from app_home import app_home_view as sdk_home

    async def open_lab(event):
        await navigate("/app/lab")

    view = sdk_home(page, navigate, status, request_story, route=route, large_text=large_text)
    view.controls[0].controls.insert(0, ft.Button("Capabilities lab", on_click=open_lab))
    return view


def lab(ctx):
    import flet as ft

    def open_route(route):
        async def clicked(event):
            await ctx.navigate(route)
        return clicked

    return ft.View(route=ctx.route, bgcolor="#101b2b", padding=24, controls=[ft.Column([
        ft.Text("Project capabilities", size=28),
        ft.Text("Edit a notebook, try a project Flutter component, and start the 2D story journey."),
        ft.Button("Project notebook", on_click=open_route("/app/notebook")),
        ft.Button("Project pulse dial", on_click=open_route("/app/pulse")),
        ft.Button("2D Lab", on_click=open_route("/app/2d")),
        ft.Button("Application records", on_click=open_route("/app/records")),
        ft.Button("Saved games", on_click=open_route("/app/saves")),
        ft.TextButton("Back", on_click=ctx.back),
    ], scroll=ft.ScrollMode.AUTO)])
