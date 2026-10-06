# RenFletPy story interface

The default application presents one Ren'Py scene with Flet dialogue over it.
Ren'Py owns startup, the interpreter, scene rendering and story flow. Flet owns
the dialogue controls, choices, transcript and shared menu. Opening a menu does
not advance the story; returning restores the same pending line.

The Android host keeps the SDL scene at the full usable height. A transparent
Flutter texture draws the dialogue card in a bottom dock. Its rounded corners
reveal the scene underneath, and touches above the dock still reach SDL. Menus
use the full Flutter viewport. Both layouts stay above the keyboard. Android
Back opens the shared menu from the scene or dialogue; Back within a menu
returns through the same Flet view stack.

## Authoring a scene

`game/script.rpy` supplies a reusable `renfletpy_say` label:

```renpy
label opening:
    scene evening
    call renfletpy_say("Mira", "Where should we go?", (
        ("sky", "Look at the sky"),
        ("dome", "Enter the observatory"),
    ))
    if _return == "sky":
        scene stars
        call renfletpy_say("Mira", "There is still time before sunrise.")
    else:
        scene observatory
        call renfletpy_say("Mira", "Let me show you the telescope.")
    return
```

Omitting `choices` produces one **Continue** control. IDs are the values
returned to the Ren'Py script; labels are the displayed text. The label publishes
the line and waits on `renfletpy_input`, leaving Ren'Py's event loop responsive.

The lower-level API is `renfletpy.story.show(speaker, text, choices)`. It returns
a revision. Flet submits `story.choose(revision, choice_id)`; the story thread
receives it once with `story.consume(revision)`. No Flet callback invokes Ren'Py
rendering or flow APIs. Old revisions, unknown IDs and repeated taps are rejected.
UI notifications are scheduled on Flet's own event loop, and page subscriptions
detach on disconnect, reconnect and backend shutdown.

The sample, **Before the First Light**, demonstrates two branches with a scene
change, subsequent lines and replay. The menu includes resume, transcript, replay
confirmation and quit. The transcript retains the latest 200 lines and selected
choice labels in memory. Replay runs on the Ren'Py thread and invalidates old
choice revisions. Transcript and dialogue synchronization are not yet wired into
Ren'Py save/load or rollback; the sample does not expose those actions.

## Diagnostics and validation

The previous shared-counter and capability sample is available from **Menu →
Device diagnostics**, or at `sdk-runner:///diagnostics`. The native capability
page remains at `sdk-runner:///capabilities`, returning to diagnostics on Back.
The story is at `/`; `/menu`, `/history` and `/restart` use the shared story stack.

Host tests cover concurrent and delayed choices, single consumption, replay,
menu/transcript state retention and subscription cleanup. The real prepared-Flet
protocol check also publishes a new line from another thread and verifies
choices, transcript navigation and resume. The existing 500-event protocol and
native-service lifetime checks continue on the diagnostics route.

The Android device harness first exercises the default story and retains
screenshots plus `story-experience.json`. It checks the full SDL viewport,
branch-dependent painting, Back after scene focus, transcript, menu/background
resume and replay in the same process, then runs the existing capability suite.
Native validation results are recorded in [validation.md](validation.md).
