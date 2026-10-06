# Runner validation

## Invisible floors, terrain colors and saved camera modes — 2026-10-06

Empty floors are invisible in the native route activity. L0 (ground), L1
(terrain) and L2 (sky) have wire grids, with equal 160-unit vertical spacing
before camera scaling and dashed vertical guides in the default separated
Isometric view. Only terrain and units have filled shapes: horizontal terrain
tops are green, vertical walls are brown, and shelves have no thickness.

The linked terrain-opacity dial and slider blend each face once at the chosen
0–100% value, revealing opaque units through covering terrain. Isometric,
Top down and orthographic Side share four quarter-turn rotations, pan, zoom
and Center. Top down shows one selectable level at a time; Side is for
inspection. Mode, level, opacity, rotation, zoom, pan, positions and selection
survive quick, worker and Android background saves. Controls receive the
restored interlude revision before the first render, so level selection works
immediately after recovery without waiting for a counter or presentation change.

Verification uses the single Android 35 x86_64 profile:
**1080×1920 at 420 dpi**. All implementation changes are on SDK `main`;
the `2d-test` source repository, component branches and SDK lock are unchanged.

| Check | Result | Evidence |
| --- | --- | --- |
| Python regressions | 158 host-independent cases and 20 prepared-Flet cases pass, giving 178 unique cases overall; terrain queues without floor fills, camera transforms, level filtering, legacy saves and invalid snapshots are covered | [Input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37546796333); [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37543367265) |
| Actual Ren'Py | 43 checks across six real processes pass, including invisible ground/sky, terrain colors, exact alpha blending, dial/slider, all three camera modes and rotations, level filtering, movement, saves, fresh-process recovery with immediately usable controls, menu guards, one result/history return and Skip; 14 framebuffer probes verify painted pixels | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37546796291), native-story-check artifact |
| Real Flet protocol | 500 events over five backend cycles; the same 16 services across 20 visits; shared reading and save/load controls pass | [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37543367265) |
| Flutter and packaging | Strict analysis and all 11 Flutter cases pass; both APKs retain 541 Python resources and 369 common Ren'Py assets; 980 shared payload hashes match | Same APK build |
| Android 1080p activity | All 24 board flags pass: invisible grids, green/brown terrain, dial/slider transparency, equal spacing, three camera modes, four rotations, top-down level filtering and movement, side inspection, pan/zoom/Center, saved positions/views, fresh-process recovery, one result return and shared history; 21 framebuffer probes verify painted pixels | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37547789664) |
| Existing Android suite | All 19 story flags pass, alongside capabilities, media/assets, visible keyboard input, exact file selections, service reuse, durable storage, links, predictive Back, clean shutdown and cold restart | Same device check |

The application and device-harness source is
`554f1c503a10a59021fd9faad38c801bea38aafe`.
The [build artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37546796291)
include universal `runner-apk` and x86_64 `runner-emulator-apk` packages.
The x86_64 APK is 229,567,512 bytes with SHA-256
`3b424ca34bf07bc57ffea6ccdfe59c39769bee4034057edae4552fbb51921d73`.
The universal APK is 600,960,428 bytes with SHA-256
`a92b67e71876e61bd9ead85e9e0752a24b4bfaa4780954a0b30c7a5a1f089a0b`.

The `runner-device-check-1080p` artifact retains the board and story receipts,
21 painted-pixel records, all three camera modes, four rotations, level-filtered
frames, quick-load/recovery screens, result dialogue and shared history.
Diagnostic errors are empty, the board's Flet height is 0, and the device APK
hash matches the build. The application-source comparison is identical.

Quick load restores Top down on L0 in the East view at 120% zoom and 25%
opacity, with pan (59.58333333333334, -30.55555555555556). A newer
background save recovers Top down on L1 in the West view at 110% zoom and 50%
opacity, with pan (-35, 33.333333333333336), in
PID 6622 after source PID 4047 is stopped. Both restores preserve
the exact saved views and unit poses. The recovered L2 button changes levels,
the Scout reaches the goal once, and the result appears in shared history.
The separated grids, top-down filtering, side view and recovered controls
were visually checked. Physical ARM execution remains unverified.

See [tactics.md](tactics.md) for controls, saved state and limits.
This is a fixed-board route planner with no combat, turn system or custom-map
loader. The shared sample has one quick-save bookmark and blocks interlude
rollback.

## Earlier flat planes, transparency and camera controls — 2026-10-06

The native route board uses flat blue floor diamonds and warm brown vertical
wall panels. Shelves have no thickness or undersides; walls have no directional
shading. All floors share one color, with blue reachable outlines and gold
selection/goal outlines. The linked opacity dial and slider cover 0–100% and
reveal opaque units through covering terrain. A bounding-box adapter for
Ren'Py's center/radius ellipse API keeps selection rings at the projected feet.

The camera supports pan, zoom, Center and four quarter-turn views. Floor levels
remain 96 units apart before camera scaling, with matching ruler ticks. Picking
uses the same camera transform as drawing; rotating or dragging never changes
world-cell identities. Positions, selection, camera and opacity share native
manual, worker and Android background saves. Loads rebuild displayable caches
and reject stale controls. Legacy tactics saves receive the default view.

The current workflow uses one Android 35 x86_64 profile: **1080×1920 at 420 dpi**.
Earlier 720p records below are historical. All changes belong to SDK `main`;
the source `2d-test` repository, component branches and SDK lock are unchanged.

| Check | Result | Evidence |
| --- | --- | --- |
| Python regressions | 153 host-independent cases plus 20 prepared-Flet cases pass, giving 173 overall; flat geometry, camera transforms, paths and save validation are covered | [Input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37529130677); [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37527251316) |
| Actual Ren'Py | 38 checks across six real processes pass: rendering/input, plane colors, selection rings, opacity dial/slider, all four views, pan/zoom/Center, movement/reset, manual/worker/mobile saves, fresh-process recovery, menu guards, result/history return and Skip; eight framebuffer samples verify floor/wall colors, opacity and selection rings | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37529130678), native-story-check artifact |
| Real Flet protocol | 500 events over five backend cycles; the same 16 services across 20 visits; shared reading and save/load controls pass | [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37527251316) |
| Flutter and packaging | Strict analysis and all 11 Flutter cases pass; both APKs retain 541 Python resources and 369 common Ren'Py assets; 980 shared payload hashes match | Same APK build |
| Android 1080p activity | All 19 board flags pass: real taps/drags, flat plane colors, selection rings, dial/slider, all camera views, equal floor spacing, pan/zoom/Center, positions and view settings after quick load and fresh-process recovery, one result return and shared history; 13 framebuffer samples verify painted pixels | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37530253790) |
| Existing Android suite | All 19 story flags pass, alongside capabilities, media/assets, visible keyboard input, exact file selections, service reuse, durable storage, links, predictive Back, clean shutdown and cold restart | Same device check |

The application and harness source is
`e0487bc95c2cd11b1e653de67d4d11030c8cbbd0`.
The [build artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37529130678)
include universal `runner-apk` and x86_64 `runner-emulator-apk` packages.
The x86_64 APK is 229,561,140 bytes with SHA-256
`21d37c44d6ca039eb9da4718b78fc253991a4189f1fb4d234ac18cc70b8ba2b6`.
The universal APK is 600,954,056 bytes with SHA-256
`c32a80f9120f2c726d9ae3a0614a666f51e4a496e2e93d43defffd18bab4914e`.
The `runner-device-check-1080p` artifact contains the board and story receipts,
13 painted-pixel records, four camera-view screenshots, save/recovery frames,
result dialogue and shared history. Diagnostic errors are empty. The board's
Flet height remains 0. Quick load restores the East view at 120% zoom and 25%
opacity; a newer background save recovers the West view at 110% zoom and 50%
opacity in PID 5959 after source PID 4028 is stopped. Both paths preserve their
exact pan values. The floor/wall, controls and recovered layouts were visually
checked. The build and device APK hashes match, and the application-source
comparison is identical. Physical ARM execution remains unverified.

See [tactics.md](tactics.md) for the activity controls, saved state and limits.
This is a fixed-board route planner with no combat, turn system or custom-map
loader. The shared sample has one quick-save bookmark and blocks interlude
rollback.

## Earlier native 2D route activity — 2026-10-06

The SDK now includes the isometric terrain, face painter queue and height-aware
movement adapted from the owner's
[2d-test source](https://github.com/hujuhhujuh9-max/2d-test/commit/7dc24c50ef8900ede31dd4bcdc01422b55d5addb).
The optional **Field journal → Plan a balcony route** activity runs in Ren'Py's
native screen and returns one outcome to Mira's dialogue. Flet provides the
existing shared menu, reading settings and chronological history. Positions and
selected units use the existing immutable interlude snapshot and native save
adapter, including worker autosaves and Android background recovery.

The import is original integration on `main`. The source repository, Ren'Py,
RAPT, Flet and Flutter branches, and pinned component inputs are unchanged.
The older source app's Flet host patch was not imported.

| Check | Result | Evidence |
| --- | --- | --- |
| Python regressions | 148 host-independent cases and 20 prepared-Flet cases pass, giving 168 cases overall; terrain, movement, invalid saves, stale controls and native presentation are covered | [Input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37512306546); [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37505478046) |
| Actual Ren'Py | 32 checks across six processes pass, including actual canvas rendering/input, selection, ground and raised moves, reset, manual/worker/mobile saves, fresh-process recovery, paused results, shared history and Skip | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37505478123), native-story-check artifact |
| Real Flet protocol | 500 events over five backend cycles; the same 16 services across 20 visits; existing save/load and reading controls pass | [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37505478046) |
| Flutter and packaging | Strict analysis and all 11 Flutter cases pass; APKs retain 541 Python resources and 369 common Ren'Py assets; 980 shared payload hashes match | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37505478123) |
| Android activity | Both Android 35 profiles pass real taps, selection, ground/raised movement, reset, shared menus, positions/selection save/load, newer background recovery in a fresh process, one result return and its visible shared-history entry; six framebuffer samples per profile verify the painted Scout | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37512306364) |
| Existing Android suite | Both profiles pass story completion/skip, journal, ending, reading preferences, native/shared history, warm/cold saves and the capability, media/asset, input, picker, service reuse, storage, link, predictive Back and restart checks | Same device check |

The tested application source is
`3a654091a81371d7b1f66b6a3544da57ebbc045d`.
The final device harness source is
`e595754fe8b1e362d34c1fb671c14041f211a836`.
Only device-checker changes separate these sources; the device workflow verifies
application-source compatibility before running. The checker rejects unsuccessful
UI dumps rather than reusing coordinates from an earlier process and scrolls
history to verify the route result. Cold launches wait for a nonempty process ID
and ActivityManager's cleanup of the previous process.

Profiles are 720×1280 at 280 dpi and 1080×1920 at 420 dpi, using Android 35 x86_64
emulators. Physical ARM execution remains unverified.

[Build artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37505478123)
include the universal `runner-apk` and x86_64 `runner-emulator-apk`.
The tested x86_64 APK is 229,553,196 bytes with SHA-256
`e55b49c512027e1c133e04528a0a44328032366586a3cf913af3c4893a971093`.
The universal APK is 600,946,112 bytes with SHA-256
`c48600cdbf81be42e78c4cfbb12e647243dda05f63515ed3b2c63737384c5caf`.

Both receipts have all nine tactics flags and all 19 existing story flags true,
with journal result `constellation` and no diagnostic errors. The 720p route
records source PID 3993 and recovered PID 5318; the 1080p route records 4040
and 5374. Both board viewports have Flet hidden at height 0. Artifacts retain
the canvas/state logs, six painted-unit samples, result dialogue and
shared-history screenshots; the board and history layouts were visually checked.

See [tactics.md](tactics.md) for source attribution, `call renfletpy_tactics`,
save behavior and activity limits. This fixed-board route planner has no combat,
turn system, camera controls or custom-map loader. The shared sample still has
one quick-save bookmark and blocks rollback across interludes.

## Reading controls and paused results — 2026-10-06

The shared reading menu now changes native dialogue, Flet panels and history
text size together. Instant/animated dialogue preferences are saved by Ren'Py's
thread. They survive process loss and stay current when loading an older story
save or replaying. Failed writes restore the previous preference. Settings and
replay controls recover when a pending save completes. Automatic Android recovery
republishes native preferences to the fresh Flet backend, even when the saved
native timer was already initialized.

The native waiting screen holds completed interlude results behind shared menus
and diagnostics. Returning to the story consumes the result once and resumes
native dialogue. This covers a late minigame event arriving as the menu opens.

All changes are original project integration on `main`; the Ren'Py, RAPT,
Flet and Flutter component branches and pinned component inputs are unchanged.

| Check | Result | Evidence |
| --- | --- | --- |
| Python regressions | 139 host-independent cases and 20 prepared-Flet cases pass, giving 159 cases overall | [Input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37489524059); [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37489523957) |
| Real Flet protocol | Shared reading controls, cross-thread confirmation, unchanged puzzle progress, fresh save/load controls and chronological history; 500 events over five backend cycles and the same 16 services across 20 visits | [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37489523957) |
| Actual Ren'Py | 19 checks across three processes, including actual 40px native dialogue, instant/30cps preferences, persistence after process loss, reading preferences retained on older-save load, and completed results held behind menu/diagnostics until resume; existing scene, panel, worker autosave and mobile recovery checks pass | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37489523982), native-story-check artifact |
| Flutter and APKs | Strict analysis and all 11 Flutter cases pass; universal/x86_64 APKs retain 541 Python resources and 369 common Ren'Py assets; 979 shared payload hashes match | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37489523982) |
| Android reading controls | Both Android 35 profiles change text size and dialogue pace through the shared menu, retain newer preferences after older-save load and verify them after manual and background cold recovery; larger text is exercised throughout the story | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37490811547) |
| Existing native suite | Both profiles pass puzzle completion/skip, journal, ending, shared history, warm/cold saves, native scenes and the complete capability, asset, input, picker, service, storage, link, predictive Back and restart suite | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37490811547) |

The tested APK and harness source is
`cb401dcd2f9eb90b1fd7d70d62d30c7b8f91a839`.
Profiles: 720×1280 at 280 dpi and 1080×1920 at 420 dpi.
Physical ARM execution remains unverified.

[Build artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37489523982)
include the universal `runner-apk` and x86_64 `runner-emulator-apk`.
The tested x86_64 APK is 229,539,864 bytes with SHA-256
`d0e0feb0d558d29e3f9707b1f84211e5d62022403e54a049ce180ef4f0440081`,
matching both device inspections. The universal APK is 600,932,780 bytes with
SHA-256 `a59e49a4df2c19c5ab21b497685b351d19d51fabc989dca91810d2f125f6b7cc`.

Both receipts have all 19 story flags true and journal result `constellation`.
The 720p run records initial/save-source PID 2293, background-recovered PID 3630
and final restarted-story PID 4050; the 1080p run records 2301, 3618 and 4052.
Both diagnostic collections have no errors. Artifacts include larger native
dialogue, reading settings before/after cold recovery, older-save preference
retention, unified history and ending screenshots. These were visually checked
alongside the receipts.

See [renfletpy.md](renfletpy.md) for reading controls, authoring and save limits.
The sample still has one quick-save slot and blocks interlude rollback.

## Earlier unified story history and native recovery — 2026-10-06

Ren'Py owns the story loop, dialogue, native history and save/load context. Flet
provides the star map, journal choices, ending and shared menu. Native dialogue
and interlude results now appear in one chronological history. Loading restores
that history and removes entries from the discarded future timeline.

A native save adapter captures live interlude state during serialization,
including worker autosaves and Android background saves. The waiting labels
retain the native load position so restoration does not initialize a new game.
A successful load consumes the temporary recovery slot; quick save remains a
separate bookmark. Pending save/load commands hold interlude completions, replay
and quit. Reconnection refreshes an open history and save menu.

| Check | Result | Evidence |
| --- | --- | --- |
| Host regressions | 131 host-independent Python cases pass; 20 prepared-Flet cases pass separately, giving 151 cases overall | [Input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37465719372) |
| Runtime protocol | 500 actual protocol events over five cycles; single save/load submission; restored controls; chronological native-history updates across threads; stable identities for 16 services across 20 visits | [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37465719376) |
| Native Ren'Py | 11 checks across three real processes: quick save; mobile save; background-worker autosave; result return; panel load; discarded future history; chronological dialogue/results; ending/replay; native scene load; background save without manual save; fresh-process recovery. Temporary recovery files are consumed after load | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37463919454), native-story-check artifact |
| Flutter and packaging | Strict analysis and all 11 Flutter cases pass; universal/x86_64 APKs contain all 541 Python package/resource files and 369 common Ren'Py assets; 979 shared payload entries have identical SHA-256 hashes | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37463919454) |
| Android recovery | Both Android profiles preserve the one-star quick bookmark, recover a newer two-star background save in a fresh process, then reload the manual bookmark separately | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37465719364) |
| Story experience | Both profiles pass native dialogue, puzzle completion/skip, journal result return, combined history, native scene/history restoration, explicit ending, menu resume and replay | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37465719364) |
| Existing integration | Both profiles retain all native capability, visual asset, input, picker, service reuse, storage, link, predictive Back and restart checks | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37465719364) |

The tested application source is
`da1727fb0b5f99dbfd2154e7677a5ab96b2c946d`. The harness source is
`be637cb69bc0c44eff403fb2d420dc4f5104b9a0`. Profiles are Android 35,
720×1280 at 280 dpi and 1080×1920 at 420 dpi. Physical ARM execution remains unverified.

[Build artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37463919454)
include the universal `runner-apk` and x86_64 `runner-emulator-apk`.
The tested x86_64 APK is 229,536,364 bytes with SHA-256
`e1d4ce4873928c836ca41e03a8e23e0aced562f131743add551211b201464c5b`,
matching both device inspections. The universal APK is 600,929,280 bytes with
SHA-256 `9969465c458833dbf21e83ea53e7e4e88104444775f9931ee97eb4fa5723aad7`.
The workflow verifies application-source compatibility with the newer harness;
only checker changes separate those sources.

Device receipts and screenshots include automatic recovery, unified history,
the journal outcome and the ending. The 720p receipt records initial/save-source PID
2239, background-recovered PID 2972 and final restarted-story PID 3280; the 1080p
receipt records 2263, 2971 and 3284. All story receipt flags are true, both journal
results are `constellation`, and both diagnostic collections have no errors.
The harness identifies the main app process separately from transient native
Python helpers. Read-only UI dumps retry a killed snapshot process up to three
attempts; taps and intents execute once.

The sample still exposes one quick-save bookmark and blocks rollback across
interlude boundaries. The current [authoring guide](renfletpy.md) describes
native-save integration and adding custom minigames.

## Earlier RenFletPy save/load integration — 2026-10-06

At this earlier source, the shared menu submits quick-save/load commands to
Ren'Py's thread. The native save includes a versioned interlude snapshot; the after-load callback
restores progress and history with fresh event revisions and resumes the story
route. One quick-save bookmark survives app exit and replay. Interlude rollback
and a save-slot browser remain outside this sample.

| Check | Result | Evidence |
| --- | --- | --- |
| Host regressions | 117 host-independent Python tests pass; the 20 prepared-Flet cases run separately, giving 137 passing cases overall | [Input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37412605875), repeated during APK assembly |
| Prepared runtime | All 20 lifetime cases pass; 500 real protocol events over five backend cycles; stable identities for 16 services across 20 visits | [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37412605883) |
| Save/load boundary | Real Flet menu controls submit commands once, report busy/completed state, and rebuild restored controls with fresh revisions; old selections are rejected | Same runtime check |
| Ren'Py save system | Compile/lint pass; local runs under pinned Ren'Py 8.5.3 save/load one-star progress, complete the restored puzzle, restore native scene/history and load the puzzle in a fresh process | Local native save probes, repeated by the Android cases below |
| Flutter and packaging | Strict analysis, all 11 Flutter tests, universal/x86_64 builds, 541 Python package/resource files and 369 Ren'Py common assets pass; all 979 shared payload entries have identical SHA-256 hashes | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37412605931) |
| Native save/load | Both Android 35 profiles save a puzzle at one star, advance to two, load back to one in the same process, then force-stop and load it in a fresh process; the restored puzzle completes and returns its result to Ren'Py | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37413336759) |
| Native scenes and history | Both profiles save native dialogue, advance through the next line and story reset, then load the saved scene and completed interlude history; Flutter hides and SDL input resumes | Same device check |
| Existing integration | Both profiles also pass story outcomes, menu/background resume, replay, counter updates, all native capability checks, painted assets, input, picker, service reuse, durable storage, links, predictive Back and both restart paths | Same device check |

The tested APK and harness source is
`bd1b355ecbbbbc265933ac2c7a005d8d76bcc5f3`. The device workflow verifies source
compatibility before execution. The profiles are 720×1280 at 280 dpi and
1080×1920 at 420 dpi; physical ARM execution remains unverified.

[Build artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37412605931)
include the universal `runner-apk` and the smaller `runner-emulator-apk`.
The tested x86_64 APK is 229,530,748 bytes with SHA-256
`395b603faa57575316ea2ba290dfe028cd1a140252a1f5693491bcc7a7822855`,
matching both device inspections. The universal APK is 600,923,664 bytes with
SHA-256 `636626fd4ca323d3c1e7ba2604c871747c9b047527465ae4a647b02ee0528ab9`.

Device artifacts include `story-experience.json`, the save menu, warm/cold loaded
puzzle screenshots, restored native dialogue and restored interlude history.
The 720p receipt records save-source PID 2304 and restored-story PID 3013; the
1080p receipt records 2297 and 3010. All four save/load receipt fields are true,
and both diagnostic collections completed without errors. Restored native
scenes use the full SDL height with Flutter hidden.

The [authoring guide](renfletpy.md) describes the single bookmark, supported
snapshot format and the remaining rollback/custom-minigame save requirements.
Native Ren'Py autosaves are not exposed as an interlude save path by this menu.

## Earlier RenFletPy flow — 2026-10-06

The default application now uses Ren'Py for startup, the interpreter, the main
loop, scenes and ordinary `Character` dialogue. Flet opens for a star-map
minigame or optional panel, returns one result, then hides and restores SDL
input. The authoring API and current save/rollback limits are in
[renfletpy.md](renfletpy.md).

| Check | Result | Evidence |
| --- | --- | --- |
| Host regressions | 105 host-independent tests pass; 20 prepared-Flet cases run separately | [Input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37409259324), repeated during APK assembly |
| Prepared runtime | All 20 lifetime cases pass; 500 protocol events over five backend cycles; stable identities for 16 services across 20 visits | [Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37409259407) |
| Real interlude protocol | Puzzle moves and completion, single consumption, return to scene, cross-thread panel publication and menu/history resume pass | Same runtime check |
| Ren'Py authoring | Compile and lint pass for the sample and staged runtime modules | Local pinned Ren'Py 8.5.3 compile/lint; the APK build compiles the packaged project |
| Flutter and packaging | Strict analysis, 11 Flutter tests, universal/x86_64 builds, 541 Python package/resource files and 369 Ren'Py common assets pass; all 979 shared payload entries have identical SHA-256 hashes | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37409259503) |
| Native story/interlude | Both Android 35 profiles pass native dialogue, wrong-star retry, both minigame outcomes, history, menu/background resume, replay in the same process and hidden Flutter on return | [Device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37410046013) |
| Native integration | Both profiles also pass the complete existing counter, capability, asset, input, picker, service reuse, storage, link, predictive Back and restart suite | Same device check |

The tested APK and harness source is
`49f84d17d1d5027c9d1a090f0c2964836450ce29`. The device workflow verifies APK
source compatibility before executing it. The profiles are 720×1280 at 280 dpi
and 1080×1920 at 420 dpi; physical ARM execution remains unverified.

[Build artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37409259503)
include the universal `runner-apk` and the smaller `runner-emulator-apk`.
The tested x86_64 APK is 229,525,804 bytes with SHA-256
`cd6ae13b13e9eddd1dd5b34893cb07a81b879794e641e8436edb93cdd9850c9b`,
matching both device inspections. The universal APK is 600,918,720 bytes.
Device artifacts include `story-experience.json` and screenshots of native
dialogue, the Flet minigame, both scene results, the shared menu and interlude
history. Read-only ADB snapshots retry brief offline connections while taps
and intents execute once. Both diagnostic collections completed without errors.

At this earlier source, minigame progress and interlude history were in-memory
state. They survived menu navigation and background/resume, but restoring an
active Flet interlude from a Ren'Py save was not implemented. The sample blocked
rollback at interlude boundaries and did not expose save/load actions.

## Earlier integration evidence — 2026-10-04

These results were recorded on 2026-10-04 for the fixed Flet/Flutter/Ren'Py
Android integration sample. Ren'Py owns startup and the single Python
interpreter; Flutter supplies the Flet UI with all 19 extensions.

| Check | Result | Evidence |
| --- | --- | --- |
| Preparation, branch boundaries, package preservation, JNI, routing, concurrency, durable evidence, file reads, APK verification and disconnect diagnostics | 84 host-independent Python tests pass; 20 prepared-Flet cases are intentionally skipped here and run below | [Build-input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264641) |
| Real prepared Flet lifetime regressions | All 20 tests pass with zero skips, including service ownership before/after mounting, cancellation, late replies, send errors, channel cleanup and executor ownership | [Runtime integration](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37202567148), repeated in the APK build |
| Protocol and shutdown | All 19 imports, handshake, UI patches, stop/restart cycles, and shutdown during startup pass | Same runtime check |
| Protocol stress | 500 events over five start/stop cycles produce exact fresh UI patches, without idle traffic or remaining backend threads | Same runtime check; [measurements](performance.md) |
| Service references on repeated navigation | The same 16 page-owned service IDs remain across 20 visits and collection, including the seven core services and one audio service | Same runtime check; Python registry scope, native route acknowledgements stubbed |
| Flutter analysis and regressions | Strict Dart analysis plus all 11 Flutter tests pass: eight backend lifecycle and three profiling cases | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37205024407) |
| Android debug APKs | Universal and x86_64 APKs assemble from one staged integration; all 979 shared payload entries have identical SHA-256 hashes | Same APK build |
| Packaged components | 541 prepared Python package/resource files and 369 Ren'Py common assets match recorded checksums | [Android device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264666) |
| Native services and assets | All 24 checks pass on four invocations across three processes per emulator profile: 96 fresh markers each, 192 total | Same device run |
| Durable storage | One random challenge survives clean exit and force-stop unchanged in app files, preferences and secure storage; existing values are read before writes | Same device run; storage-persistence.json |
| Native file selection | Four system-picker selections return exact binary fixture names, sizes and SHA-256 hashes, before and after forced restart | Same device run; file-selections.json |
| Local visual output | SVG body and both colored chart bars paint within their semantic bounds on all four suite invocations per profile | Same device run; local-visuals.json and screenshots |
| Reused native services | A reopened view passes again with the same seven core service IDs; three visits initialize each core service and the audio player exactly once | Same device run; capability-service-reuse.json |
| Input and platform callbacks | Visible focused text entry above the keyboard, picker cancellation, share dismissal, camera permission grant, rotation, background/resume and ordinary Back pass | Same device run |
| Links and predictive Back | Cold/warm query links and a root link reach the correct view; an edge swipe produces fresh start/progress/commit callbacks | Same device run |
| Shutdown and forced restart | Clean exit stops Flet first; clean and forced cold launches use new processes, reattach services and retain both renderers | Same device run |
| Hardware key and frame probe | F1 is delivered once per down/up; 20 additional counter events reach both renderers, with a bounded Flutter timing report | Same device run; [timing scope](performance.md) |

The tested APK source is `24ca4fdf84a7ea086074f458342ba0a9ca600237`
([build 37205024407](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37205024407)).
The Linux protocol/service probe uses unchanged runtime inputs at
`731573b69e37ab6eb12feda9ca286acd94d701e8`; the APK build repeats all prepared tests.
The device harness source is
`b6afb12442873ccd32b8f63a5640cec342435616`.
The harness verifies source compatibility before downloading/executing an APK.
Harness/documentation changes may reuse an APK; app-input changes, including
renamed inputs, require a compatible rebuild. Unknown, divergent, reverse or
truncated comparisons are deferred. A deferred workflow is not device evidence.
Read-only GitHub metadata requests have up to three attempts for transient API failures; failed response output is
discarded before retrying.

The latest device check runs the same x86_64 APK at 720p/280 dpi and 1080p/420 dpi. Its inspected SHA-256 is
`8e45f1d5a84b440934f8c3a4d4d7297ccda251fc064242b26020f2b6fb83e481`, matching the build report. The universal APK retains
arm64-v8a, armeabi-v7a and x86_64; the x86_64 payload, code, assets and notices
are byte-identical between the two packages. APK signatures and removed native
ABI folders are the allowed differences. Physical ARM execution remains unverified.

The fullscreen host sizes both renderer panels above the IME and removes the
already-handled keyboard inset from the embedded Flutter view. The text-input
check requires a fully visible field before tapping, focused semantics while the full software
keyboard is open, native input-view visibility and matching IME surface geometry,
panel/input bounds above the keyboard, and a fresh Python
on-change receipt after Android text injection. Keyboard layout is recorded in
`keyboard-viewport.json`; Android 35 is the tested implementation path.

| Profile | Native IME occlusion (px) | Flutter top / height with keyboard (px) | Restored Flutter height (px) |
| --- | --- | --- | --- |
| 720p | 600 | 408 / 272 | 512 |
| 1080p | 901 | 612 / 407 | 768 |

Both require a shown software input view; the recorded occlusion matches Android's
IME surface hint. Text entry produces a fresh Python callback before dismissal,
and the driver then verifies zero keyboard overlap and the restored split.

Both profiles require fresh storage results from three distinct processes and
repeat the suite after reopening the view in the second process. All readiness
markers agree on one process per launch. Within each run, the original challenge
digest and source PID survive both restarts; missing or mismatched evidence fails
instead of reseeding it. Test values are synthetic. Structured receipts contain
digests; full debug protocol logs can include synthetic service values.

Each selected fixture is 71,750 or 72,006 bytes, containing non-text bytes,
UTF-8 text and a fresh random component. DocumentsUI grants native access,
the plugin copies into app cache, and the shared Python process reads the
returned path. Reads hash 64 KiB chunks on the worker pool, keeping the async
event loop available. Callback cancellation signals the chunk loop to exit and
close its file; regression checks require the active worker to stop and release
the picker guard. Fresh receipts are compared with the CI-created bytes;
each selection must retain the same app process.

A prior full run,
[37153138450](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37153138450),
verified storage, four file selections and 72 capability markers across three
processes before the service-reuse change. Its APK source was
`300debb6e003b5dd7c6665a9d2aa802226b39ed8`, with harness
`2a37666cde779c7468cede03cde5fbec9ec4aa94`.

## APK packaging measurement

Both packages come from [build 37205024407](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37205024407)
at source `24ca4fdf84a7ea086074f458342ba0a9ca600237`. APK sizes below are bytes before the
Actions artifact ZIP wrapper.

| APK | Bytes | Native ABIs | SHA-256 |
| --- | --- | --- | --- |
| runner-debug.apk | 600902912 | arm64-v8a, armeabi-v7a, x86_64 | 95c443a4346be78315e0c7e8c198b118069adcdff4c4bede288b180d02e1e0eb |
| runner-debug-x86_64.apk | 229509996 | x86_64 | 8e45f1d5a84b440934f8c3a4d4d7297ccda251fc064242b26020f2b6fb83e481 |

The x86_64 APK is 61.8% smaller and retains all 19 extensions, 541 prepared
Python package/resource files and 369 Ren'Py common assets. The build compares
979 shared payload entries, including retained native libraries, code, resources
and notices. `apk-builds.json` is included in both artifact downloads.

The second host assembly took 20 seconds in this build;
shared-payload hashing took about 5 seconds. Producing and uploading an additional artifact adds
build work. The measurement demonstrates fewer bytes for repeated emulator
download/installation, rather than an overall CI latency or runtime FPS gain.

## Device conditions and retained evidence

The emulator is provisioned, awake, unlocked and in gesture navigation before
installation. Immersive help cannot obscure its framebuffer; startup requires
focus and one unchanged process. Text injection waits for committed focus;
the driver reacquires current bounds and permits at most three focus taps before failing.
Picker cancellation targets focused DocumentsUI and requires its result.

SDL's immersive window can consume the first edge swipe to reveal bars.
The gesture check retries immediately and requires new started/progressed/
committed callbacks, correct returned Flet state and the SDL framebuffer.
SystemUI diagnostics record enablement, visibility, exclusions and motion.

[Download the universal debug APK](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37205024407/artifacts/11304363346).
[Download the x86_64 APK used in device CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37205024407/artifacts/11304298442).
[720p device artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264666/artifacts/11305330709)
and [1080p device artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264666/artifacts/11304985804)
include source receipts, keyboard layout/restoration, storage/file/service results,
SVG/chart screenshots, UI trees,
framebuffer samples, logcat, input/window/activity and gesture diagnostics,
Flutter frame/memory probes, APK inspection/selection reports, phase log
checkpoints, actual/configured display receipts and diagnostics.json. Failed reads retain earlier logs; cleanup
cannot replace the primary test error. Incomplete final diagnostics still fail
a suite that otherwise passed.
[Runtime artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37202567148/artifacts/11303567123)
include the 500-event and 20-visit measurements with their source receipt.
Artifacts expire; pinned archives and source remain available for rebuilding.

Both display profiles have the same 411.429 × 731.429 dp logical viewport.
The smaller profile has 921,600 pixels versus 2,073,600, reducing software
rendering area by 55.6%; both profiles run the full suite. Frame measurements
are scoped per profile in [performance.md](performance.md).

Device execution uses Android 35 x86_64, SwiftShader software graphics and
Flutter Impeller OpenGLES. The universal APK includes both native runtimes for
all three target ABIs; the smaller tested APK includes both for x86_64. Neither
package includes the obsolete Serious Python interpreter or Dart bridge runtime.
Debug raster times remain high; physical-GPU and release-speed improvements have
not been measured. Registry/player counts are not a native-memory benchmark.

Physical ARM execution, actual biometrics, camera capture, recording, GPS,
flashlight, ads, animation assets, advanced GPU paths, in-flight process-death
recovery and game-state restoration remain outside this validation. Force-stop
checks a cold restart and durable test data, not recovery of pending operations.
Media checks verify muted loading, positive duration and play/pause calls;
audible output and decoded video fidelity remain unverified. Image-disposal
guards are inspected/compiled, without a deterministic decoder-race benchmark.

Release signing remains unconfigured. The split view is an integration sample;
final game content/layout is not supplied by the archives. See
[capability coverage](flet-flutter-capabilities.md) for remaining limits.

Original main work remains all rights reserved. PROJECT-NOTICE.txt is packaged
in private app data; third-party notices remain with their code. Flet patches
remain on sdk/flet-1.0.3 at `ce1a18b26dda28febb69f50e24214ae910c95318`.
Component branches and archives retain their ownership; main consumes pinned
patches during assembly.
