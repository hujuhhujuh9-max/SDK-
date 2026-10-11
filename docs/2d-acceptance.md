# Demanding 2D acceptance

These limits were specified before measuring the new workloads. The executable
specification is [workloads.json](../examples/2d/workloads.json), profile
`physical-api35-60hz-v1`. A passing import or an emulator screenshot does not
establish this profile.

| Workload | Nominal workload | Stress workload | Required behavior |
| --- | --- | --- | --- |
| Native Ren'Py | 128 animated sprites, 8 translucent compositing layers, 2 animated shader passes | 512 sprites, 16 layers, 4 passes | ATL translation, rotation and opacity; generated composite textures; two original fragment effects; a native continuation result |
| Flet Canvas | 2,000 primitives, 500 selectable nodes | 10,000 primitives, 2,500 nodes | One-finger pan, two-finger zoom, picking, camera reconstruction and visible input receipt |
| List and table | 10,000 data rows, 1,000 lazy ListView children, a 100-row × 4-column table page | 100,000 rows, 5,000 list children, 250-row table page | Editing, unsaved draft, page navigation, filtering and sorting off the Flet loop, stale result rejection |
| Interactive Rive | Two live controllers; one number, one boolean, a three-trigger catalog with one exercised trigger | No separate scale tier | Actual state-machine motion, typed inputs, a named event with properties, save/reopen, background/resume and disposal |
| Combined journey | Ten app → story → native animation → Canvas activity → Rive activity → app cycles | No separate scale tier | Save halfway through an activity, reopen and restore game values, return a result, retain the app draft and selection |

The table deliberately distinguishes data rows, Python controls and Flutter's
visible children. The default list sends 1,000 controls, uses the pinned
`ListView.build_controls_on_demand`, and the table sends a bounded page. It does
not claim that 10,000 editable TextFields can be mounted at once. Stress tiers
are discovery runs; a nominal pass cannot be reported as a stress pass.

## Physical phone limits

Use a physical Android API 35 ARM64 phone, the release APK, a 1080 × 1920
display fixed to 60 Hz, and no screen recording during frame measurements.
Record the model, OS build, device serial, ABI, display mode, APK SHA-256 and
source revision. Allow five seconds to warm up; then measure three separate
30-second continuous-motion windows per workload and per required surface.
Keep the same foreground workload active throughout each window. A trace must
contain at least 1,500 distinct presented frames for every measured surface.
The four individual workloads supply continuous-motion windows. The combined
journey supplies lifecycle, startup and whole-process memory evidence; idle
transitions are not treated as a continuous animation benchmark.

| Measurement | Limit |
| --- | --- |
| Frame presentation interval | p95 ≤ 20 ms, p99 ≤ 50 ms |
| Android FrameTimeline frames carrying a jank reason | ≤ 5% |
| Injected tap to a changed, captured input-receipt pixel | p95 upper bound ≤ 150 ms over at least 20 taps |
| Cold process launch to a captured enabled app control | p95 upper bound ≤ 4,000 ms over five force-stopped launches |
| Whole process PSS | ≤ 350 MiB at every recorded sample |
| Retained memory after ten complete navigation cycles | Final three-sample median minus initial three-sample median ≤ 20 MiB |
| Thermal status | Android severity ≤ 2 (moderate) throughout the run |

These are targets, not measurements already achieved. Percentiles use nearest
rank. Each of the three windows must pass; an average across windows cannot
hide a failed window. Cold-start and input times include ADB transport and
screenshot acquisition, so they are conservative upper bounds. They are not
hardware-touch-to-photon measurements. A captured pixel confirms a visible
response, whereas a Python handler log confirms only that a callback ran.

FrameTimeline supplies presented SurfaceFrames for the selected SDL and Flutter
surfaces. The harness derives presentation intervals from raw timestamps and
also retains pipeline durations and Android jank classifications. It cannot
infer SDL timing from Flutter's frame callback. Match surface names explicitly
after discovering the device's layers; ambiguous, empty or combined surfaces
remain unverified. If a renderer does not emit FrameTimeline frames on that
device, use an external frame capture or additional engine instrumentation;
the harness never replaces missing frames with zero-duration samples.

Use a Perfetto trace with FrameTimeline, process statistics and `gfx`, `view`
and `input` atrace sources. Preserve the binary trace, extraction SQL, raw CSV,
logcat, thermal and memory snapshots, screenshots and hashes. Recorded frame
statistics must be recomputed from these samples, not copied from a summary.
Memory is the entire shared-interpreter app process, including both renderers;
the navigation trend is separate from its peak. A ten-cycle trend does not prove
absence of every long-running leak.

## Evidence decisions

Each workload reports separate functionality and physical-performance states:

- `pass`: all required observations and applicable limits are satisfied.
- `fail`: an observed operation fails or a complete eligible measurement exceeds a limit.
- `unverified`: the build, hardware, size, raw samples, renderer attribution or
  required operations are missing. No exception, empty file, skip or reported
  average can turn this state into `pass`.

Linux timing is labeled `host_protocol`; software Android emulators are labeled
`emulator_functionality`. Neither is a physical-phone result. Existing
`flutter/lib/runtime_profile.dart` is a bounded, debug-only Flutter diagnostic
collector (600 retained samples). Its build/raster/total-span statistics exclude
SDL and cannot satisfy the physical-release frame gate. The Android intent
`runner.profile` also runs only in debuggable apps. Keep it for regressions and
do not silently expand its scope.

## Reproduction

The [2D project example](../examples/2d/README.md) installs the workloads through
`project_setup`, with no SDK route edits. Host measurements, functional protocol
checks, collection commands, and the current evidence status are recorded there.
Device collection requires ADB, a physical API 35 phone and Perfetto's
`trace_processor_shell`; the Linux environment alone cannot complete that gate.
