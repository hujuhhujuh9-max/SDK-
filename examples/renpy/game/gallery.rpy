# Standalone launcher only. Do not copy this file into the existing demo.
define config.name = "SDK optional Ren'Py examples"
define config.version = "1.0"
define config.main_menu = False
define config.save_directory = "sdk-renpy-optional-examples"
define config.screen_width = 720
define config.screen_height = 1280
define config.default_text_cps = 0
define config.history_length = 200
define config.check_conflicting_properties = True

default sdk_examples_name = "Traveler"
default sdk_examples_last_choice = ""

screen say(who, what):
    window:
        id "window"
        yalign 1.0
        xfill True
        padding (32, 32)
        background Solid("#101b2bf5")

        vbox:
            spacing 16
            if who:
                text who id "who" size 28 color "#b9d7de"
            text what id "what" size 32 color "#f4f0e8"
            text "Tap to continue" size 22 color "#b9c5d0"

label start:
    scene expression Solid("#182635")
    call sdk_example_dialogue(text="Choose an example. Each one returns here when it finishes.")

label sdk_examples_gallery:
    call sdk_example_choice("Try a native Ren'Py example", (("dialogue", "Dialogue"), ("choice", "Choice"), ("input", "Input"), ("animation", "Animation"), ("quit", "Close gallery")))

    if _return == "dialogue":
        call sdk_example_dialogue(text="A Character owns this line, its reading pace, and its history.")
        call sdk_example_dialogue(None, "Passing None uses the narrator instead.")
    elif _return == "choice":
        call sdk_example_choice
        $ sdk_examples_last_choice = _return
        if sdk_examples_last_choice == "tower":
            sdk_examples_guide "The tower gives us a view over the whole garden."
        else:
            sdk_examples_guide "Let's take the path through the garden."
    elif _return == "input":
        call sdk_example_input(initial=sdk_examples_name)
        $ sdk_examples_name = _return
        sdk_examples_guide "Hello, [sdk_examples_name!q]."
    elif _return == "animation":
        call sdk_example_animation
        sdk_examples_guide "The animation screen has closed. You can use its transform on your own images too."
    else:
        $ renpy.quit()

    jump sdk_examples_gallery
