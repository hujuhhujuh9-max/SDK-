define config.name = "Runner integration"
define config.version = "0.1.0"
define config.main_menu = False
define config.save_directory = "sdk-runner-integration"

init python:
    import os
    import sdk_bridge
    _last_count = -1
    def refresh_shared_state():
        global _last_count
        if sdk_bridge.quitting():
            renpy.quit()
        value = sdk_bridge.counter()
        if value != _last_count:
            print("SDK_RUNNER_RENPY_COUNTER value=%s pid=%s" % (value, os.getpid()), flush=True)
            _last_count = value
        renpy.restart_interaction()
    config.quit_callbacks.append(sdk_bridge.stop)
    if renpy.android:
        sdk_bridge.start()

screen integration:
    add Solid("#1b2838")
    vbox:
        align (0.5, 0.5)
        spacing 20
        text "Ready" size 50 xalign 0.5
        text "Count: [sdk_bridge.counter()]" size 40 xalign 0.5
    timer 0.2 repeat True action Function(refresh_shared_state)

label start:
    $ print("SDK_RUNNER_RENPY_READY pid=%s" % __import__("os").getpid(), flush=True)
    show screen integration
    $ renpy.pause(hard=True)
    jump start
