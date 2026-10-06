# RenFletPy interludes

Ren'Py owns Android startup, the interpreter, the main event loop, normal scenes
and dialogue. Flet provides temporary minigames and panels at explicit points in
the script. Both run in one Android process and one Python interpreter.

The default **Before the First Light** sample starts with a normal Ren'Py
`Character` line. Tapping it opens a Flet star-map minigame. Connect Deneb, Vega
and Altair in order, or skip it. The result returns to the Ren'Py script and
selects the next scene and dialogue. Wrong moves can be retried; completed stars
cannot be tapped twice. The puzzle keeps its progress through menu navigation
and background/resume. A Flet field-journal panel offers a memory to keep; its
choice returns to another native line. The ending waits for **Play again** or
**Close story**, keeping the menu and history available until then.

During normal story interactions, Flutter is hidden and input belongs to the
full-size SDL view. An interlude displays a full-size transparent Flutter texture
over that view; menus use an opaque page. SDL keeps its full usable height.
Closing the interlude hides Flutter and restores SDL focus. Android Back and the
native scene's Menu button open the same Flet menu without advancing the story.
The menu has resume, quick save/load, story history, replay confirmation,
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

Android also creates a separate native background save. If the backgrounded
process is lost, the next launch automatically restores the scene or interlude,
including moves made since the quick save. Returning normally from the background
removes that temporary recovery save. The manual bookmark remains available.
Successful loads also consume any temporary recovery save, so a later launch
cannot resurrect a discarded timeline.
Quitting deliberately uses the quick bookmark for the next visit; the menu
still exposes one manual slot.

Flet sends save/load requests through the bridge. A Ren'Py screen timer executes
them on the story thread. The default variable `_renfletpy_saved_state` holds
`renfletpy.SaveState()`, whose pickle hook captures `story.snapshot()` during
native serialization. This covers manual saves, the native autosave worker and
Android background saves without invoking Ren'Py from Flet or the save adapter.
The interlude labels call `renpy.retain_after_load()` before waiting, keeping
the native load position inside the input screen instead of restarting the
minigame initialization. The after-load callback restores the snapshot with fresh
event revisions, updates the input screen's revision and returns to the story.
An explicit diagnostics deep link is preserved during automatic recovery.
Controls from either earlier timeline cannot advance the restored game.

Other native save actions automatically include Flet state. Keep the save adapter,
after-load callback and waiting labels when adapting this sample. Custom minigames
need their own saveable state and restoration rules. Save format version 1 supports
the panel and star map; future changes need a migration. The earlier plain-dict
quick-save state is accepted and upgraded. Older recovery saves with no Flet
snapshot can resume a native scene; an unrestorable interlude starts over safely.
Native autosaves preserve interludes but have no browser in the shared menu.

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

Story history uses Ren'Py's native history list for normal dialogue and completed
Flet results. The waiting interlude is appended to the display until its result
is recorded on the story thread. Plain text snapshots cross to Flet; Ren'Py text
tags are stripped. This keeps chronological history, save restoration and replay
consistent, including removal of lines from a future timeline after loading.
The display retains the latest 200 entries and refreshes while open.

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
through real menu controls. It restores fresh controls and verifies native-history
publication across threads. `scripts/check_native_story.py` runs the actual pinned
Ren'Py SDK under Xvfb: manual, mobile and worker autosaves; panel and scene loads;
history chronology and discarded future entries; explicit ending/replay; and
background recovery in a fresh process. The APK build runs it before assembly.
Its receipts and logs are in the `native-story-check` artifact. The 500-event
and service lifetime checks remain.

The Android harness checks native dialogue, the wrong-star retry, progress after
menu/background resume, both result branches, a hidden Flutter view on return,
story history and replay before the capability suite. It also saves a puzzle
at one star, loads it after advancing to two, loads it in a fresh process after
force-stop, completes the restored puzzle, then saves/loads a native scene and
its completed history. A newer two-star state is saved by backgrounding Android,
then recovered automatically after force-stop; the one-star quick bookmark is
checked separately. The harness plays the journal choice and ending too.
Screenshots and `story-experience.json` record those phases. Read-only ADB
snapshots retry brief connection failures; interaction commands execute once.
Native results and their source commits are in [validation.md](validation.md).
