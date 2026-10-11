"""Application-owned registrations and home for the opt-in 2D project."""


def register_scale(api):
    from scale_activity import register_scale_activity
    from scale_ui import register_scale_screens
    from rive_activity import register_rive_activity

    register_scale_screens(api)
    register_scale_activity(api)
    register_rive_activity()


def app_home_view(page, navigate, status, request_story, *, route="/app", large_text=False):
    import flet as ft
    from app_home import app_home_view as sdk_home

    async def lab(event):
        await navigate("/app/2d")

    view = sdk_home(page, navigate, status, request_story, route=route, large_text=large_text)
    view.controls[0].controls.insert(0, ft.Button("2D Lab", on_click=lab))
    return view
