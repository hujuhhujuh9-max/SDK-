# Native tactics activity

The SDK includes the isometric board and height-aware movement adapted from the
owner's [2d-test](https://github.com/hujuhhujuh9-max/2d-test) repository at
[`7dc24c50ef8900ede31dd4bcdc01422b55d5addb`](https://github.com/hujuhhujuh9-max/2d-test/commit/7dc24c50ef8900ede31dd4bcdc01422b55d5addb).
That source includes the external-module startup fixes from its PR #1.
The source repository and SDK component branches are unchanged by this import.

In **Before the First Light**, complete or skip the star map, then choose
**Plan a balcony route** in the Flet field journal. Tap a unit, then a destination
with a blue outline. Guide the teal Scout to the gold tile on the upper balcony.
Reset restores the board; Skip returns to the story. Android Back opens the
shared Flet menu, with the same reading settings, history, replay and quick save.

Floors are flat 2D diamonds in blue; vertical wall panels use a contrasting
warm brown. Ground, raised floors and shelves share the same floor color.
There are no slab edges, undersides or directional wall shading. Blue outlines
mark reachable destinations, and gold outlines mark the selection and goal.

Tiles start at 60% opacity. Turn the touch dial or move its linked slider from
0% (clear terrain) to 100% (opaque terrain). Planes blend individually over
already-painted floors and units; units stay opaque and can be seen through
covering terrain. Tile outlines, reachable destinations and the gold goal remain
visible at zero opacity.

Drag the board to pan. Rotate left/right turns the camera by 90° around the
board's center, with four isometric views. Zoom buttons change the scale from
65% to 180%; a mouse wheel also zooms. Center returns pan and zoom to the fitted
view, keeping orientation and opacity. A drag threshold separates panning from
taps, and camera changes never move units or alter movement budgets.
All three floor levels use the same 96-unit vertical step before camera scaling;
the floor ruler shows that spacing in every orientation. Vertical wall panels
are divided at those floor boundaries; shelves have no visual thickness.
Reset route restores positions and selection while keeping your view settings.

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
positions. Native input, reset, camera and opacity controls are guarded while
menus or save/settings commands are active. Completion uses the existing single-consumer result path;
it waits for Resume if a menu is open, records a history entry, and returns once.

`runtime/tactics.py` contains the renderer-independent board, movement field and
plane draw queue. Solid terrain replaces its lower ground surface, while shelves
keep usable floors underneath. Flat floors, exposed wall panels and units
are individual painter-sorted items. Movement uses four cardinal
neighbors, an equal cost per step, unit-specific movement/jump limits and occupied
surface blocking. The movement field also exposes `path_to(destination)`.

`game/tactics_display.py` composites that queue into an alpha-enabled SDL surface
and blits it into Ren'Py's native Render. This blends each plane over the scene
instead of replacing the alpha of previously drawn geometry. Selection rings
use a bounding-box adapter for Ren'Py's center/radius ellipse API, keeping them
at the unit's feet. The camera fits the
imported landscape board inside the portrait scene. Drawing, depth sorting and
input picking share the camera transform, retaining world-cell identities.
External Python modules import the public
`Displayable`, `Render`, `redraw` and `restart_interaction` APIs from
`renpy.exports`; Ren'Py script blocks already have the public `renpy` namespace.

The authoritative positions, selected unit and `TacticsView` live in the immutable
interlude snapshot. Renderer copies cannot mutate that state. Native manual, worker
autosave and Android background saves capture it through the existing `SaveState`
adapter. Loading validates surface positions, occupancy, unit identity, result
and finite, bounded camera/opacity values before replacing the live story, then
issues fresh event revisions. Earlier version-1 panel/star-map snapshots remain
accepted; earlier tactics snapshots without view settings receive the default
camera and 60% opacity. The native load callback rebuilds displayable caches
from the restored model.

This is a small route-planning example, not a combat system: movement budgets
apply to each destination choice, with no turns, attacks, enemy AI, animation,
custom-map loader. Painter sorting and picking cover this
fixed board; arbitrary tall overlapping geometry needs additional occlusion
rules. Interlude rollback remains blocked, as described in the authoring guide.

Verification is part of the existing SDK checks. Python tests cover terrain,
legal paths, plane ordering, invalid snapshots and stale moves. The native Ren'Py
driver runs at 1080p and exercises the actual displayable, dial/slider, covered-unit
pixels at zero/half/full opacity, different floor/wall colors, selection rings
and movement through all four views,
pan/zoom/centering, movement at two heights, reset, quick saves, worker autosaves, mobile saves, process loss,
shared-menu pause, result/history return and Skip. It retains screenshots.
Android device checks use the single 1080p workflow profile and add real taps,
drags, dial/slider touches and framebuffer color probes for transparent cover
and moved units. Camera and opacity must survive shared menus, quick load and
automatic recovery in a fresh process.
