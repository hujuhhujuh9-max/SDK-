# Acceptance-only host. Uses the real SDK initialization, polling and save labels.
default _activity_probe_result = None
default _activity_probe_cancelled = None
default _activity_probe_returns = 0

init 2 python:
    import activity_native_driver
    config.overlay_screens.append("activity_native_probe")
    config.default_fullscreen = True
    if activity_native_driver.mode in ("reopen", "migrate"):
        config.auto_load = "_reload-1"

screen activity_native_probe():
    timer 0.15 repeat True action Function(activity_native_driver.tick, _update_screens=False)

label start:
    $ scene_title = "Registered activity native acceptance"
    show screen integration
    call renfletpy_activity("field_survey") from activity_probe_return
    $ _activity_probe_result = _return
    $ _activity_probe_returns += 1
    call renfletpy_activity("field_survey") from activity_probe_cancel_return
    $ _activity_probe_cancelled = _return
    $ _activity_probe_returns += 1
    "Both activity results reached the native story."
    return
