# Native tactics activity

The SDK includes the isometric board and height-aware movement adapted from the
owner's [2d-test](https://github.com/hujuhhujuh9-max/2d-test) repository at
[`7dc24c50ef8900ede31dd4bcdc01422b55d5addb`](https://github.com/hujuhhujuh9-max/2d-test/commit/7dc24c50ef8900ede31dd4bcdc01422b55d5addb).
That source includes the external-module startup fixes from its PR #1.
The source repository and SDK component branches are unchanged by this import.

In **Before the First Light**, complete or skip the star map, then choose
**Plan a balcony route** in the Flet field journal. Tap a unit and a blue
destination. Guide the teal Scout to the gold tile on the upper balcony.
Reset restores the board; Skip returns to the story. Android Back opens the
shared Flet menu, with the same reading settings, history, replay and quick save.

Authors can call the native activity from their Ren'Py script:

```renpy
call renfletpy_tactics
if _return == "reached":
    mira "The balcony is within reach."
else:
    mira "We can take that route another day."
```

Keep the shared integration screen active, as in the sample. The activity waits
in a native screen rather than an independent game loop. Flet remains hidden on
the board and opens for shared menu pages. Closing a menu returns to the same
positions. Native input and reset are guarded while menus or save/settings
commands are active. Completion uses the existing single-consumer result path;
it waits for Resume if a menu is open, records a history entry, and returns once.

`runtime/tactics.py` contains the renderer-independent board, movement field and
face draw queue. Solid terrain replaces its lower ground surface, while shelves
keep usable floors underneath. Tops, exposed cliffs, shelf undersides/fascias
and units are individual painter-sorted items. Movement uses four cardinal
neighbors, an equal cost per step, unit-specific movement/jump limits and occupied
surface blocking. The movement field also exposes `path_to(destination)`.

`game/tactics_display.py` draws that queue with Ren'Py's canvas and fits the
imported landscape board geometry inside the portrait scene. Input picking uses
the same board coordinates. External Python modules import the public
`Displayable`, `Render`, `redraw` and `restart_interaction` APIs from
`renpy.exports`; Ren'Py script blocks already have the public `renpy` namespace.

The authoritative positions and selected unit live in the immutable interlude
snapshot. Renderer copies cannot mutate that state. Native manual, worker
autosave and Android background saves capture it through the existing `SaveState`
adapter. Loading validates surface positions, occupancy, unit identity and result
before replacing the live story, then issues fresh event revisions. Earlier
version-1 panel/star-map snapshots remain accepted. The restored screen paints
the fresh model rather than treating its cached displayable as authoritative.

This is a small route-planning example, not a combat system: movement budgets
apply to each destination choice, with no turns, attacks, enemy AI, animation,
camera controls or custom-map loader. Painter sorting and picking cover this
fixed board; arbitrary tall overlapping geometry needs additional occlusion
rules. Interlude rollback remains blocked, as described in the authoring guide.

Verification is part of the existing SDK checks. Python tests cover terrain,
legal paths, face ordering, invalid snapshots and stale moves. The native Ren'Py
driver exercises the actual canvas/displayable, selection, movement at two
heights, reset, quick saves, worker autosaves, mobile saves, process loss,
shared-menu pause, result/history return and Skip. It retains screenshots.
Android device checks add real taps and framebuffer color probes for the moved
units, plus shared menus, quick load and automatic recovery in a fresh process.
