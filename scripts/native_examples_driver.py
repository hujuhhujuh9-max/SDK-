"""Real Ren'Py interaction driver for the optional native examples."""
import json
import os
import statistics
import time
import traceback
from pathlib import Path

import pygame_sdl2 as pygame
import renpy.exports as renpy
import renpy.store as store
from renpy import config, game
from renpy.display.core import EndInteraction, IgnoreEvent

checks = []
animation = []
animation_started = None
animation_waits = 0
sent_input = set()
saved_history = None
loading = False
started = time.monotonic()
output = Path(os.environ["SDK_EXAMPLES_PROBE_OUTPUT"])


def passed(name):
    checks.append(name)
    print("Passed: " + name, flush=True)


def history():
    return [(entry.who, entry.what) for entry in store._history_list]


def capture(name):
    path = output / (name + ".png")
    renpy.screenshot(str(path))
    return path


def marker(name, required=True):
    surface = pygame.image.load(str(capture(name)))
    points = []
    green = []
    for y in range(surface.get_height()):
        for x in range(surface.get_width()):
            r, g, b = surface.get_at((x, y))[:3]
            if r < 30 and g - r > 55 and b - r > 50:
                points.append(x)
                green.append(g)
    if required:
        assert len(points) >= 100, (name, len(points))
    result = {"capture": str(output / (name + ".png")), "pixels": len(points),
              "x": statistics.mean(points) if points else None,
              "green": statistics.mean(green) if green else None}
    return result


def click(screen, widget):
    button = renpy.get_displayable(screen, widget)
    assert button.is_sensitive() and button.clicked is not None
    value = renpy.run(button.clicked)
    if value is not None:
        renpy.end_interaction(value)


def type_text(text):
    widget = renpy.get_displayable("sdk_examples_input", "input")
    assert widget.editable
    try:
        widget.event(pygame.event.Event(pygame.TEXTINPUT, text=text), 0, 0, 0)
    except IgnoreEvent:
        pass


def enter():
    widget = renpy.get_displayable("sdk_examples_input", "input")
    event = pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN,
                               unicode="\r", mod=0, repeat=False)
    value = widget.event(event, 0, 0, 0)
    if value is not None:
        renpy.end_interaction(value)


def finish():
    for name in ("rollback", "can_rollback", "in_rollback", "roll_forward_info",
                 "roll_forward_core", "in_fixed_rollback", "get_identifier_checkpoints",
                 "get_roll_forward", "block_rollback", "suspend_rollback", "fix_rollback"):
        assert not hasattr(renpy, name), name
    for name in ("Rollback", "RollbackToIdentifier", "RollForward"):
        assert not hasattr(store, name), name
    assert "rollback" not in config.keymap and "rollforward" not in config.keymap
    passed("player rollback APIs and controls remain absent")
    (output / "receipt.json").write_text(json.dumps({"pid": os.getpid(),
        "checks": checks, "animation": animation, "history": history()}, indent=2) + "\n")
    renpy.quit()


def tick():
    try:
        advance()
    except (EndInteraction, game.FullRestartException, game.QuitException):
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)


def advance():
    global animation_started, animation_waits, saved_history, loading
    if time.monotonic() - started > 80:
        raise RuntimeError("Example probe stalled at " + store.sdk_probe_stage)
    stage = store.sdk_probe_stage
    if stage == "character":
        assert history()[-1] == ("Guide", "Probe character dialogue."), history()
        passed("Character dialogue reaches native say and chronological history")
        renpy.end_interaction(True)
    elif stage == "narrator":
        assert history()[-1] == (None, "Probe narrator dialogue."), history()
        passed("Narrator dialogue reaches native say and history")
        renpy.end_interaction(True)
    elif stage == "default-choice" and renpy.get_screen("sdk_examples_choice"):
        capture("choice-default")
        click("sdk_examples_choice", "sdk_examples_choice_tower")
    elif stage == "default-result":
        assert store.sdk_probe_default_choice == "tower"
        assert not renpy.get_screen("sdk_examples_choice")
        passed("Default choice returns its ID and closes the transient screen")
        renpy.end_interaction(True)
    elif stage == "custom-choice" and renpy.get_screen("sdk_examples_choice"):
        click("sdk_examples_choice", "sdk_examples_choice_beta")
    elif stage == "custom-result":
        assert store.sdk_probe_custom_choice == "beta"
        assert not renpy.get_screen("sdk_examples_choice")
        passed("Custom choice returns the selected host route ID")
        renpy.end_interaction(True)
    elif stage == "typed-input" and renpy.get_screen("sdk_examples_input"):
        if stage not in sent_input:
            type_text("  Nova  ")
            sent_input.add(stage)
            return
        assert renpy.get_displayable("sdk_examples_input", "input").content == "  Nova  "
        capture("input-typed")
        enter()
    elif stage == "typed-result":
        assert store.sdk_probe_name == "Nova", store.sdk_probe_name
        assert not renpy.get_screen("sdk_examples_input")
        passed("Native text events and Enter return trimmed input and close its screen")
        renpy.end_interaction(True)
    elif stage == "limited-input" and renpy.get_screen("sdk_examples_input"):
        if stage not in sent_input:
            assert renpy.get_displayable("sdk_examples_input", "input").content == "AB"
            type_text("CDEF")
            sent_input.add(stage)
            return
        assert renpy.get_displayable("sdk_examples_input", "input").content == "ABCD"
        capture("input-limited")
        click("sdk_examples_input", "sdk_examples_input_confirm")
    elif stage == "limited-result":
        assert store.sdk_probe_limited == "ABCD", store.sdk_probe_limited
        assert not renpy.get_screen("sdk_examples_input")
        passed("Initial value, four-character limit and Confirm use the native input widget")
        renpy.end_interaction(True)
    elif stage == "empty-input" and renpy.get_screen("sdk_examples_input"):
        click("sdk_examples_input", "sdk_examples_input_confirm")
    elif stage == "empty-result":
        assert store.sdk_probe_empty == "Empty fallback"
        assert not renpy.get_screen("sdk_examples_input")
        passed("Empty submission returns the requested fallback")
        renpy.end_interaction(True)
    elif stage == "whitespace-input" and renpy.get_screen("sdk_examples_input"):
        click("sdk_examples_input", "sdk_examples_input_confirm")
    elif stage == "whitespace-result":
        assert store.sdk_probe_whitespace == "Whitespace fallback"
        assert not renpy.get_screen("sdk_examples_input")
        passed("Whitespace-only submission returns the requested fallback")
        renpy.end_interaction(True)
    elif stage == "animation" and renpy.get_screen("sdk_examples_animation"):
        if animation_started is None:
            animation.append(marker("animation-first"))
            animation_started = time.monotonic()
            return
        if time.monotonic() - animation_started < 0.25:
            return
        current = marker("animation-second")
        # Capturing a framebuffer may span a frame on a busy runner; take
        # additional timed observations when a leg happens to return near start.
        animation_waits += 1
        if abs(current["x"] - animation[0]["x"]) < 10 and animation_waits < 4:
            return
        assert abs(current["x"] - animation[0]["x"]) >= 10, (animation[0], current)
        assert abs(current["green"] - animation[0]["green"]) >= 10, (animation[0], current)
        animation.append(current)
        passed("ATL moves actual framebuffer pixels and changes their opacity")
        click("sdk_examples_animation", "sdk_examples_animation_continue")
    elif stage == "animation-result":
        assert store.sdk_probe_animation == "finished"
        assert not renpy.get_screen("sdk_examples_animation")
        assert marker("animation-closed", required=False)["pixels"] == 0
        passed("Continue returns finished and removes the rendered animation")
        renpy.end_interaction(True)
    elif stage == "snapshot":
        if loading:
            assert store.sdk_probe_name == "Nova" and store.sdk_probe_custom_choice == "beta"
            assert store.sdk_probe_default_choice == "tower"
            assert history() == saved_history, (history(), saved_history)
            passed("Native load restores example state, script position and exact history")
            finish()
        saved_history = history()
        renpy.save("native-examples-probe")
        assert renpy.can_load("native-examples-probe")
        renpy.end_interaction(True)
    elif stage == "future":
        assert store.sdk_probe_name == "Changed" and store.sdk_probe_custom_choice == "future"
        assert history()[-1][1] == "Future history should disappear."
        loading = True
        renpy.load("native-examples-probe")
