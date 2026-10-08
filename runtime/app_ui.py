"""Optional app screens; native story operations are confirmed by the bridge."""

if __package__:
    from .story_ui import route_handler
else:
    from story_ui import route_handler


def home_view(navigate, status):
    import flet as ft
    return ft.View(route="/app", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Text("Application home", size=30, color="#f4f0e8"),
            ft.Text(status["message"], color="#b9c5d0"),
            ft.Button("Story", on_click=route_handler(navigate, "/app/story")),
            ft.Button("Application records", on_click=route_handler(navigate, "/app/records")),
            ft.Button("Reading settings", on_click=route_handler(navigate, "/app/settings")),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])


def story_view(navigate, status, submit, busy):
    import flet as ft
    resumable = status["state"] in ("active", "suspended")

    async def clicked(event):
        submit("resume" if resumable else "start")

    return ft.View(route="/app/story", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Row([
                ft.Text("Story", size=30, color="#f4f0e8", expand=True),
                ft.TextButton("Back", on_click=route_handler(navigate, "/app")),
            ]),
            ft.Text("Before the First Light", size=24, color="#b9d7de"),
            ft.Text("Story status: " + status["state"], color="#b9c5d0"),
            ft.Text(status["message"], color="#b9c5d0"),
            ft.Button("Resume story" if resumable else "Start story", on_click=clicked,
                      disabled=busy),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])
