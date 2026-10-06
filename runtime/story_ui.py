"""Flet interludes and menus; ordinary dialogue stays in Ren'Py."""

if __package__:
    from .renfletpy import STAR_ORDER, story
else:
    from renfletpy import STAR_ORDER, story


def route_handler(navigate, route):
    async def clicked(event):
        await navigate(route)
    return clicked


def dialogue_controls(navigate, dialogue):
    import flet as ft

    if dialogue is None:
        return []
    controls = [ft.Row([
        ft.Text(dialogue.speaker, color="#b9d7de", size=24,
                weight=ft.FontWeight.W_600, expand=True),
        ft.TextButton("Menu", on_click=route_handler(navigate, "/menu")),
    ])]
    if dialogue.kind == "star_map":
        def tap(star_id):
            async def clicked(event):
                story.tap_star(dialogue.revision, star_id)
            return clicked

        def star(star_id, label):
            return ft.Button(label, on_click=tap(star_id), height=72,
                             disabled=dialogue.selected is not None or star_id in dialogue.progress,
                             bgcolor="#42685e" if star_id in dialogue.progress else "#294559",
                             color="#f4f0e8")

        controls.extend([
            ft.Text(dialogue.text, color="#f4f0e8", size=20),
            ft.Row([ft.Text("✦", color="#b9d7de", size=32),
                    ft.Text("·", color="#b9d7de", size=20),
                    ft.Text("✧", color="#b9d7de", size=32)],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([star(*STAR_ORDER[0])], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([star(*STAR_ORDER[2]), star(*STAR_ORDER[1])],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(f"Stars connected: {len(dialogue.progress)} / 3", color="#b9d7de", size=18),
            ft.Text(dialogue.feedback or "Tap the stars in the order above.", color="#f4f0e8"),
        ])
        choices = (("skipped", "Skip minigame"),)
    else:
        controls.append(ft.Text(dialogue.text, color="#f4f0e8", size=20))
        choices = dialogue.choices

    def choose(choice_id):
        async def clicked(event):
            story.choose(dialogue.revision, choice_id)
        return clicked

    controls.append(ft.Row([
        ft.Button(label, on_click=choose(choice_id),
                  disabled=dialogue.selected is not None,
                  bgcolor="#b9d7de", color="#101b2b")
        for choice_id, label in choices
    ], wrap=True, spacing=10, run_spacing=10))
    return [ft.Container(
        content=ft.Column(controls, spacing=14, expand=True, scroll=ft.ScrollMode.AUTO),
        padding=20, border_radius=20, bgcolor="#101b2b", expand=True,
    )]


def menu_view(navigate, quit_runner, save_status, request_save):
    import flet as ft

    def save_action(action):
        async def clicked(event):
            request_save(action)
        return clicked

    return ft.View(route="/menu", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Text("Paused", size=30, color="#f4f0e8"),
            ft.Text("Your place in the scene is kept while this menu is open.",
                    color="#b9c5d0"),
            ft.Button("Resume", on_click=route_handler(navigate, "/"), disabled=save_status["busy"]),
            ft.Row([
                ft.Button("Quick save", on_click=save_action("save"), disabled=save_status["busy"]),
                ft.Button("Quick load", on_click=save_action("load"),
                          disabled=save_status["busy"] or not save_status["available"]),
            ], wrap=True),
            ft.Text(save_status["message"], color="#b9c5d0"),
            ft.TextButton("Story history", on_click=route_handler(navigate, "/history")),
            ft.TextButton("Replay story", on_click=route_handler(navigate, "/restart"),
                          disabled=save_status["busy"]),
            ft.TextButton("Device diagnostics", on_click=route_handler(navigate, "/diagnostics")),
            ft.TextButton("Quit", on_click=quit_runner, disabled=save_status["busy"]),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])


def transcript_view(navigate, transcript):
    import flet as ft

    entries = []
    for speaker, text, result in transcript:
        lines = []
        if speaker:
            lines.append(ft.Text(speaker, color="#b9d7de", size=14))
        lines.append(ft.Text(text, color="#f4f0e8", size=18))
        if result:
            lines.append(ft.Text("→ " + result,
                                 color="#b9d7de", size=14))
        entries.append(ft.Container(content=ft.Column(lines, spacing=8),
                                    padding=16, border_radius=12, bgcolor="#1b2838"))
    return ft.View(route="/history", bgcolor="#101b2b", padding=24, controls=[
        ft.Row([ft.Text("Story history", size=28, color="#f4f0e8", expand=True),
                ft.TextButton("Back", on_click=route_handler(navigate, "/menu"))]),
        ft.Column(entries or [ft.Text("Your story will appear here as you play.")],
                  expand=True, spacing=12, scroll=ft.ScrollMode.AUTO),
    ])


def restart_view(navigate, request_restart, busy):
    import flet as ft

    async def replay(event):
        if request_restart():
            await navigate("/")

    return ft.View(route="/restart", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Text("Replay this story?", size=28, color="#f4f0e8"),
            ft.Text("Start from the beginning with a fresh history. Your quick save is kept.", color="#b9c5d0"),
            ft.Button("Replay", on_click=replay, disabled=busy),
            ft.TextButton("Keep playing", on_click=route_handler(navigate, "/")),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])
