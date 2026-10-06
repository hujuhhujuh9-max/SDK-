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
The menu has resume, quick save/load, interlude history, replay confirmation,
diagnostics and quit.

## Saving and loading

**Menu → Quick save** writes one bookmark using Ren'Py's native save system.
Saving again replaces it. The menu reports success or failure, and **Quick load**
is enabled when a saved game exists. Loading returns directly to the saved story
interaction. The bookmark survives app exit, force-stop and replay.

The save includes normal Ren'Py scene variables and script position, together
with an active Flet interlude's choices, progress, feedback and result, plus the
latest 200 interlude history entries. Loading a partly completed star map returns
to that progress; completing it still supplies `_return` to the waiting script.
Loading a normal dialogue hides Flutter and restores native input.

Flet sends save/load requests through the bridge. A Ren'Py screen timer executes
them on the story thread. Before saving, it stores `story.snapshot()` in a Ren'Py
default variable and calls `renpy.retain_after_load()` so progress made during the
current interaction is preserved. The after-load callback restores that snapshot
with fresh event revisions, updates the native input screen's revision and
returns the Flet route to `/`. Controls from either earlier timeline cannot
advance the restored game.

This sample exposes one quick-save slot, without a slot browser or automatic
resume. If adding other save actions, capture the snapshot and retain it before
calling Ren'Py's save API, as `process_save_request()` does. Custom minigames need
to include their own saveable state and restoration rules in the model. Save
format version 1 supports the included panel and star map; future state-format
changes need an explicit migration. Native Ren'Py autosaves are not exposed by
this menu and are not the supported interlude save path.

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

The history retains the latest 200 interludes and their results.
Normal dialogue remains a Ren'Py say interaction. The sample blocks rollback at
interlude boundaries because external minigame state is not part of Ren'Py's
rollback store. The save snapshot restores interlude state on load; it does not
add minigame rollback.

## Diagnostics and checks

The counter and capability sample is available from **Menu → Device diagnostics**
or `sdk-runner:///diagnostics`. The capability route is
`sdk-runner:///capabilities`, returning to diagnostics on Back. The story/interlude
root is `/`; `/menu`, `/history` and `/restart` share its view stack.

Host tests cover ordering, concurrent and stale selections, single consumption,
snapshot round trips, invalid saves, main-thread save/load handoff and failure
recovery, return to scene, replay, navigation and subscription cleanup. The
prepared-Flet protocol test drives actual puzzle taps, passes the result to the
story owner, opens a panel from another thread and submits save/load requests
through real menu controls. It restores fresh controls and verifies history and
resume. Native serialization is checked by the Android harness. The 500-event
and service lifetime checks remain.

The Android harness checks native dialogue, the wrong-star retry, progress after
menu/background resume, both result branches, a hidden Flutter view on return,
interlude history and replay before the capability suite. It also saves a puzzle
at one star, loads it after advancing to two, loads it in a fresh process after
force-stop, completes the restored puzzle, then saves/loads a native scene and
its completed interlude history.
Screenshots and `story-experience.json` record those phases. Read-only ADB
snapshots retry brief connection failures; interaction commands execute once.
Native results and their source commits are in [validation.md](validation.md).
