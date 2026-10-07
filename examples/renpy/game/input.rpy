# Ren'Py supplies the input widget's length, filters, and keyboard handling.
screen sdk_examples_input(prompt, initial):
    modal True
    default answer = initial

    frame:
        align (0.5, 0.5)
        xsize min(620, config.screen_width - 64)
        padding (24, 24)
        background Solid("#101b2bf5")

        vbox:
            spacing 20
            xfill True

            text prompt size 30 color "#f4f0e8" substitute False
            input:
                id "input"
                value ScreenVariableInputValue("answer", returnable=True)
                size 30
                color "#b9d7de"

            button:
                id "sdk_examples_input_confirm"
                yminimum 64
                padding (16, 12)
                background Solid("#263e50")
                hover_background Solid("#365970")
                action Return(answer)

                text "Confirm":
                    style "button_text"
                    size 28
                    color "#f4f0e8"

label sdk_example_input(prompt="What should we call you?", initial="", fallback="Traveler", length=24):
    $ renpy.checkpoint()
    return renpy.input(prompt, default=initial, length=length, screen="sdk_examples_input", show_initial=initial).strip() or fallback
