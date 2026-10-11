# Project acceptance only: callbacks and caches live in the imported module.
# SDK native initialization and restore keep their original ownership and order.
init 20 python:
    import capabilities_observer
    capabilities_observer.install(renpy)
    config.overlay_screens.append("capabilities_native_observer")

screen capabilities_native_observer():
    timer 0.2 repeat True action Function(capabilities_observer.tick, _update_screens=False)
