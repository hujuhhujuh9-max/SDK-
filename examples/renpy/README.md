# Optional native Ren'Py examples

Four small, reusable examples for the pinned Ren'Py 8.5.3 SDK. They live outside
the product's `game/` directory, so the current **Before the First Light** demo
and Android builds do not load or package them. This directory owns the examples,
their standalone gallery, and their documentation.

| File | Entry point | Existing Ren'Py APIs | Result |
| --- | --- | --- | --- |
| [dialogue.rpy](game/dialogue.rpy) | `sdk_example_dialogue(who, text)` | `Character`, `renpy.say` | `None` |
| [choice.rpy](game/choice.rpy) | `sdk_example_choice(prompt, choices)` | `call screen`, `Return` | Selected string ID |
| [input.rpy](game/input.rpy) | `sdk_example_input(prompt, initial, fallback, length)` | `renpy.input`, `ScreenVariableInputValue`, `Return` | Trimmed text or fallback |
| [animation.rpy](game/animation.rpy) | `sdk_example_animation(travel, duration)` | ATL, `Solid`, `call screen`, `Return` | `"finished"` |

The four files are independent. Their labels, screens, transform, and Character
use the `sdk_example_` or `sdk_examples_` prefix. They do not replace a host's
`start`, `say`, `choice`, or `input`, or register callbacks, threads, or bridge
hooks. Dialogue uses the host's existing say screen and reading preferences.
Choice and input use named native screens; animation uses Ren'Py's renderer.

## Run the standalone gallery

From the repository root on Linux:

```sh
python3 prepare.py setup renpy
mkdir -p .android-build/renpy-examples
cp -R examples/renpy/game .android-build/renpy-examples/

renpy_examples_sdk="$(python3 -c 'from prepare import BuildInputs; print(BuildInputs(".android-build").sdk_root("renpy"))')"
"$renpy_examples_sdk/renpy.sh" .android-build/renpy-examples compile
"$renpy_examples_sdk/renpy.sh" .android-build/renpy-examples lint
"$renpy_examples_sdk/renpy.sh" .android-build/renpy-examples run \
    --savedir .android-build/renpy-examples/saves
```

Use a desktop display or Xvfb for `run`. On other platforms, open the copied
project with the matching Ren'Py launcher. Generated scripts, logs, caches, and
saves stay in the ignored `.android-build/` directory.

The gallery starts with dialogue and offers each example, then returns to its
menu. Input accepts Enter or the **Confirm** button. Animation runs until
**Continue**. **Close gallery** exits the standalone process.

[gallery.rpy](game/gallery.rpy) supplies a standalone `start`, say screen, portrait
window, and save directory named `sdk-renpy-optional-examples`. Keep it in the
standalone project. When reusing an example in another project, copy only the
individual example files. This keeps the host's configuration and entry point.

## Reuse the labels

Copy any of the four files into your own project's `game/` directory. Call the
labels at an explicit story point. Store `_return` before another call overwrites
it; use `default` for story variables that should be saved.

```renpy
default my_example_route = ""
default my_example_name = "Traveler"

label my_example_scene:
    call sdk_example_dialogue(text="The path divides just beyond the gate.")
    call sdk_example_choice("Where next?", (("garden", "Visit the garden"), ("tower", "Climb the tower")))
    $ my_example_route = _return

    if my_example_route == "tower":
        call sdk_example_dialogue(None, "The steps wind above the trees.")
    else:
        call sdk_example_dialogue(None, "The garden is quiet this morning.")

    call sdk_example_input(initial=my_example_name)
    $ my_example_name = _return
    sdk_examples_guide "I'll remember you, [my_example_name!q]."

    call sdk_example_animation(travel=120, duration=0.6)
    return
```

Dialogue accepts a host `Character`, a speaker name, or `None` for narration.
Its text supports normal Ren'Py text tags and interpolation. The included
`sdk_examples_guide` is optional; pass your own speaker to keep your story's cast.

Choice accepts a nonempty sequence of `(string_id, caption)` pairs. Use unique
IDs, and branch on the returned ID instead of the displayed caption. The sample
layout is intended for short lists that fit the screen. Prompt and caption
strings are not interpolated. Choosing an option closes only this transient
screen.

Input starts with `initial`, limits edits to the positive `length` (24 by default),
and uses Ren'Py's normal input filters and platform keyboard support. Keep
`initial` within that length. It trims leading/trailing whitespace and returns
`fallback` (`"Traveler"` by default) for an empty or whitespace-only submission.
The screen's local answer does not write to persistent data. Assign its result
to your own story variable. Use `!q` when interpolating user text into dialogue
so Ren'Py text tags in that text are quoted. Android and web input retain the
limitations of `renpy.input`; this example adds no keyboard backend.

Animation moves a generated teal square and changes its opacity with ATL.
`travel` is the horizontal distance in pixels; keep it within the screen's
available width. `duration` is the positive number of seconds for each leg.
The default is 160 pixels and 0.8 seconds per leg. The transient screen closes
on **Continue**, removing its animation. No external image or media is needed.
Use the transform directly with your own image or screen, for example:

```renpy
screen my_signal:
    add Solid("#00d4c8", xsize=32, ysize=32) at sdk_examples_pulse(120, 0.6)
```

## Integration and verification

These are native story interactions. Call them on Ren'Py's story thread, as you
would other labels. Existing Flet interludes still use the APIs documented in
[the authoring guide](../../docs/renfletpy.md). Keep the demo's save adapter,
after-load callback, runner, and bridge when adapting that project. The examples
do not introduce save slots, migrate existing saves, or change recovery behavior.
The modified SDK's removed player rollback stays removed.

The compile/lint commands above check the optional gallery. Existing regression
checks remain:

```sh
python3 -m unittest discover -s tests -v
python3 scripts/check_native_story.py
python3 scripts/check_native_examples.py
```

The native checks need Xvfb, FFmpeg, and the prepared Ren'Py SDK. The committed
example driver compiles/lints an isolated gallery and exercises real keyboard,
choice, animation, history and native save operations. Recorded results
and scope are in [VERIFICATION.md](VERIFICATION.md).
