# Opt-in project: assemble with this profile and lifecycle/story.rpy.
# Never copy this host or its early profile into the default demo game.
define config.name = "Story application"
define config.main_menu = False
define config.screen_width = 720
define config.screen_height = 1280
define config.default_text_cps = 0

init 1 python:
    import sdk_bridge
    import native_app_bridge
    SDK_NATIVE_STORY_PROFILE = "sdk-app-lantern-v1"
    sdk_native_story_install_profile()
    native_app_bridge.install()
    config.overlay_screens.append("sdk_app_commands")
    config.python_exit_callbacks.append(sdk_bridge.stop)
    if renpy.android:
        sdk_bridge.start()

screen sdk_app_commands():
    timer 0.05 repeat True action Function(native_app_bridge.tick, _update_screens=False)

screen sdk_app_idle():
    modal True
    add Solid("#182635")
    text "Open the application to choose a story." align (0.5, 0.5)
    key "dismiss" action NullAction()

label start:
    $ native_app_bridge.recover()
    while True:
        $ renpy.checkpoint()
        $ renpy.retain_after_load()
        call screen sdk_app_idle
        if _return in ("start", "resume"):
            call sdk_native_story(_return)
            while native_app_bridge.returned(_return):
                call sdk_native_story("start")
