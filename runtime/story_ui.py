"""Flet dialogue and menus for the shared Ren'Py story."""

if __package__:
    from .renfletpy import story
else:
    from renfletpy import story


def route_handler(navigate, route):
    async def clicked(event):
        await navigate(route)
    return clicked


def dialogue_controls(navigate, dialogue):
    import flet as ft

    controls = [ft.Row([
        ft.Text(dialogue.speaker if dialogue else "", color="#b9d7de", size=14,
                weight=ft.FontWeight.W_600, expand=True),
        ft.TextButton("Menu", on_click=route_handler(navigate, "/menu")),
    ])]
    if dialogue is None:
        controls.append(ft.Text("Opening the scene…", color="#f4f0e8", size=20))
    else:
        controls.append(ft.Text(dialogue.text, color="#f4f0e8", size=20))

        def choose(choice_id):
            # Capture this line's revision. A delayed or double tap can never
            # advance a newer line or choose a different branch twice.
            async def clicked(event):
                story.choose(dialogue.revision, choice_id)
            return clicked

        controls.append(ft.Row([
            ft.Button(label, on_click=choose(choice_id),
                      disabled=dialogue.selected is not None,
                      bgcolor="#b9d7de", color="#101b2b")
            for choice_id, label in dialogue.choices
        ], wrap=True, spacing=10, run_spacing=10))
    return [ft.Container(
        content=ft.Column(controls, spacing=14, expand=True, scroll=ft.ScrollMode.AUTO),
        padding=20, border_radius=20, bgcolor="#ed101b2b", expand=True,
    )]


def menu_view(navigate, quit_runner):
    import flet as ft

    return ft.View(route="/menu", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Text("Paused", size=30, color="#f4f0e8"),
            ft.Text("Your place in the scene is kept while this menu is open.",
                    color="#b9c5d0"),
            ft.Button("Resume", on_click=route_handler(navigate, "/")),
            ft.TextButton("Transcript", on_click=route_handler(navigate, "/history")),
            ft.TextButton("Replay scene", on_click=route_handler(navigate, "/restart")),
            ft.TextButton("Device diagnostics", on_click=route_handler(navigate, "/diagnostics")),
            ft.TextButton("Quit", on_click=quit_runner),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])


def transcript_view(navigate):
    import flet as ft

    entries = []
    for dialogue in story.history():
        lines = []
        if dialogue.speaker:
            lines.append(ft.Text(dialogue.speaker, color="#b9d7de", size=14))
        lines.append(ft.Text(dialogue.text, color="#f4f0e8", size=18))
        if dialogue.selected is not None:
            lines.append(ft.Text("→ " + dict(dialogue.choices)[dialogue.selected],
                                 color="#b9d7de", size=14))
        entries.append(ft.Container(content=ft.Column(lines, spacing=8),
                                    padding=16, border_radius=12, bgcolor="#1b2838"))
    return ft.View(route="/history", bgcolor="#101b2b", padding=24, controls=[
        ft.Row([ft.Text("Transcript", size=28, color="#f4f0e8", expand=True),
                ft.TextButton("Back", on_click=route_handler(navigate, "/menu"))]),
        ft.Column(entries or [ft.Text("The scene has not started yet.")],
                  expand=True, spacing=12, scroll=ft.ScrollMode.AUTO),
    ])


def restart_view(navigate):
    import flet as ft

    async def replay(event):
        story.request_restart()
        await navigate("/")

    return ft.View(route="/restart", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Text("Replay this scene?", size=28, color="#f4f0e8"),
            ft.Text("The current choices and transcript will be cleared.", color="#b9c5d0"),
            ft.Button("Replay", on_click=replay),
            ft.TextButton("Keep playing", on_click=route_handler(navigate, "/")),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])
