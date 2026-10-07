# Minimal host for one reusable file at a time. Never copied into the gallery.
define config.name = "Independent example verification"
define config.main_menu = False
define config.screen_width = 720
define config.screen_height = 1280
define config.default_text_cps = 0
define config.history_length = 200
define config.check_conflicting_properties = True
define sdk_probe_speaker = Character("Host speaker")

default sdk_probe_stage = "first"
default sdk_probe_first_result = None
default sdk_probe_word = "interpolation"
default answer = "Host story value"

init 1 python:
    import sdk_examples_check
    config.overlay_screens.append("sdk_examples_probe_overlay")
    config.exception_handler = sdk_examples_check.fail_exception

screen sdk_examples_probe_overlay():
    timer 0.15 repeat True action Function(sdk_examples_check.tick, _update_screens=False)

screen say(who, what):
    window:
        id "window"
        yalign 1.0
        xfill True
        padding (24, 24)
        background Solid("#101b2b")
        vbox:
            spacing 16
            text "Independent host screen" id "sdk_probe_say_marker" size 24
            if who:
                text who id "who" size 28
            text what id "what" size 32

label start:
    scene expression Solid("#182635")
    if sdk_examples_check.mode == "first-dialogue":
        call sdk_example_dialogue(sdk_probe_speaker, "Host [sdk_probe_word].")
    else:
        call expression "sdk_example_" + sdk_examples_check.mode.removeprefix("first-")
    $ sdk_probe_first_result = _return
    $ sdk_probe_stage = "first-done"
    "First interaction complete."
    return
