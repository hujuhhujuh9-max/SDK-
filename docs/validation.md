# Runner validation

The latest recorded application and device results are below. Older revisions
and their original scopes are in [the validation history](validation-history.md);
protocol and frame measurements are in [performance.md](performance.md).

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

## Scope and retained evidence

The device suite uses Android 35 x86_64, SwiftShader software graphics and
Flutter Impeller OpenGLES. It verifies story and tactics saves, fresh-process
recovery, native services, local media/assets, keyboard input, exact file
selections, service reuse, durable data, links, predictive Back and shutdown.
Source, APK hashes, display settings, UI trees, screenshots, framebuffer samples
and diagnostic receipts are retained with each workflow run. Artifact downloads
can expire; the pinned inputs and source remain available for rebuilding.

Physical ARM execution, release speed, actual biometrics, camera capture,
recording, GPS, flashlight, ads and advanced GPU paths remain unverified.
Recovery of in-flight native service operations is outside the recorded checks.
Media checks verify muted loading, duration and play/pause calls; audible output
and decoded video fidelity remain unverified. Service counts and a single memory
snapshot do not establish a native-memory improvement.

Release signing is unconfigured. See [capability coverage](flet-flutter-capabilities.md)
for the full service scope and [build environment](build-environment.md) for
reproduction requirements.
