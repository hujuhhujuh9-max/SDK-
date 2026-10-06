# RenFletPy interludes

Ren'Py owns Android startup, the interpreter, the main event loop, normal scenes
and dialogue. Flet provides temporary minigames and panels at explicit points in
the script. Both run in one Android process and one Python interpreter.

The default **Before the First Light** sample starts with a normal Ren'Py
`Character` line. Tapping it opens a Flet star-map minigame. Connect Deneb, Vega
and Altair in order, or skip it. The result returns to the Ren'Py script and
selects the next scene and dialogue. Wrong moves can be retried; completed stars
cannot be tapped twice. The puzzle keeps its progress through menu navigation
and background/resume.

During normal story interactions, Flutter is hidden and input belongs to the
full-size SDL view. An interlude displays a full-size transparent Flutter texture
over that view; menus use an opaque page. SDL keeps its full usable height.
Closing the interlude hides Flutter and restores SDL focus. Android Back and the
native scene's Menu button open the same Flet menu without advancing the story.
The menu has resume, interlude history, replay confirmation, diagnostics and quit.

## Authoring

Write scenes and dialogue normally. Call a Flet interlude only where needed:

```renpy
define mira = Character("Mira")

label opening:
    scene observatory
    mira "Help me find the summer triangle."
    call renfletpy_minigame("star_map")
    if _return == "aligned":
        scene stars
        mira "You found it."
    else:
        mira "We can try another night."
    return
```

`renfletpy_minigame` and `renfletpy_panel` are reusable labels in
[game/script.rpy](../game/script.rpy). The included `star_map` returns `aligned`
or `skipped`. A simple Flet panel accepts title, text and optional ID/label pairs:

```renpy
call renfletpy_panel("Travel journal", "Choose the next stop.", (
    ("garden", "Visit the garden"),
    ("tower", "Climb the tower"),
))
if _return == "tower":
    jump tower
```

Omitting choices gives a **Continue** button. `_return` is the selected ID.
These calls wait on a Ren'Py screen timer, keeping its event loop responsive.
The included game is one example; adding another requires its Flet controls and
state transitions in `runtime/story_ui.py` and `runtime/renfletpy.py`.

## The boundary

`renfletpy.story.minigame(kind)` or `story.show(title, text, choices)` opens an
interlude and returns a unique revision. Flet submits moves or a choice against
that revision. The Ren'Py thread polls `story.consume(revision)` once, closes it
with `story.close(revision)`, and returns the value from the label. Flet callbacks
never call Ren'Py flow or rendering APIs. Delayed events, unknown IDs and repeated
completion taps are rejected. Notifications schedule rendering on Flet's own
loop; subscriptions and menu callbacks detach on disconnect and shutdown.

The history retains the latest 200 interludes and their results in memory.
Normal dialogue remains a Ren'Py say interaction. The sample blocks rollback at
interlude boundaries because external minigame state is not part of Ren'Py's
rollback store. Durable minigame save/load and restoring an active interlude are
not implemented; the sample does not expose save/load actions.

## Diagnostics and checks

The counter and capability sample is available from **Menu → Device diagnostics**
or `sdk-runner:///diagnostics`. The capability route is
`sdk-runner:///capabilities`, returning to diagnostics on Back. The story/interlude
root is `/`; `/menu`, `/history` and `/restart` share its view stack.

Host tests cover ordering, concurrent and stale selections, single consumption,
return to scene, replay during native dialogue, navigation and subscription
cleanup. The prepared-Flet protocol test drives actual puzzle taps, passes its
result to the story owner, closes it, opens a panel from another thread and
checks history/menu resume. The 500-event and service lifetime checks remain.

The Android harness checks native dialogue, the wrong-star retry, progress after
menu/background resume, both result branches, a hidden Flutter view on return,
interlude history and replay in the same process before the capability suite.
Screenshots and `story-experience.json` record those phases. Read-only ADB
snapshots retry brief connection failures; interaction commands execute once.
Native results and their source commits are in [validation.md](validation.md).
