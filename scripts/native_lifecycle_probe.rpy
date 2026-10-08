# Verification only: copied into temporary projects by check_native_lifecycle.py.
init 1 python:
    import native_lifecycle_check
    native_lifecycle_check.setup()
    config.overlay_screens.append("sdk_native_lifecycle_check")
    config.default_fullscreen = True

screen sdk_native_lifecycle_check():
    timer 0.12 repeat True action Function(native_lifecycle_check.tick, _update_screens=False)
