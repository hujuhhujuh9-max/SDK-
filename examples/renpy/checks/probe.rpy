init 1 python:
    import sdk_examples_check
    if sdk_examples_check.mode == "native":
        config.label_overrides["start"] = "sdk_examples_probe_start"
    config.overlay_screens.append("sdk_examples_probe_overlay")
    config.exception_handler = sdk_examples_check.fail_exception

screen sdk_examples_probe_overlay():
    timer 0.15 repeat True action Function(sdk_examples_check.tick, _update_screens=False)

default sdk_probe_stage = "dialogue"
default sdk_probe_name = ""
default sdk_probe_route = ""
default sdk_probe_branch = ""

label sdk_examples_probe_start:
    scene expression Solid("#182635")
    call sdk_example_dialogue(text="Native example dialogue.")
    $ sdk_probe_stage = "narrator"
    call sdk_example_dialogue(None, "Native example narration.")
    $ sdk_probe_stage = "tower"
    call sdk_example_choice
    $ sdk_probe_route = _return
    if sdk_probe_route == "tower":
        $ sdk_probe_branch = "tower"
    else:
        $ sdk_probe_branch = "garden"
    $ sdk_probe_stage = "garden"
    call sdk_example_choice("Custom prompt", (("custom_garden", "Garden [literal]"), ("custom_tower", "Tower")))
    $ sdk_probe_route = _return
    if sdk_probe_route == "custom_garden":
        $ sdk_probe_branch = "garden"
    $ sdk_probe_stage = "name"
    call sdk_example_input
    $ sdk_probe_name = _return
    $ sdk_probe_stage = "limit"
    call sdk_example_input(initial="Hi", length=4)
    $ sdk_probe_limit = _return
    $ sdk_probe_stage = "empty"
    call sdk_example_input(fallback="Guest")
    $ sdk_probe_empty = _return
    $ sdk_probe_stage = "whitespace"
    call sdk_example_input(fallback="Visitor")
    $ sdk_probe_whitespace = _return
    $ sdk_probe_stage = "animation"
    call sdk_example_animation(travel=120, duration=0.6)
    $ sdk_probe_animation = _return
    $ sdk_probe_stage = "saved"
    sdk_examples_guide "Examples complete, [sdk_probe_name!q]."
    $ sdk_probe_stage = "future"
    $ sdk_probe_name = "Changed"
    $ sdk_probe_route = "future"
    sdk_examples_guide "Future state."
    return
