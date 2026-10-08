# This ATL transform can also be used with a host's own show/add statements.
transform sdk_examples_pulse(travel=160, duration=0.8):
    xoffset 0
    alpha 0.4
    linear duration xoffset travel alpha 1.0
    linear duration xoffset 0 alpha 0.4
    repeat

screen sdk_examples_animation(travel, duration):
    modal True

    frame:
        align (0.5, 0.5)
        xsize min(620, config.screen_width - 64)
        padding (24, 24)
        background Solid("#101b2bf5")

        vbox:
            spacing 20
            xfill True

            text "Native ATL animation" size 30 color "#f4f0e8"
            fixed:
                ysize 160
                add Solid("#00d4c8", xsize=32, ysize=32) at sdk_examples_pulse(travel, duration):
                    id "sdk_examples_marker"
                    xpos 24
                    ypos 64

            text "The light moves and changes opacity until you continue." size 26 color "#b9d7de"
            button:
                id "sdk_examples_animation_continue"
                yminimum 64
                padding (16, 12)
                background Solid("#263e50")
                hover_background Solid("#365970")
                action Return("finished")

                text "Continue":
                    style "button_text"
                    size 28
                    color "#f4f0e8"

label sdk_example_animation(travel=160, duration=0.8):
    $ renpy.checkpoint()
    call screen sdk_examples_animation(travel, duration)
    return _return
