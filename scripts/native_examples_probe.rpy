init 1 python:
    import sdk_examples_probe_driver
    config.overlay_screens.append("sdk_examples_probe_driver")
    config.label_overrides["start"] = "sdk_examples_probe_start"
    config.default_fullscreen = True

screen sdk_examples_probe_driver():
    timer 0.12 repeat True action Function(sdk_examples_probe_driver.tick, _update_screens=False)

default sdk_probe_stage = "opening"
default sdk_probe_default_choice = ""
default sdk_probe_custom_choice = ""
default sdk_probe_name = ""
default sdk_probe_limited = ""
default sdk_probe_empty = ""
default sdk_probe_whitespace = ""
default sdk_probe_animation = ""

label sdk_examples_probe_start:
    scene expression Solid("#182635")
    $ sdk_probe_stage = "character"
    call sdk_example_dialogue(text="Probe character dialogue.")
    $ sdk_probe_stage = "narrator"
    call sdk_example_dialogue(None, "Probe narrator dialogue.")
    $ sdk_probe_stage = "default-choice"
    call sdk_example_choice
    $ sdk_probe_default_choice = _return
    $ sdk_probe_stage = "default-result"
    "Default choice returned."
    $ sdk_probe_stage = "custom-choice"
    call sdk_example_choice("Custom route?", (("alpha", "First route"), ("beta", "Second route")))
    $ sdk_probe_custom_choice = _return
    $ sdk_probe_stage = "custom-result"
    "Custom choice returned."
    $ sdk_probe_stage = "typed-input"
    call sdk_example_input("Probe name?")
    $ sdk_probe_name = _return
    $ sdk_probe_stage = "typed-result"
    "Typed input returned."
    $ sdk_probe_stage = "limited-input"
    call sdk_example_input("Limited input?", initial="AB", length=4)
    $ sdk_probe_limited = _return
    $ sdk_probe_stage = "limited-result"
    "Limited input returned."
    $ sdk_probe_stage = "empty-input"
    call sdk_example_input("Empty input?", fallback="Empty fallback")
    $ sdk_probe_empty = _return
    $ sdk_probe_stage = "empty-result"
    "Empty input returned."
    $ sdk_probe_stage = "whitespace-input"
    call sdk_example_input("Whitespace input?", initial="   ", fallback="Whitespace fallback")
    $ sdk_probe_whitespace = _return
    $ sdk_probe_stage = "whitespace-result"
    "Whitespace input returned."
    $ sdk_probe_stage = "animation"
    call sdk_example_animation(travel=120, duration=0.8)
    $ sdk_probe_animation = _return
    $ sdk_probe_stage = "animation-result"
    "Animation returned."
    $ sdk_probe_stage = "snapshot"
    "Example snapshot ready."
    $ sdk_probe_name = "Changed"
    $ sdk_probe_custom_choice = "future"
    $ sdk_probe_stage = "future"
    "Future history should disappear."
    $ renpy.quit()
