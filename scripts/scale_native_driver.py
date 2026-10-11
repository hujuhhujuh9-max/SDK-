"""Probe-only native driver, copied into an isolated Ren'Py project."""

import json
import os
import time
import traceback
from pathlib import Path

import pygame_sdl2 as pygame
import renpy.exports as renpy
import renpy.store as store
from renpy import game
from renpy.display.core import EndInteraction

output = Path(os.environ["SDK_2D_NATIVE_OUTPUT"])
mode = os.environ.get("SDK_2D_NATIVE_MODE", "initial")
phase = "reopen" if mode == "reopen" else "motion"
checks = []
pixels = {}
ticks = 0
started = time.monotonic()
motion_first = None
plain = None


def fail_exception(exception):
    os._exit(1)


def capture(name):
    filename = output / (name + ".png")
    renpy.screenshot(str(filename))
    surface = pygame.image.load(str(filename))
    # Both renders use the same screen. Sample its central drawing field;
    # the text heading and continuation control are outside this region.
    width, height = surface.get_size()
    return [tuple(surface.get_at((x, y))[:3])
            for y in range(height // 2 - 180, height // 2 + 120, 4)
            for x in range(24, width - 24, 4)]


def continue_stage():
    button = renpy.get_displayable("sdk_scale_native_stage", "sdk_scale_continue")
    assert button.is_sensitive(), "Native Continue must accept input"
    renpy.end_interaction(renpy.run(button.action))


def receipt():
    value = {"scope": "host_native_functionality", "mode": mode, "checks": checks,
             "sizes": {"sprites": 128, "composite_layers": 8, "shader_passes": 2},
             "elapsed_ms": (time.monotonic() - started) * 1000,
             "renpy": renpy.version_string, "renderer": dict(renpy.get_renderer_info()),
             "pid": os.getpid(), "pixel_samples": pixels,
             "phone_performance": "unverified"}
    (output / "receipt.json").write_text(json.dumps(value, indent=2) + "\n")
    print("SDK_2D_NATIVE_RECEIPT " + json.dumps(value), flush=True)


def tick():
    global ticks, phase, motion_first, plain
    try:
        ticks += 1
        if phase == "motion" and ticks == 3:
            motion_first = capture("motion-first")
        elif phase == "motion" and ticks == 9:
            motion_second = capture("motion-second")
            changed = sum(before != after for before, after in zip(motion_first, motion_second))
            assert changed > 500, ("Native ATL/shader field must actually animate", changed)
            pixels["motion"] = {"changed": changed, "samples": len(motion_first), "required_more_than": 500}
            assert any(max(pixel) - min(pixel) > 50 for pixel in motion_second), "Field must contain colored sprites"
            checks.append("128 ATL sprites and original shaders visibly animate")
            renpy.save("scale-halfway")
            assert renpy.can_load("scale-halfway")
            checks.append("native bookmark saved while shaders and ATL are active")
            phase = "plain"
            continue_stage()
        elif phase == "plain" and store.sdk_scale_probe_stage == "plain":
            plain = capture("shader-disabled")
            phase = "shader"
            continue_stage()
        elif phase == "shader" and store.sdk_scale_probe_stage == "shader":
            shader = capture("shader-enabled")
            changed = sum(before != after for before, after in zip(plain, shader))
            assert changed > 1000, ("Custom shaders must change actual static pixels", changed)
            pixels["shader"] = {"changed": changed, "samples": len(plain), "required_more_than": 1000}
            checks.append("two shader passes change static composite pixels")
            checks.append("native Continue returns the declared plain result")
            receipt()
            renpy.quit()
        elif phase == "reopen" and ticks >= 3 and store.sdk_scale_probe_stage == "motion":
            capture("reopened-motion")
            assert renpy.get_screen("sdk_scale_native_stage")
            assert len(store.scale_native._scenes) == 1, "Renderers are freshly reconstructed after reopening"
            checks.append("fresh process loads native bookmark and reconstructs the live scene")
            receipt()
            renpy.quit()
    except (EndInteraction, game.FullRestartException, game.QuitException):
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)
