"""A project screen using its own Python/Dart package through ordinary SDK routes."""

import json
import os

import flet as ft

from app_home import app_home_view as sdk_home
from project_pulse import PulseDial


def register(api):
    api.register_screen("/app/pulse", pulse_screen, state_factory=lambda: {
        "value": 25.0, "intensity": 0.7, "running": True, "mounted": True,
        "draft": "", "changes": 0, "lifecycle": "Waiting for component",
    })


def app_home_view(page, navigate, status, request_story, *, route="/app", large_text=False):
    view = sdk_home(page, navigate, status, request_story, route=route, large_text=large_text)

    async def open_pulse(event):
        await navigate("/app/pulse")

    view.controls[0].controls.insert(1, ft.Button("Open pulse dial", on_click=open_pulse))
    return view


def pulse_screen(ctx):
    state = ctx.state
    selected = ft.Text(f"Selected: {state['value']:.1f} · changes: {state['changes']}")
    lifecycle = ft.Text(state["lifecycle"])
    dial = PulseDial(value=state["value"], intensity=state["intensity"],
                     running=state["running"], width=280, height=280)

    def record_event(phase, *, running=None):
        if ctx.is_current():
            print("SDK_CAP_PULSE_EVENT", json.dumps({
                "phase": phase,
                "running": state["running"] if running is None else running,
                "value": state["value"], "intensity": state["intensity"],
                "changes": state["changes"], "mounted": state["mounted"],
                "pid": os.getpid(),
            }, sort_keys=True), flush=True)

    async def changed(event):
        if not ctx.is_current():
            return
        state["value"] = float(event.value)
        state["changes"] += 1
        dial.value = state["value"]
        selected.value = f"Selected: {state['value']:.1f} · changes: {state['changes']}"
        ctx.page.update()
        record_event("selection")

    async def lifecycle_changed(event):
        if not ctx.is_current():
            return
        state["lifecycle"] = f"{event.phase}: {'playing' if event.running else 'paused'}"
        lifecycle.value = state["lifecycle"]
        ctx.page.update()
        record_event(event.phase, running=event.running)

    async def failed(event):
        if ctx.is_current():
            lifecycle.value = "Palette could not be loaded"
            ctx.page.update()

    async def toggle_playback(event):
        if not ctx.is_current():
            return
        state["running"] = not state["running"]
        dial.running = state["running"]
        ctx.page.update()
        record_event("playback")

    async def intensity_changed(event):
        if not ctx.is_current():
            return
        state["intensity"] = 0.3 if state["intensity"] > 0.5 else 0.9
        dial.intensity = state["intensity"]
        ctx.page.update()
        record_event("intensity")

    async def toggle_mount(event):
        if not ctx.is_current():
            return
        state["mounted"] = not state["mounted"]
        await ctx.refresh()

    async def draft_changed(event):
        if ctx.is_current():
            state["draft"] = event.control.value

    dial.on_change, dial.on_lifecycle, dial.on_error = changed, lifecycle_changed, failed
    controls = [ft.Text("Project pulse dial", size=28), selected, lifecycle,
                ft.Text("Tap the ring to select a value. Your note and selection stay here when you return from a story."),
                ft.Semantics(identifier="cap-pulse-draft", container=True,
                             content=ft.TextField(label="Working note", value=state["draft"], on_change=draft_changed))]
    if state["mounted"]:
        controls.append(ft.Semantics(identifier="cap-pulse-dial", container=True, content=dial))
    controls.extend([
        ft.Button("Pause / resume pulse", on_click=toggle_playback, disabled=not state["mounted"]),
        ft.Button("Change intensity", on_click=intensity_changed, disabled=not state["mounted"]),
        ft.Button("Remove component" if state["mounted"] else "Recreate component", on_click=toggle_mount),
        ft.Button("Start story", on_click=lambda event: ctx.start_story()),
        ft.Button("Resume story", on_click=lambda event: ctx.resume_story()),
        ft.Button("Back", on_click=ctx.back),
    ])
    return ft.View(route=ctx.route, controls=[ft.Column(controls, scroll=ft.ScrollMode.AUTO)])
