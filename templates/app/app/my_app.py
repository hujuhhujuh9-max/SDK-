"""Replace this project home while keeping the SDK's story and data actions."""

import flet as ft

from app_home import app_home_view as sdk_app_home_view


def app_home_view(page, navigate, status, request_story, *, route="/app", large_text=False):
    view = sdk_app_home_view(page, navigate, status, request_story,
                             route=route, large_text=large_text)
    column = view.controls[0]
    column.controls[0].value = "My RenFletPy App"
    column.controls.insert(1, ft.Semantics(
        identifier="project-home-asset",
        content=ft.Image(src="runner.svg", width=180, height=48, fit=ft.BoxFit.CONTAIN)))
    return view
