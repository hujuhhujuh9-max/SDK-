"""Flet interludes and menus; ordinary dialogue stays in Ren'Py."""

if __package__:
    from .renfletpy import STAR_ORDER, story
else:
    from renfletpy import STAR_ORDER, story


def route_handler(navigate, route):
    async def clicked(event):
        await navigate(route)
    return clicked


def font_size(size, large_text):
    return round(size * 1.25) if large_text else size


def dialogue_controls(navigate, dialogue, large_text=False):
    import flet as ft

    if dialogue is None:
        return []
    controls = [ft.Row([
        ft.Text(dialogue.speaker, color="#b9d7de", size=font_size(24, large_text),
                weight=ft.FontWeight.W_600, expand=True),
        ft.TextButton("Menu", on_click=route_handler(navigate, "/menu")),
    ])]
    if dialogue.kind == "star_map":
        def tap(star_id):
            async def clicked(event):
                story.tap_star(dialogue.revision, star_id)
            return clicked

        def star(star_id, label):
            return ft.Button(label, on_click=tap(star_id), height=88 if large_text else 72,
                             disabled=dialogue.selected is not None or star_id in dialogue.progress,
                             bgcolor="#42685e" if star_id in dialogue.progress else "#294559",
                             color="#f4f0e8")

        controls.extend([
            ft.Text(dialogue.text, color="#f4f0e8", size=font_size(20, large_text)),
            ft.Row([ft.Text("✦", color="#b9d7de", size=font_size(32, large_text)),
                    ft.Text("·", color="#b9d7de", size=font_size(20, large_text)),
                    ft.Text("✧", color="#b9d7de", size=font_size(32, large_text))],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Row([star(*STAR_ORDER[0])], alignment=ft.MainAxisAlignment.CENTER),
            ft.Row([star(*STAR_ORDER[2]), star(*STAR_ORDER[1])],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Text(f"Stars connected: {len(dialogue.progress)} / 3", color="#b9d7de", size=font_size(18, large_text)),
            ft.Text(dialogue.feedback or "Tap the stars in the order above.", color="#f4f0e8"),
        ])
        choices = (("skipped", "Skip minigame"),)
    else:
        controls.append(ft.Text(dialogue.text, color="#f4f0e8", size=font_size(20, large_text)))
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


def menu_view(navigate, quit_runner, save_status, request_save, large_text=False):
    import flet as ft

    def save_action(action):
        async def clicked(event):
            request_save(action)
        return clicked

    return ft.View(route="/menu", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Text("Paused", size=font_size(30, large_text), color="#f4f0e8"),
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
            ft.TextButton("Reading settings", on_click=route_handler(navigate, "/settings")),
            ft.TextButton("Replay story", on_click=route_handler(navigate, "/restart"),
                          disabled=save_status["busy"]),
            ft.TextButton("Device diagnostics", on_click=route_handler(navigate, "/diagnostics")),
            ft.TextButton("Quit", on_click=quit_runner, disabled=save_status["busy"]),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])


def transcript_view(navigate, transcript, large_text=False):
    import flet as ft

    entries = []
    for speaker, text, result in transcript:
        lines = []
        if speaker:
            lines.append(ft.Text(speaker, color="#b9d7de", size=font_size(14, large_text)))
        lines.append(ft.Text(text, color="#f4f0e8", size=font_size(18, large_text)))
        if result:
            lines.append(ft.Text("→ " + result,
                                 color="#b9d7de", size=font_size(14, large_text)))
        entries.append(ft.Container(content=ft.Column(lines, spacing=8),
                                    padding=16, border_radius=12, bgcolor="#1b2838"))
    return ft.View(route="/history", bgcolor="#101b2b", padding=24, controls=[
        ft.Row([ft.Text("Story history", size=font_size(28, large_text), color="#f4f0e8", expand=True),
                ft.TextButton("Back", on_click=route_handler(navigate, "/menu"))]),
        ft.Column(entries or [ft.Text("Your story will appear here as you play.")],
                  expand=True, spacing=12, scroll=ft.ScrollMode.AUTO),
    ])


def restart_view(navigate, request_restart, busy, large_text=False):
    import flet as ft

    async def replay(event):
        if request_restart():
            await navigate("/")

    return ft.View(route="/restart", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Text("Replay this story?", size=font_size(28, large_text), color="#f4f0e8"),
            ft.Text("Start from the beginning with a fresh history. Your quick save is kept.", color="#b9c5d0"),
            ft.Button("Replay", on_click=replay, disabled=busy),
            ft.TextButton("Keep playing", on_click=route_handler(navigate, "/")),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])


def settings_view(navigate, status, request_reading):
    import flet as ft

    large_text = status["large_text"]

    def choice(name, value, label):
        async def clicked(event):
            request_reading(name, value)
        selected = status[name] == value
        return ft.Button(label, on_click=clicked, disabled=status["busy"] or selected,
                         bgcolor="#42685e" if selected else "#294559", color="#f4f0e8")

    return ft.View(route="/settings", bgcolor="#101b2b", padding=24, controls=[
        ft.Column([
            ft.Row([ft.Text("Reading settings", size=font_size(28, large_text),
                            color="#f4f0e8", expand=True),
                    ft.TextButton("Back", on_click=route_handler(navigate, "/menu"))]),
            ft.Text("Text size: " + ("Larger" if large_text else "Standard"),
                    size=font_size(20, large_text), color="#b9d7de"),
            ft.Row([choice("large_text", False, "Standard"),
                    choice("large_text", True, "Larger")], wrap=True),
            ft.Text("A clear sky, a quiet morning. Your place in the story is kept.",
                    size=font_size(20, large_text), color="#f4f0e8"),
            ft.Text("Dialogue: " + ("Instant" if status["text_speed"] == "instant" else "Animated"),
                    size=font_size(20, large_text), color="#b9d7de"),
            ft.Row([choice("text_speed", "instant", "Instant"),
                    choice("text_speed", "animated", "Animated")], wrap=True),
            ft.Text("With animated dialogue, tap once to reveal the line, then again to continue.",
                    color="#b9c5d0"),
            ft.Text(status["message"], color="#b9c5d0"),
        ], spacing=18, expand=True, scroll=ft.ScrollMode.AUTO),
    ])
