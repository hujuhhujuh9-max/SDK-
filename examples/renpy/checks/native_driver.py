"""Ren'Py-side driver, loaded only into verify.py's temporary projects."""

import json
import os
import statistics
import traceback
from pathlib import Path

import pygame_sdl2 as pygame
import renpy.exports as renpy
import renpy as renpy_engine
import renpy.store as store
from renpy import game
from renpy.display.core import EndInteraction, IgnoreEvent

mode = os.environ["SDK_EXAMPLES_MODE"]
phase = "dialogue"
checks = []
positions = []
ticks = 0
gallery_step = 0
output = Path(os.environ["SDK_EXAMPLES_OUTPUT"])

def fail_exception(exception):
    # Ren'Py has already written its traceback to the captured log.
    os._exit(1)

def passed(name):
    checks.append(name)
    print("Passed: " + name, flush=True)

def screenshot(name):
    path = output / (name + ".png")
    renpy.screenshot(str(path))
    return path

def enter_text(text):
    widget = renpy.get_displayable("sdk_examples_input", "input")
    try:
        widget.event(pygame.event.Event(pygame.TEXTINPUT, text=text), 0, 0, 0)
    except IgnoreEvent:
        pass

def press_enter():
    widget = renpy.get_displayable("sdk_examples_input", "input")
    result = widget.event(pygame.event.Event(pygame.KEYDOWN, key=pygame.K_RETURN,
                         unicode="\r", mod=0, repeat=False), 0, 0, 0)
    renpy.end_interaction(result)

def post_key(key, text=""):
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key,
                      unicode=text, mod=0, repeat=False))
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key,
                      unicode=text, mod=0, repeat=False))

def click(screen, widget):
    button = renpy.get_displayable(screen, widget)
    assert button.is_sensitive()
    renpy.end_interaction(renpy.run(button.action))

def marker(name):
    surface = pygame.image.load(str(screenshot(name)))
    points = []
    colors = []
    for y in range(surface.get_height()):
        for x in range(surface.get_width()):
            r, g, b = surface.get_at((x, y))[:3]
            if g > 80 and g - r > 60 and b - r > 50 and abs(g - b) < 35:
                points.append(x)
                colors.append(g)
    assert len(points) >= 100, (name, len(points))
    return statistics.mean(points), statistics.mean(colors)

def tick():
    try:
        if mode == "gallery":
            advance_gallery()
        elif mode.startswith("first-"):
            advance_first()
        else:
            advance()
    except (EndInteraction, game.FullRestartException, game.QuitException):
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)

def advance():
    global phase, ticks
    stage = store.sdk_probe_stage
    if phase == "dialogue":
        assert store._history_list[-1].who == "Guide"
        assert store._history_list[-1].what == "Native example dialogue."
        screenshot("dialogue")
        passed("Character dialogue renders and enters native history")
        renpy.save("examples-dialogue")
        phase = "dialogue-future"
        renpy.end_interaction(True)
    elif phase == "dialogue-future" and stage == "narrator":
        assert store._history_list[-1].what == "Native example narration."
        phase = "dialogue-restored"
        renpy.load("examples-dialogue")
    elif phase == "dialogue-restored" and stage == "dialogue":
        assert len(store._history_list) == 1, [(h.kind, h.what) for h in store._history_list]
        assert store._history_list[-1].who == "Guide"
        assert store._history_list[-1].what == "Native example dialogue."
        passed("loading active dialogue restores its speaker, text, and history")
        phase = "narrator"
        renpy.end_interaction(True)
    elif phase == "narrator" and stage == "narrator":
        assert store._history_list[-1].who is None
        assert store._history_list[-1].what == "Native example narration."
        assert len(store._history_list) == 2
        passed("None speaker uses native narration")
        phase = "tower"
        renpy.end_interaction(True)
    elif phase == "tower" and renpy.get_screen("sdk_examples_choice"):
        screenshot("choice")
        renpy.save("examples-choice")
        phase = "choice-future"
        click("sdk_examples_choice", "sdk_examples_choice_garden")
    elif phase == "choice-future" and stage == "garden":
        assert store.sdk_probe_route == "garden" and store.sdk_probe_branch == "garden"
        phase = "choice-restored"
        renpy.load("examples-choice")
    elif phase == "choice-restored" and stage == "tower":
        assert store.sdk_probe_route == "" and store.sdk_probe_branch == ""
        assert renpy.get_screen("sdk_examples_choice").scope["prompt"] == "Which path will you take?"
        passed("loading an active choice restores its options and removes future results")
        phase = "garden"
        click("sdk_examples_choice", "sdk_examples_choice_tower")
    elif phase == "garden" and stage == "garden":
        assert store.sdk_probe_branch == "tower"
        passed("default choice returns its ID and executes the tower branch")
        phase = "name"
        click("sdk_examples_choice", "sdk_examples_choice_custom_garden")
    elif phase == "name" and stage == "name" and renpy.get_screen("sdk_examples_input"):
        assert store.sdk_probe_branch == "garden"
        assert store.sdk_probe_route == "custom_garden"
        assert not renpy.get_screen("sdk_examples_choice")
        passed("custom choice returns its ID, executes garden branch, and closes its screen")
        enter_text("  Nova  ")
        phase = "name-enter"
    elif phase == "name-enter":
        assert renpy.get_screen("sdk_examples_input").scope["answer"] == "  Nova  "
        renpy.save("active-input")
        enter_text("Future")
        phase = "active-input-load"
    elif phase == "active-input-load":
        assert renpy.get_screen("sdk_examples_input").scope["answer"] == "  Nova  Future"
        phase = "active-input-restored"
        renpy.load("active-input")
    elif phase == "active-input-restored":
        restored = renpy.get_screen("sdk_examples_input").scope["answer"]
        assert restored == ""
        passed("loading active input restarts the prompt with its initial value")
        enter_text("  Nova  ")
        phase = "name-confirm"
    elif phase == "name-confirm":
        screenshot("input")
        phase = "limit"
        press_enter()
    elif phase == "limit" and stage == "limit":
        assert store.sdk_probe_name == "Nova"
        passed("native text events and Enter return whitespace-trimmed text")
        widget = renpy.get_displayable("sdk_examples_input", "input")
        assert widget.content == "Hi"
        enter_text("12345")
        phase = "limit-confirm"
    elif phase == "limit-confirm":
        assert renpy.get_screen("sdk_examples_input").scope["answer"] == "Hi12"
        phase = "empty"
        click("sdk_examples_input", "sdk_examples_input_confirm")
    elif phase == "empty" and stage == "empty":
        assert store.sdk_probe_limit == "Hi12"
        passed("initial value, native length limit, and Confirm button work")
        phase = "whitespace"
        press_enter()
    elif phase == "whitespace" and stage == "whitespace":
        assert store.sdk_probe_empty == "Guest"
        passed("empty input returns the supplied fallback")
        enter_text("   ")
        phase = "whitespace-confirm"
    elif phase == "whitespace-confirm":
        phase = "animation"
        click("sdk_examples_input", "sdk_examples_input_confirm")
    elif phase == "animation" and stage == "animation":
        assert store.sdk_probe_whitespace == "Visitor"
        assert not renpy.get_screen("sdk_examples_input")
        passed("whitespace input returns fallback and removes its transient screen")
        renpy.save("examples-animation")
        positions.append(marker("animation-start"))
        ticks = 0
        phase = "animation-moving"
    elif phase == "animation-moving":
        ticks += 1
        if ticks < 2:
            return
        sample = marker("animation-moving")
        if abs(sample[0] - positions[0][0]) <= 10 or abs(sample[1] - positions[0][1]) <= 5:
            assert ticks < 10, (positions, sample)
            return
        positions.append(sample)
        passed("ATL moves actual framebuffer pixels and changes opacity")
        phase = "animation-restored"
        renpy.load("examples-animation")
    elif phase == "animation-restored" and stage == "animation":
        assert renpy.get_screen("sdk_examples_animation")
        positions.append(marker("animation-restored"))
        ticks = 0
        phase = "animation-resumed"
    elif phase == "animation-resumed":
        ticks += 1
        if ticks < 2:
            return
        sample = marker("animation-resumed")
        if abs(sample[0] - positions[-1][0]) <= 10:
            assert ticks < 10, (positions, sample)
            return
        positions.append(sample)
        passed("loading an active animation restores the screen and visible movement")
        phase = "saved"
        click("sdk_examples_animation", "sdk_examples_animation_continue")
    elif phase == "saved" and stage == "saved":
        assert store.sdk_probe_animation == "finished"
        assert not renpy.get_screen("sdk_examples_animation")
        screenshot("animation-closed")
        passed("Continue returns finished and removes the animation screen")
        renpy.save("examples-probe")
        phase = "load"
        renpy.end_interaction(True)
    elif phase == "load" and stage == "future":
        assert store.sdk_probe_name == "Changed"
        phase = "restored"
        renpy.load("examples-probe")
    elif phase == "restored" and stage == "saved":
        assert store.sdk_probe_name == "Nova"
        assert store.sdk_probe_route == "custom_garden"
        assert store._history_list[-1].what == "Examples complete, Nova."
        passed("native save/load restores example results, script position, and history")
        write_receipt()
        renpy.quit()

def write_receipt():
    (output / "results.json").write_text(json.dumps({"mode": mode,
        "sdk_version": renpy_engine.version, "checks": checks,
        "project_files": sorted(p.name for p in Path(store.config.gamedir).glob("*.rpy")),
        "animation_pixels": positions}, indent=2) + "\n")

def advance_first():
    global phase, ticks
    name = mode.removeprefix("first-")
    screen = {"dialogue": "say", "choice": "sdk_examples_choice",
              "input": "sdk_examples_input", "animation": "sdk_examples_animation"}[name]
    if phase == "dialogue" and renpy.get_screen(screen):
        files = {p.name for p in Path(store.config.gamedir).glob("*.rpy")}
        assert files == {name + ".rpy", "host.rpy"}, files
        passed(name + " runs with only its own library and the host fixture")
        renpy.save("examples-first")
        phase = "first-restored"
        renpy.load("examples-first")
    elif phase == "first-restored" and renpy.get_screen(screen):
        passed(name + " saves and loads as the first interaction")
        if name == "dialogue":
            assert len(store._history_list) == 1
            assert store._history_list[-1].who == "Host speaker"
            assert store._history_list[-1].what == "Host interpolation."
            assert renpy.get_displayable("say", "sdk_probe_say_marker")
            phase = "first-result"
            post_key(pygame.K_RETURN, "\r")
        elif name == "choice":
            phase = "first-focus"
        elif name == "input":
            phase = "first-input"
            pygame.event.post(pygame.event.Event(pygame.TEXTINPUT, text="  Solo  "))
        else:
            phase = "first-focus"
    elif phase == "first-input":
        assert renpy.get_screen(screen).scope["answer"] == "  Solo  "
        phase = "first-result"
        post_key(pygame.K_RETURN, "\r")
    elif phase == "first-focus":
        widget_id = "sdk_examples_choice_tower" if name == "choice" else "sdk_examples_animation_continue"
        button = renpy.get_displayable(screen, widget_id)
        if not button.is_focused():
            ticks += 1
            assert ticks < 5, "Arrow keys did not reach " + widget_id
            post_key(pygame.K_DOWN)
            return
        phase = "first-result"
        post_key(pygame.K_RETURN, "\r")
    elif phase == "first-result" and store.sdk_probe_stage == "first-done":
        expected = {"dialogue": None, "choice": "tower", "input": "Solo", "animation": "finished"}[name]
        assert store.sdk_probe_first_result == expected
        passed(name + " returns its result through native keyboard events after loading")
        if name == "input":
            assert store.answer == "Host story value", store.answer
            passed("input leaves the host's answer story variable unchanged")
        write_receipt()
        renpy.quit()

GALLERY_MENU = "Try a native Ren'Py example"
GALLERY_STEPS = (
    ("say", "Choose an example. Each one returns here when it finishes.", None),
    ("choose", GALLERY_MENU, "dialogue"),
    ("say", "A Character owns this line, its reading pace, and its history.", None),
    ("say", "Passing None uses the narrator instead.", None),
    ("choose", GALLERY_MENU, "choice"),
    ("choose", "Which path will you take?", "tower"),
    ("say", "The tower gives us a view over the whole garden.", None),
    ("choose", GALLERY_MENU, "choice"),
    ("choose", "Which path will you take?", "garden"),
    ("say", "Let's take the path through the garden.", None),
    ("choose", GALLERY_MENU, "input"),
    ("edit", "Traveler", "Reader"),
    ("enter", "TravelerReader", None),
    ("say", "Hello, TravelerReader.", None),
    ("choose", GALLERY_MENU, "input"),
    ("confirm", "TravelerReader", None),
    ("say", "Hello, TravelerReader.", None),
    ("choose", GALLERY_MENU, "animation"),
    ("animation", None, None),
    ("say", "The animation screen has closed. You can use its transform on your own images too.", None),
    ("choose", GALLERY_MENU, "quit"),
)

def advance_gallery():
    global gallery_step, ticks
    action, expected, value = GALLERY_STEPS[gallery_step]
    if action == "say" and renpy.get_screen("say"):
        assert store._history_list[-1].what == expected
        assert not renpy.get_screen("sdk_examples_animation")
        gallery_step += 1
        passed("gallery dialogue: " + expected)
        renpy.end_interaction(True)
    elif action == "choose" and renpy.get_screen("sdk_examples_choice"):
        assert renpy.get_screen("sdk_examples_choice").scope["prompt"] == expected
        if expected == GALLERY_MENU:
            assert not renpy.get_screen("sdk_examples_input")
            assert not renpy.get_screen("sdk_examples_animation")
        if value == "quit":
            passed("gallery Close gallery exits normally")
            write_receipt()
        elif value == "dialogue":
            screenshot("gallery-menu")
        gallery_step += 1
        if value != "quit":
            passed("gallery selects " + value)
        click("sdk_examples_choice", "sdk_examples_choice_" + value)
    elif action in ("edit", "enter", "confirm") and renpy.get_screen("sdk_examples_input"):
        assert renpy.get_screen("sdk_examples_input").scope["answer"] == expected
        gallery_step += 1
        if action == "edit":
            enter_text(value)
        elif action == "enter":
            passed("gallery input accepts native text and Enter")
            press_enter()
        else:
            passed("gallery reopened input keeps the last confirmed name")
            click("sdk_examples_input", "sdk_examples_input_confirm")
    elif action == "animation" and renpy.get_screen("sdk_examples_animation"):
        ticks += 1
        if not positions:
            positions.append(marker("gallery-animation-start"))
            return
        if ticks < 3:
            return
        sample = marker("gallery-animation-moving")
        if abs(sample[0] - positions[0][0]) <= 10:
            assert ticks < 10, (positions, sample)
            return
        positions.append(sample)
        passed("gallery animation moves and Continue returns to dialogue")
        gallery_step += 1
        click("sdk_examples_animation", "sdk_examples_animation_continue")
