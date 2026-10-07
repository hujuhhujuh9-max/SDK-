# Copy this file into a project's game/ directory to opt in.
define sdk_examples_guide = Character("Guide", color="#b9d7de")

label sdk_example_dialogue(who=sdk_examples_guide, text="Welcome. This line uses native Ren'Py dialogue."):
    # Character, narrator, reading speed, and history stay with Ren'Py.
    $ renpy.say(who, text)
    return
