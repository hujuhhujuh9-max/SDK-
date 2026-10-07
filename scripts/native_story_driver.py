"""Ren'Py-side driver for native story, tactics, save and recovery checks."""

import json
import os
import statistics
import time
import traceback
from pathlib import Path
import renpy.exports as renpy
from renpy import game as renpy_game
from renpy.display.core import EndInteraction
import renpy.store as store
import sdk_bridge
from renfletpy import SaveState, story

mode = os.environ["RENFLETPY_CHECK_MODE"]
phase = "tactics-recover" if mode == "tactics-recover" else "recover" if mode == "recover" else "opening"
checks = []
old_revision = None
paused_ticks = 0
camera_step = 0
pixel_probes = []
animation_probes = []
render_profile = None

def passed(name):
    checks.append(name)
    print("Passed: native " + name, flush=True)

def finish():
    Path(os.environ["RENFLETPY_CHECK_RECEIPT"]).write_text(json.dumps({
        "mode": mode, "pid": os.getpid(), "checks": checks,
        "pixel_probes": pixel_probes, "animation_probes": animation_probes,
        "render_profile": render_profile}, indent=2) + "\n")
    renpy.quit()

def tick():
    try:
        advance()
    except (EndInteraction, renpy_game.FullRestartException, renpy_game.QuitException):
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)

def check_no_rollback():
    assert not renpy.can_rollback()
    assert not store.Rollback().get_sensitive()
    position, state = renpy_game.context().current, story.snapshot()
    renpy.rollback()
    renpy.run(store.Rollback())
    assert renpy_game.context().current == position and story.snapshot() == state
    passed("player rollback leaves the current story and choices unchanged")

def advance():
    global phase, old_revision, paused_ticks
    if mode.startswith("tactics"):
        advance_tactics()
        return
    current = story.current()
    status = sdk_bridge.save_status()
    if phase == "opening" and mode == "warm":
        animation_probes.append(light_position("animation-start"))
        paused_ticks = 0
        phase = "animation-moving"
    elif phase == "animation-moving":
        paused_ticks += 1
        if paused_ticks < 2:
            return
        animation_probes.append(light_position("animation-moving"))
        assert abs(animation_probes[-1] - animation_probes[-2]) > 10, animation_probes
        passed("ATL animation moves actual native framebuffer pixels")
        sdk_bridge.set_presentation("page")
        paused_ticks = 0
        phase = "animation-hidden"
    elif phase == "animation-hidden":
        paused_ticks += 1
        if paused_ticks < 3:
            return
        assert light_position("animation-hidden", required=False) is None
        passed("native animation leaves the shared menu surface clear")
        sdk_bridge.set_presentation("scene")
        paused_ticks = 0
        phase = "animation-returned"
    elif phase == "animation-returned":
        paused_ticks += 1
        if paused_ticks < 3:
            return
        animation_probes.append(light_position("animation-returned"))
        paused_ticks = 0
        phase = "animation-resumed"
    elif phase == "animation-resumed":
        paused_ticks += 1
        if paused_ticks < 2:
            return
        animation_probes.append(light_position("animation-resumed"))
        assert abs(animation_probes[-1] - animation_probes[-2]) > 10, animation_probes
        passed("ATL animation moves again after returning from the menu")
        assert sdk_bridge.request_reading("large_text", True)
        phase = "reading-size"
    elif phase == "opening":
        assert sdk_bridge.request_reading("large_text", True)
        phase = "reading-size"
    elif phase == "reading-size" and not sdk_bridge.reading_status()["busy"]:
        assert store.persistent.renfletpy_large_text
        assert renpy.get_displayable("say", "what").style.size == 40
        passed("shared large text updates the actual native dialogue")
        assert sdk_bridge.request_reading("text_speed", "animated")
        phase = "reading-pace"
    elif phase == "reading-pace" and not sdk_bridge.reading_status()["busy"]:
        assert store._preferences.text_cps == 30
        assert sdk_bridge.request_reading("text_speed", "instant")
        phase = "reading-ready"
    elif phase == "reading-ready" and not sdk_bridge.reading_status()["busy"]:
        assert store._preferences.text_cps == 0
        passed("dialogue pace changes through the native preference owner")
        phase = "puzzle"
        renpy.end_interaction(True)
    elif phase == "puzzle" and current is not None:
        assert current.kind == "star_map"
        story.tap_star(current.revision, "deneb")
        old_revision = current.revision
        if mode == "seed":
            renpy_game.interface.mobile_save()
            assert renpy.can_load("_reload-1")
            passed("background save captures a move without quick save")
            Path(os.environ["RENFLETPY_CHECK_RECEIPT"]).write_text(json.dumps({
                "mode": mode, "pid": os.getpid(), "checks": checks}, indent=2) + "\n")
            os._exit(0)  # Simulate process loss, preserving the mobile reload.
        assert sdk_bridge.request_save("save")
        phase = "manual-saved"
    elif phase == "manual-saved" and not status["busy"]:
        assert "Saved." in status["message"], status
        assert sdk_bridge.request_reading("text_speed", "animated")
        phase = "manual-preference"
    elif phase == "manual-preference" and not sdk_bridge.reading_status()["busy"]:
        story.tap_star(current.revision, "vega")
        assert sdk_bridge.request_save("load")
        phase = "manual-loaded"
    elif phase == "manual-loaded" and not status["busy"]:
        assert current.progress == ("deneb",), current
        assert current.revision != old_revision
        assert not story.tap_star(old_revision, "altair")
        passed("quick save restores exact progress and fresh controls")
        assert store._preferences.text_cps == 30
        passed("loading an older quick save keeps the current reading preferences")
        assert sdk_bridge.request_reading("text_speed", "instant")
        phase = "manual-reading-reset"
    elif phase == "manual-reading-reset" and not sdk_bridge.reading_status()["busy"]:
        renpy_game.interface.mobile_save()
        story.tap_star(current.revision, "vega")
        phase = "background-loaded"
        renpy.load("_reload-1")
    elif phase == "background-loaded":
        assert current.progress == ("deneb",), current
        assert not renpy.can_load("_reload-1"), "Loaded background save was not consumed"
        passed("mobile save restores active minigame")
        renpy.force_autosave()
        phase = "auto-saving"
    elif phase == "auto-saving" and renpy.can_load("auto-1"):
        story.tap_star(current.revision, "vega")
        phase = "auto-loaded"
        renpy.load("auto-1")
    elif phase in ("auto-loaded", "recover"):
        assert current is not None and current.progress == ("deneb",), current
        assert isinstance(store._renfletpy_saved_state, SaveState)
        assert any("before sunrise" in entry.what for entry in store._history_list)
        assert not renpy.can_load("_reload-1"), "Stale recovery remains after a successful load"
        passed("fresh process recovers mobile save" if phase == "recover" else "autosave worker restores active minigame")
        if mode == "recover":
            assert store.persistent.renfletpy_large_text
            assert store._preferences.text_cps == 0
            assert sdk_bridge.reading_status()["large_text"]
            assert sdk_bridge.reading_status()["text_speed"] == "instant"
            passed("reading preferences survive process loss independently of the story save")
        sdk_bridge.set_presentation("page")
        story.tap_star(current.revision, "vega")
        story.tap_star(current.revision, "altair")
        paused_ticks = 0
        phase = "paused-menu-result"
    elif phase in ("paused-menu-result", "paused-diagnostic-result"):
        assert current is not None and current.selected == "aligned"
        assert not [entry for entry in store._history_list if entry.kind == "interlude"]
        paused_ticks += 1
        if paused_ticks < 3:
            return
        if phase == "paused-menu-result":
            sdk_bridge.set_presentation("diagnostics")
            phase = "paused-diagnostic-result"
            paused_ticks = 0
            return
        passed("menus and diagnostics hold a completed minigame until resume")
        sdk_bridge.set_presentation("interlude")
        phase = "result"
    elif phase == "result" and current is None:
        assert store.scene_title == "A sky worth waiting for"
        results = [entry for entry in store._history_list if entry.kind == "interlude"]
        assert len(results) == 1 and results[0].renfletpy_result == "Constellation aligned"
        passed("restored result returns once to native dialogue and history")
        check_no_rollback()
        if mode == "recover":
            finish()
        assert sdk_bridge.request_save("save")
        phase = "scene-saved"
    elif phase == "scene-saved" and not status["busy"]:
        phase = "panel"
        renpy.end_interaction(True)
    elif phase == "panel" and current is not None:
        assert current.speaker == "Field journal"
        renpy.save("probe-panel")
        old_revision = current.revision
        story.choose(current.revision, "company")
        phase = "panel-result"
    elif phase == "panel-result" and current is None:
        assert any(getattr(entry, "renfletpy_result", "") == "The company" for entry in store._history_list)
        phase = "panel-loaded"
        renpy.load("probe-panel")
    elif phase == "panel-loaded":
        assert current.speaker == "Field journal" and current.selected is None
        assert current.revision != old_revision
        assert not story.choose(old_revision, "company")
        assert not any(getattr(entry, "renfletpy_result", "") == "The company" for entry in store._history_list)
        passed("panel save restores choices and removes future history")
        story.choose(current.revision, "constellation")
        phase = "journal-result"
    elif phase == "journal-result" and current is None:
        assert any("next summer" in entry.what for entry in store._history_list)
        phase = "final-dialogue"
        renpy.end_interaction(True)
    elif phase == "final-dialogue":
        assert any("first light reaches" in entry.what for entry in store._history_list)
        phase = "ending"
        renpy.end_interaction(True)
    elif phase == "ending" and current is not None:
        assert current.speaker == "First light"
        history = sdk_bridge.transcript()
        if not history or history[-1][0] != "First light":
            return  # The shared-history timer runs independently of this driver.
        assert [entry[0] for entry in history] == ["Mira", "Star map", "Mira", "Field journal", "Mira", "Mira", "First light"], history
        passed("native dialogue and Flet results share chronological history")
        renpy.save("probe-ending")
        story.choose(current.revision, "replay")
        phase = "replayed"
    elif phase == "replayed" and current is None:
        assert store.scene_title == "Before the First Light"
        assert story.history() == ()
        assert len(store._history_list) == 1
        phase = "ending-loaded"
        renpy.load("probe-ending")
    elif phase == "ending-loaded":
        assert current.speaker == "First light"
        assert len(store._history_list) == 6
        passed("ending waits for explicit replay and can be restored after replay")
        phase = "scene-loaded"
        renpy.load("renfletpy-quick")
    elif phase == "scene-loaded":
        assert current is None and store.scene_title == "A sky worth waiting for"
        assert len([entry for entry in store._history_list if entry.kind == "interlude"]) == 1
        passed("normal scene save restores input and native history")
        check_no_rollback()
        finish()

def capture(name):
    path = Path(os.environ["RENFLETPY_CHECK_RECEIPT"]).parent / (mode + "-" + name + ".png")
    renpy.screenshot(str(path))
    return path

def light_position(name, required=True):
    import renpy.pygame as pygame
    surface = pygame.image.load(str(capture(name)))
    scale = surface.get_width() / 720
    y = round(150 * surface.get_height() / 1280)
    points = [x for x in range(round(270 * scale), round(470 * scale))
              if all(abs(actual - target) < 8 for actual, target in
                     zip(surface.get_at((x, y))[:3], (0, 212, 200)))]
    if required:
        assert len(points) >= 10, (name, points)
    return statistics.mean(points) if points else None

def profile_board(view):
    """Measure real SDL painting and reuse, excluding GPU presentation."""
    global render_profile
    width, height = view.viewport
    samples = {"repaint_ms": [], "reuse_ms": []}
    for _ in range(15):
        view._raster_surface = None
        started = time.perf_counter()
        view.render(width, height, 0, 0)
        samples["repaint_ms"].append((time.perf_counter() - started) * 1000)
        surface = view._raster_surface
        started = time.perf_counter()
        view.render(width, height, 0, 0)
        samples["reuse_ms"].append((time.perf_counter() - started) * 1000)
        assert view._raster_surface is surface
    assert "_raster_surface" not in view.__getstate__()
    view.render(width + 1, height, 0, 0)
    assert view._raster_surface is not surface, "Resizing reused a stale raster"
    view.render(width, height, 0, 0)
    render_profile = {"scope": "SDL board construction, excluding GPU presentation",
                      "viewport": [width, height], "samples": 15,
                      **{name: {"median": statistics.median(values), "p95": sorted(values)[-1]}
                         for name, values in samples.items()}}
    print("SDK_RUNNER_NATIVE_RENDER_PROFILE " + json.dumps(render_profile), flush=True)
    passed("board raster reuse invalidates on resize and stays out of native saves")

def advance_tactics():
    global phase, old_revision, paused_ticks, camera_step
    import renpy.pygame as pygame
    from math import cos, radians, sin
    from tactics import Cell, GOAL, LEVEL_H, TacticsView, project
    current = story.current()
    status = sdk_bridge.save_status()
    view = store._tactics_view

    def click(x, y):
        px, py = view.screen_position(x, y)
        view.event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1), px, py, 0)

    def cell_tap(cell):
        x, y = project(cell, current.view.rotation, current.view.mode)
        click(x + 24, y)

    def unit_tap(uid):
        cell = next(u.cell for u in story.tactics_state().units if u.uid == uid)
        x, y = project(cell, current.view.rotation, current.view.mode)
        click(x if current.view.mode == "top_down" else x - 10,
              y if current.view.mode == "top_down" else y - 30)

    def ready():
        return (view.state is not None and view.revision == current.revision
                and view.camera == current.view and view.state.positions() == current.positions)

    def dial(value):
        angle = radians(135 + value * 270)
        x, y = 40 + 32 * cos(angle), 40 + 32 * sin(angle)
        for event in (pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP):
            view.opacity_dial.event(pygame.event.Event(event, button=1), x, y, 0)

    def probe(name, x=449, y=305):
        path = capture(name)
        surface = pygame.image.load(str(path))
        px, py = view.screen_position(x, y)
        # Fullscreen renders the 720x1280 virtual UI at the physical 1080p size.
        x, y = round((16 + px) * surface.get_width() / 720), round((240 + py) * surface.get_height() / 1280)
        color = tuple(surface.get_at((x, y)))[:3]
        pixel_probes.append({"name": name, "point": [x, y], "actual": color})
        return color

    saved_view = TacticsView(opacity=0.25, rotation=1, zoom=1.2, pan_x=40.0, pan_y=-25.0,
                            mode="top_down", level=0)

    if phase == "opening":
        phase = "tactics-stars"
        renpy.end_interaction(True)
    elif phase == "tactics-stars" and current is not None:
        story.choose(current.revision, "skipped")
        phase = "tactics-dialogue"
    elif phase == "tactics-dialogue" and current is None:
        phase = "tactics-journal"
        renpy.end_interaction(True)
    elif phase == "tactics-journal" and current is not None:
        story.choose(current.revision, "route")
        phase = "tactics-board"
    elif phase == "tactics-board" and current is not None and current.kind == "tactics":
        if not ready():
            return
        capture("start")
        assert view.scale > 0
        assert story.tactics_state().selected_uid == "scout"
        passed("adapted tactics board renders in the portrait story viewport")
        if mode == "tactics-skip":
            view.skip()
            phase = "tactics-skipped"
            return
        profile_board(view)
        unit_tap("knight")
        assert story.current().selected_unit == "knight"
        unit_tap("scout")
        assert story.current().selected_unit == "scout"
        passed("native displayable taps select the painted units")
        cell_tap(Cell(0, 4, 0))
        assert story.tactics_state().selected.cell == Cell(0, 4, 0)
        phase = "tactics-ground"
    elif phase == "tactics-ground":
        capture("ground")
        x, y = project(Cell(0, 4, 0))
        assert probe("selection-foot", x, y + 11) == (214, 181, 69)
        assert probe("selection-body", x, y - 30) == (74, 170, 157)
        passed("selection rings sit at the projected feet without crossing the unit body")
        cell_tap(Cell(1, 4, 1))
        assert story.tactics_state().selected.cell == Cell(1, 4, 1)
        passed("native taps move on ground and onto an elevated shelf")
        phase = "tactics-height"
    elif phase == "tactics-height":
        capture("height")
        view.reset()
        assert story.tactics_state().selected.cell == Cell(1, 4, 0)
        passed("native reset restores the route without restarting the story")
        from tactics_display import _BlendedCanvas
        for alpha in (64, 128):
            raster = _BlendedCanvas(10, 10)
            raster.surface.fill((74, 170, 157, 255))
            raster.rect((124, 83, 67, alpha), (0, 0, 10, 10))
            expected = [round(top * alpha / 255 + bottom * (1 - alpha / 255))
                        for top, bottom in zip((124, 83, 67), (74, 170, 157))]
            assert all(abs(a - b) <= 1 for a, b in zip(raster.surface.get_at((5, 5)), expected))
            raster.surface.fill((74, 170, 157, 255))
            raster.polygon((124, 83, 67, alpha), [(0, 0), (9, 0), (0, 9)])
            assert tuple(raster.surface.get_at((8, 8))) == (74, 170, 157, 255)
        passed("terrain opacity is applied once when blending a face over a unit")
        phase = "tactics-reset"
    elif phase == "tactics-reset":
        capture("reset")
        dial(1.0)
        phase = "tactics-opacity-opaque"
    elif phase == "tactics-opacity-opaque" and ready():
        assert current.view.opacity == 1.0
        assert probe("opaque") == (124, 83, 67)
        assert probe("terrain-top", *project(Cell(3, 4, 1))) == (91, 126, 68)
        assert probe("wall-plane", 655, 350) == (124, 83, 67)
        assert probe("wall-plane-left", 600, 350) == (124, 83, 67)
        for name, cell in (("invisible-ground", Cell(5, 5, 0)), ("invisible-sky", Cell(0, 5, 2))):
            x, y = project(cell)
            assert probe(name, x + 14, y + 4) == (17, 19, 24)
        passed("empty floors stay invisible while terrain has green tops and brown walls")
        dial(0.0)
        phase = "tactics-opacity-clear"
    elif phase == "tactics-opacity-clear" and ready():
        assert current.view.opacity == 0.0
        assert probe("clear") == (74, 170, 157)
        dial(0.5)
        phase = "tactics-opacity-half"
    elif phase == "tactics-opacity-half" and ready():
        assert current.view.opacity == 0.5
        blended = probe("half")
        opaque = next(p["actual"] for p in pixel_probes if p["name"] == "opaque")
        clear = next(p["actual"] for p in pixel_probes if p["name"] == "clear")
        assert blended != opaque and blended != clear
        assert all(abs(a - b) <= 3 for a, b in zip(blended, (99, 126, 112)))
        passed("the touch dial reveals covered units with per-face transparency")
        bar = renpy.get_displayable("renfletpy_tactics_input", "tactics_opacity")
        bar.adjustment.change(0.25)
        assert story.tactics_view().opacity == 0.25
        passed("the native opacity slider shares the dial's saved value")
        camera_step = 0
        phase = "tactics-camera"
    elif phase == "tactics-camera" and ready():
        assert current.view.rotation == camera_step
        capture("camera-" + str(camera_step))
        cell_tap(Cell(0, 4, 0))
        assert story.tactics_state().units[1].cell == Cell(0, 4, 0)
        view.reset()
        camera_step += 1
        if camera_step < 4:
            view.rotate(1)
        else:
            passed("tile picking preserves world destinations through all four camera views")
            view.rotate(1)
            view.set_mode("top_down")
            camera_step = 0
            phase = "tactics-top-down"
    elif phase == "tactics-top-down" and ready():
        assert current.view.mode == "top_down" and current.view.level == 0
        capture("top-down-" + str(camera_step))
        cell_tap(Cell(0, 4, 0))
        assert story.tactics_state().units[1].cell == Cell(0, 4, 0)
        view.reset()
        camera_step += 1
        if camera_step < 4:
            view.rotate(1)
        else:
            passed("top-down taps resolve the chosen level through all four rotations")
            view.rotate(1)
            view.change_view(opacity=1.0, level=1)
            phase = "tactics-top-level-one"
    elif phase == "tactics-top-level-one" and ready():
        assert probe("top-down-terrain", *project(Cell(3, 4, 1), mode="top_down")) == (91, 126, 68)
        assert probe("top-down-unit", *project(Cell(3, 2, 1), mode="top_down")) == (74, 170, 157)
        x, y = project(Cell(0, 5, 0), mode="top_down")
        assert view.pick_unit(x, y) is None
        assert view.pick_surface(x, y) is None
        view.set_level(2)
        phase = "tactics-top-level-two"
    elif phase == "tactics-top-level-two" and ready():
        assert probe("top-down-sky-unit", *project(Cell(4, 3, 2), mode="top_down")) == (184, 76, 71)
        x, y = project(Cell(3, 4, 2), mode="top_down")
        assert probe("top-down-empty-sky", x + 14, y + 4) == (17, 19, 24)
        passed("level selection filters units, picking and terrain in the top-down view")
        view.change_view(mode="side", level=None, opacity=0.25)
        camera_step = 0
        phase = "tactics-side"
    elif phase == "tactics-side" and ready():
        capture("side-" + str(camera_step))
        before = current.positions
        cell_tap(Cell(5, 0, 0))
        assert story.current().positions == before
        assert view.pick_surface(*project(Cell(5, 0, 0), camera_step, "side")) is None
        assert project(Cell(0, 0, 0), mode="side")[1] - project(Cell(0, 0, 1), mode="side")[1] == LEVEL_H
        camera_step += 1
        if camera_step < 4:
            view.rotate(1)
        else:
            passed("orthographic side inspection retains equal levels without ambiguous tile moves")
            view.change_view(mode="isometric", rotation=0, zoom=1.2)
            phase = "tactics-pan"
    elif phase == "tactics-pan" and ready():
        assert current.view.rotation == 0 and current.view.zoom == 1.2
        before = current.positions
        sx, sy = 340, 400
        view.event(pygame.event.Event(pygame.MOUSEBUTTONDOWN, button=1), sx, sy, 0)
        view.event(pygame.event.Event(pygame.MOUSEMOTION, buttons=(1, 0, 0)), sx + 50, sy - 30, 0)
        view.event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1), sx + 50, sy - 30, 0)
        assert story.current().positions == before
        assert story.tactics_view().pan_x > 0 and story.tactics_view().pan_y < 0
        passed("native drag pans without moving a unit, and zoom changes the camera scale")
        view.center()
        assert story.tactics_view().zoom == 1.0 and story.tactics_view().pan_x == 0
        assert story.tactics_view().opacity == 0.25
        view.change_view(**vars(saved_view))
        phase = "tactics-camera-save"
    elif phase == "tactics-camera-save" and ready():
        capture("camera-saved")
        cell_tap(Cell(0, 4, 0))
        unit_tap("knight")
        assert story.current().selected_unit == "knight"
        old_revision = current.revision
        sdk_bridge.set_presentation("page")
        assert sdk_bridge.request_save("save")
        phase = "tactics-saved"
    elif phase == "tactics-saved" and not status["busy"]:
        before = story.current()
        click(*project(GOAL))
        view.reset()
        view.rotate(1)
        view.zoom_by(0.2)
        view.center()
        view.set_mode("side")
        view.set_level(2)
        dial(1.0)
        view.opacity = 1.0
        assert story.current() == before
        passed("the shared menu blocks board input, camera controls and opacity changes")
        sdk_bridge.set_presentation("scene")
        view.reset()
        view.change_view(opacity=1.0, rotation=3, zoom=0.8, pan_x=0.0, pan_y=0.0,
                         mode="isometric", level=None)
        assert sdk_bridge.request_save("load")
        phase = "tactics-loaded"
    elif phase == "tactics-loaded" and not status["busy"]:
        state = story.tactics_state()
        assert state.units[1].cell == Cell(0, 4, 0)
        assert state.selected_uid == "knight"
        assert current.revision != old_revision
        assert not story.move_tactics_unit(old_revision, GOAL)
        assert current.view == saved_view
        passed("native quick save restores positions, selection, camera mode, level and opacity")
        capture("loaded")
        renpy.force_autosave()
        phase = "tactics-auto-saving"
    elif phase == "tactics-auto-saving" and renpy.can_load("auto-1"):
        story.reset_tactics(current.revision)
        phase = "tactics-auto-loaded"
        renpy.load("auto-1")
    elif phase == "tactics-auto-loaded":
        assert story.tactics_state().units[1].cell == Cell(0, 4, 0)
        assert current.selected_unit == "knight"
        assert current.view == saved_view
        passed("native worker autosave captures the live board and camera settings")
        # Model a steady scene with no changed timer values after process loss.
        store._last_count = sdk_bridge.counter()
        store._last_presentation = sdk_bridge.presentation()
        renpy_game.interface.mobile_save()
        assert renpy.can_load("_reload-1")
        passed("mobile save captures the tactics board before process loss")
        Path(os.environ["RENFLETPY_CHECK_RECEIPT"]).write_text(json.dumps({
            "mode": mode, "pid": os.getpid(), "checks": checks,
            "pixel_probes": pixel_probes, "render_profile": render_profile}, indent=2) + "\n")
        os._exit(0)
    elif phase == "tactics-recover":
        assert current is not None and current.kind == "tactics"
        assert story.tactics_state().units[1].cell == Cell(0, 4, 0)
        assert current.selected_unit == "knight"
        assert current.view == saved_view
        assert not renpy.can_load("_reload-1")
        if not ready():
            return
        capture("recovered")
        passed("a fresh Ren’Py process recovers the moved board, camera and opacity")
        sdk_bridge.set_presentation("scene")
        story.select_tactics_unit(current.revision, "scout")
        button = renpy.get_displayable("renfletpy_tactics_input", "tactics_level_2")
        assert button.is_sensitive() and button.clicked is not None
        assert not renpy.get_displayable("renfletpy_tactics_input", "tactics_level_all").is_sensitive()
        renpy.run(button.clicked)
        assert story.tactics_view().level == 2
        passed("restored screen controls accept input without a counter or presentation change")
        phase = "tactics-recovered-goal"
    elif phase == "tactics-recovered-goal" and ready():
        cell_tap(GOAL)
        assert story.current().selected == "reached"
        sdk_bridge.set_presentation("page")
        paused_ticks = 0
        phase = "tactics-paused-result"
    elif phase == "tactics-paused-result":
        assert current is not None and current.selected == "reached"
        assert not any(getattr(entry, "renfletpy_result", "") == "Scout reached the balcony"
                       for entry in store._history_list)
        paused_ticks += 1
        if paused_ticks < 3:
            return
        passed("a completed tactics result waits for shared-menu resume")
        sdk_bridge.set_presentation("scene")
        phase = "tactics-result"
    elif phase in ("tactics-result", "tactics-skipped") and current is None:
        reached = phase == "tactics-result"
        expected = "Scout reached the balcony" if reached else "Route skipped"
        results = [entry for entry in store._history_list
                   if getattr(entry, "renfletpy_result", "") == expected]
        assert len(results) == 1
        assert any(("found a path" if reached else "balcony can wait") in entry.what
                   for entry in store._history_list)
        passed("tactics completion returns once to native dialogue and history" if reached
               else "skipping the native route resumes its story branch")
        capture("result")
        finish()
