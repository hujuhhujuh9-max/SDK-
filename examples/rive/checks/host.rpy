# Runs only in the staged acceptance project, through real SDK native labels.
default _rive_probe_result = None
default _rive_probe_cancelled = None
default _rive_probe_returns = 0

init 2 python:
    import rive_native_driver
    config.overlay_screens.append("rive_native_probe")
    config.default_fullscreen = True
    if rive_native_driver.mode in ("reopen", "migrate"):
        config.auto_load = "_reload-1"

screen rive_native_probe():
    timer 0.15 repeat True action Function(rive_native_driver.tick, _update_screens=False)

label start:
    $ scene_title = "Rive saved activity acceptance"
    show screen integration
    call renfletpy_activity("rive_console") from rive_probe_return
    $ _rive_probe_result = _return
    $ _rive_probe_returns += 1
    call renfletpy_activity("rive_console") from rive_probe_cancel_return
    $ _rive_probe_cancelled = _return
    $ _rive_probe_returns += 1
    "Both Rive results reached the native story."
    return
