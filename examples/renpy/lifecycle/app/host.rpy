# Alternative host for A's shared bridge; do not include the standalone host too.
# Copy native_story_mailbox.py to the project root and the shared runtime there.
define config.name = "Native story mailbox recipe"
define config.main_menu = False
define config.screen_width = 720
define config.screen_height = 1280
define config.default_text_cps = 0

default sdk_native_story_last_result = None

init 1 python:
    import sdk_bridge
    import native_story_mailbox
    import renfletpy

    sdk_native_story_install_profile()
    native_story_mailbox.runtime = native_story_mailbox.NativeStoryMailbox(sdk_bridge, SDK_NATIVE_STORY_ID)

    def sdk_native_story_input_allowed():
        return (sdk_bridge.presentation() == "scene" and not sdk_bridge.story_status()["busy"]
                and not sdk_bridge.save_status()["busy"] and not sdk_bridge.reading_status()["busy"])

    def sdk_native_story_prepare_return():
        return native_story_mailbox.runtime.prepare_return()

    def sdk_native_story_save_from_scene():
        if not sdk_native_story_input_allowed():
            return False
        saved = sdk_native_story_save_checkpoint()
        sdk_bridge.update_save_status(sdk_native_story_owns_slot(SDK_NATIVE_STORY_SLOT), sdk_native_story_message)
        return saved

    def sdk_native_story_mailbox_restore():
        native_story_mailbox.runtime.restore(sdk_native_story_status())
        sdk_bridge.update_save_status(sdk_native_story_owns_slot(SDK_NATIVE_STORY_SLOT), "Story restored.")
        sdk_bridge.initialize_reading(bool(persistent.renfletpy_large_text),
            "instant" if _preferences.text_cps == 0 else "animated")

    def sdk_native_story_mailbox_tick():
        if sdk_bridge.quitting():
            renpy.quit()
        if renfletpy.story.restarting():
            renfletpy.story.reset()
            renpy.full_restart()
        scene_shown = renpy.get_screen("sdk_native_story_scene") is not None
        if scene_shown:
            native_story_mailbox.runtime.entered(sdk_native_story_status())
        action = native_story_mailbox.runtime.take(sdk_native_story_status(), scene_shown=scene_shown)
        if action is not None:
            renpy.end_interaction(action)

        # These are distinct from story commands. Only this native timer calls
        # save/load; a successful load transfers control to the after-load hook.
        save = sdk_bridge.take_save_request()
        if save is not None:
            if save == "save":
                sdk_native_story_save_checkpoint()
            else:
                sdk_native_story_load_checkpoint()
            sdk_bridge.update_save_status(sdk_native_story_owns_slot(SDK_NATIVE_STORY_SLOT), sdk_native_story_message)
        reading = sdk_bridge.take_reading_request()
        if reading is not None:
            old_size, old_speed = persistent.renfletpy_large_text, _preferences.text_cps
            name, value = reading
            try:
                if name == "large_text":
                    persistent.renfletpy_large_text = value
                else:
                    _preferences.text_cps = 0 if value == "instant" else 30
                renpy.save_persistent()
                message = "Reading choice kept for your next visit."
            except Exception:
                logging.exception("Native recipe reading preference could not be saved")
                persistent.renfletpy_large_text, _preferences.text_cps = old_size, old_speed
                message = "Could not keep that choice. Please try again."
            sdk_bridge.update_reading_status(bool(persistent.renfletpy_large_text),
                "instant" if _preferences.text_cps == 0 else "animated", message)
        gate = sdk_native_story_input_allowed()
        if gate != native_story_mailbox.runtime.last_gate:
            native_story_mailbox.runtime.last_gate = gate
            renpy.restart_interaction()

    config.after_load_callbacks.append(sdk_native_story_mailbox_restore)
    config.overlay_screens.append("sdk_native_story_mailbox_timer")
    config.quit_callbacks.append(sdk_bridge.stop)
    if renpy.android:
        sdk_bridge.start()

screen sdk_native_story_mailbox_timer():
    timer 0.05 repeat True action Function(sdk_native_story_mailbox_tick, _update_screens=False)

screen sdk_native_story_app_home():
    add Solid("#101b2b")
    vbox:
        xalign 0.5
        yalign 0.5
        xsize 620
        spacing 24
        text "The last lantern" size 42 color "#f4f0e8"
        text "Confirmed native story mailbox" size 26 color "#b9d7de"
        textbutton "Start" action Function(sdk_bridge.request_story, "start", SDK_NATIVE_STORY_ID) sensitive (not sdk_bridge.story_status()["busy"] and sdk_native_story_status()["status"] in ("unavailable", "completed"))
        textbutton "Resume live story" action Function(sdk_bridge.request_story, "resume", SDK_NATIVE_STORY_ID) sensitive (not sdk_bridge.story_status()["busy"] and sdk_native_story_can_resume())
        textbutton "Load checkpoint" action Function(sdk_bridge.request_save, "load") sensitive (sdk_bridge.save_status()["available"] and not sdk_bridge.save_status()["busy"] and not sdk_bridge.story_status()["busy"])
        textbutton "Close recipe" action Quit(confirm=False)
        text sdk_bridge.story_status()["message"] size 20 color "#b9c5d0"

label start:
    $ sdk_native_story_mailbox_restore()
    while True:
        $ renpy.checkpoint()
        $ renpy.retain_after_load()
        call screen sdk_native_story_app_home
        call sdk_native_story(_return)
        $ sdk_native_story_last_result = _return
        $ native_story_mailbox.runtime.handoff(_return)
