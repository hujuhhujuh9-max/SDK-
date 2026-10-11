"""Reconstructed native displayables for the optional Ren'Py stress example."""

import threading
import json

if __package__:
    from .scale_workloads import NATIVE_SIZES
else:
    from scale_workloads import NATIVE_SIZES


_scenes = {}
_owner = None


def _native_owner():
    global _owner
    thread = threading.get_ident()
    if _owner is None:
        _owner = thread
    elif _owner != thread:
        raise RuntimeError("Native 2D displayables belong to the Ren'Py story thread")


def scene(tier="nominal", width=688, height=480, *, animated=True, shaders=True):
    """Live displayables remain module-owned and are excluded from game values."""
    _native_owner()
    import renpy.store as store

    key = (tier, width, height, animated, shaders)
    if key in _scenes:
        return _scenes[key]
    if tier not in NATIVE_SIZES:
        raise ValueError("Choose workload tier 'nominal' or 'stress'")
    sprites, layers, passes = NATIVE_SIZES[tier]
    colors = ("#00d4c8", "#8ebcf0", "#f09f96", "#d6bcff")
    tile = [store.Composite((32, 32),
                            (0, 0), store.Solid(color, xsize=32, ysize=32),
                            (4, 4), store.Solid("#182635aa", xsize=24, ysize=24),
                            (12, 8), store.Solid("#f4f0e8cc", xsize=8, ysize=16))
            for color in colors]
    children = [store.Solid("#182635", xsize=width, ysize=height)]
    for index in range(layers):
        # Every layer overlaps the complete stage; alpha keeps earlier layers
        # visible. They are genuine compositing work rather than hidden nodes.
        children.append(store.Transform(store.Solid(colors[index % len(colors)] + "0b",
                                                     xsize=width, ysize=height),
                                         xsize=width, ysize=height))
    columns = max(1, width // 40)
    rows = max(1, (sprites + columns - 1) // columns)
    spacing_y = max(8, (height - 48) // rows)
    for index in range(sprites):
        item = tile[index % len(tile)]
        if animated:
            item = store.At(item, store.sdk_scale_orbit(index))
        children.append(store.Transform(item, xpos=4 + index % columns * 40,
                                         ypos=4 + index // columns * spacing_y))
    result = store.Fixed(*children, xsize=width, ysize=height)
    if shaders:
        for index in range(passes):
            result = store.At(result, store.sdk_scale_shader(
                "sdk_scale.ripple" if index % 2 == 0 else "sdk_scale.scanline"))
    _scenes[key] = result
    if animated and shaders:
        print("SDK_2D_READY " + json.dumps({"workload": "renpy", "tier": tier,
                                          "sprites": sprites, "composite_layers": layers,
                                          "shader_passes": passes}, sort_keys=True), flush=True)
    return result


def release():
    _native_owner()
    _scenes.clear()
