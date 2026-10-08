# A native choice screen without replacing the host's choice screen.
screen sdk_examples_choice(prompt, choices):
    modal True

    frame:
        align (0.5, 0.5)
        xsize min(620, config.screen_width - 64)
        padding (24, 24)
        background Solid("#101b2bf5")

        vbox:
            spacing 16
            xfill True

            text prompt size 30 color "#f4f0e8" substitute False

            for value, caption in choices:
                button:
                    id ("sdk_examples_choice_" + value)
                    xfill True
                    yminimum 64
                    padding (16, 12)
                    background Solid("#263e50")
                    hover_background Solid("#365970")
                    action Return(value)

                    text caption:
                        style "button_text"
                        size 28
                        color "#f4f0e8"
                        substitute False

label sdk_example_choice(prompt="Which path will you take?", choices=(("garden", "Visit the garden"), ("tower", "Climb the tower"))):
    $ renpy.checkpoint()
    call screen sdk_examples_choice(prompt, choices)
    return _return
