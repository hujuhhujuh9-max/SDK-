# Interactive Rive in projects

The runner supplements the pinned `flet_rive` package with `SdkRiveExtension`.
The original 19-package catalog and its initialization remain present. Flet tries
extension factories in order, so this supplement precedes `flet_rive.Extension`.
It handles the existing Python `flet_rive.Rive` control and the new
`rive_control.InteractiveRive`. No project changes the SDK's central registry.
Adding or updating the Dart adapter requires rebuilding the APK.

## Pinned API review and repairs

This implementation uses Flet 1.0.3, Rive 0.14.11 and `rive_native` 0.1.11
(native library revision `0.1.11+3`). The packaged Flet adapter already exposes
source paths/URLs, headers, animations, machine names, fit/alignment, playback
speed, clipping and pointer handling. The runner keeps these operations using
Rive's public file/artboard/painter APIs. It adds only the missing input/event
control and lifecycle ownership.

`rive_control.RivePlayback` subclasses the pinned Python `flet_rive.Rive` and
inherits its animation, sizing and playback properties. It adds only the
missing `on_ready`, `on_lifecycle` and `on_error` callbacks. It uses the same
stock-control wire type and extension factory.

The pinned Python package serializes `artboard` and `use_artboard_size`, while
the pinned Dart adapter reads `art_board` and `use_art_board_size`. The runner
reads the canonical fields, with legacy aliases accepted when canonical values
are absent. The installed component source remains unchanged. Stock Python
controls therefore work through this runner without a component pin change.

The selected artboard is the single instance used for both painting and
intrinsic sizing. Changing an artboard or controller selection reuses the
loaded file. Source/header changes load a new file; a load finishing after
replacement/removal closes its unused file. Invalid selectors produce an error
instead of silently selecting a different artboard. Correcting an initial
selector or input error reuses the decoded file and creates a new painter.
File, artboard, animation,
machine, input, listener, event and custom-property ownership is explicit.

`enable_antialiasing` was already unused by the pinned adapter; this supplement
does not introduce a separate antialiasing setting. It uses the native Rive
renderer's defaults. Image/font/audio dependencies of arbitrary files and every
Rive feature are outside the supplied fixture evidence.

## Python control

```python
from rive_control import InteractiveRive

animation = InteractiveRive(
    src="rive/tree_loading_bar.riv",
    state_machine="Loading",
    numbers={"Progress": saved_model["progress"]},
    booleans={"Downloading": saved_model["downloading"]},
    height=220,
    on_event=lambda event: context.command("rive_event", event.data),
)
```

`numbers` and `booleans` are named root inputs on one selected machine. Number
values must be finite; booleans must be actual booleans. Unknown names, wrong
types, invalid selectors, decode errors and nonfinite speeds report errors.
Updates validate all names/types before changing any input. Nested input paths
and Rive data-binding view models are not part of this Python interface.
Rive recommends data binding for new assets, but the pinned runtime still
supports the number, boolean and trigger API exercised here.

Call `await animation.fire("FireGeneralEvent")` for a trigger. It returns an
accepted acknowledgement or raises `RuntimeError` with a specific rejection
reason. A trigger is rejected while loading, paused, backgrounded or disposed.
It is consumed immediately and never saved, queued for mounting, or replayed
after foregrounding/load. Updating number/boolean properties remains the
durable input path. `await animation.snapshot()` reads current scalar values
for diagnostics or an explicit model command; it does not save a story.

If a renderer rebuild or navigation removes the target while a method awaits
its reply, the pinned Flet lifecycle repair settles that caller with an
`unmounted before its method reply` error and keeps the transport connected.
The console drops status updates whose old control is no longer mounted.

All callbacks receive a normal Flet event whose `data` is a detached dictionary:

| Callback | Payload |
| --- | --- |
| `on_ready` | Selected artboard, dimensions, machine and animation names, root input types, current scalar values, effective `active` and `speed_multiplier` |
| `on_event` | Event `name`, `type`, `machine`, `seconds_delay`, scalar custom `properties`; URL events also include `url`/`target` |
| `on_input_change` | Current `numbers` and `booleans` after a property/machine/pointer change |
| `on_state_change` | Machine name and layer state name |
| `on_lifecycle` | Initial effective `active` state on attachment, then playback changes with their reason |
| `on_error` | Error `message` and source |

URL events are delivered as data; the adapter does not open links. The state
callback uses the pinned runtime's deprecated `onStateChanged` callback and
must be reviewed if that version changes. Native event/property wrappers are
copied and disposed before a callback crosses to Python. Post-frame callbacks
from a removed/replaced controller are dropped.

## Lifecycle and saved values

`playing=False` and speed zero freeze playback. Inactive, hidden, paused and
detached Flutter lifecycle states freeze playback; only `resumed` advances it.
A disabled `TickerMode` also freezes it. The guard runs before native advance,
so elapsed background time is not consumed. Pointer interaction and triggers
are disabled while frozen. Foregrounding resumes the existing controller;
removing the control disposes it and all of its native resources.

A newly attached painter applies its initial pose with a zero-time advance
after saved inputs and speed are set. A saved speed of zero therefore produces
a visible still image, reports `active=False` and consumes no elapsed animation
time. Its initial lifecycle callback reports `reason="properties"`.

Loading a story reconstructs the control, file, artboard, controllers and input
handles from the activity's plain number/boolean values. Animation timeline
positions and internal state-machine transitions are not serialized. Playback
starts at the selected machine's initial state with saved values applied.
If exact progress matters to a game, represent it as a model number/input.
Triggers and services do not become durable game values.

The example scopes control keys to the activity revision. Ordinary model
commands keep those keys; loading a native save changes the revision and
requires fresh controllers even in a renderer that retains keyed views.

Flet renderers submit plain commands/results. `ActivityContext` owns the
revision check, and the native story owner drains reducers and performs native
save/load/return. A Rive callback never calls Ren'Py exports or transfers a live
controller to a native save.

## Example and evidence

[The console project](../examples/rive/README.md) registers `rive_console`
through the project hook. Its version 2 model saves progress, the downloading
boolean and a validated event receipt. Version 1's progress-only model migrates
without replaying a trigger. The native story receives a completed or cancelled
`ActivityResult`, and normal SDK Menu/Save/Return/Resume remain available.
The console's Story menu button awaits that normal navigation; Return is
performed by the SDK menu's native acknowledgement. Cancellation is a reducer
command so a preceding queued progress edit appears in its returned value.

Three controls have separate roles. The forest exercises number/boolean inputs
and may naturally become still; the signal returns a meaningful typed trigger
event. A stock `RivePlayback` plays the official rover's genuinely looping
`bouncing` animation. The saved `downloading` boolean also sets the rover's
speed to one or zero, so pause survives model updates and save/load.

The forest asset exceeds its native transition iteration limit at input 100.
This example projects the forest's `Progress` input as `min(game_progress, 99)`;
the saved model, displayed progress and completion result still reach 100.
The generic SDK number-input interface remains unclamped. A real native test
renders the projected endpoint for ten seconds without that transition loop.

The fixture files are unmodified official MIT Rive test/example assets with source,
hashes and license in [their notice](../examples/rive/assets/rive/NOTICE.md).
They exercise a real `Loading` machine's number/boolean inputs and a real
event machine's trigger/custom/URL events, plus the rover's stock animation.

`tests/test_rive_activity.py` passes 15 cases with the prepared pinned Flet:
halfway plain save/reopen, migration, native thread ownership, stale callback
rejection, cancellation, renderer reconstruction and actual MessagePack
trigger/event transport. It also verifies cancellation after a queued edit,
awaited menu navigation and real fire/snapshot replies after unmount without
closing the socket or updating a detached renderer.
It also verifies the example-only 100-to-99 projection and saved pause across
ordinary model rebuilds. `flutter/test/rive_control_test.dart` passes ten cases
and exercises
native counters and rendered pixels: canonical nondefault artboard/sizing,
single file loading, atomically applied inputs, real events, trigger replay
rejection, paused/background frozen output, resume, reconstruction and late
loader disposal. Matched-time images independently isolate the number and
boolean effects. Every native allocation counter returns to its baseline.

The additional [loop receipt](../examples/rive/evidence/loop-validation.json)
records actual 140-by-140 rover pixels at 2, 5, 10 and 30 seconds of advanced
native animation time. Each pair is separated by about 0.367 seconds and uses
the device gate's sampled-pixel threshold. Fresh paused reconstruction and
background playback are byte-identical across another two seconds; resuming
changes pixels. This is a functionality check with the widget test clock,
not a measured phone frame-rate or memory result.

The historical two-controller [Linux receipt](../examples/rive/evidence/linux.json) includes
source/artifact hashes, the actual [trigger payload](../examples/rive/evidence/event.json)
and five independently compiled native save runs recorded with the original
eight-case Python and Dart suites. It predates the looping rover. The follow-up
lifecycle regressions require the pinned Flet
pending-method repair. The following snapshots use
the same 120 advances of 1/60 second at 320 by 220 pixels:

| Progress 25, downloading true | Progress 85, downloading true | Progress 85, downloading false |
| --- | --- | --- |
| ![25 percent animated forest](../examples/rive/evidence/matched-25-true.png) | ![85 percent animated forest](../examples/rive/evidence/matched-85-true.png) | ![85 percent forest disabled](../examples/rive/evidence/matched-85-false.png) |

`examples/rive/verify_native.py` uses the actual pinned Ren'Py save APIs.
It verifies normal SDK save/load, a native mobile save across process loss,
version 1-to-2 migration, old-callback rejection, menu completion gating and
single native completed/cancelled results. Its completion command carries
`event.json` produced by the real Dart trigger test. This joins the tested
wire/model/native contracts; it runs the Flutter renderer and native story
in separate host checks.

Flutter widget tests use the real native state machine with `Factory.flutter`
for CPU-rendered Linux output. Production uses `Factory.rive`. These tests
establish the exercised playback/control/lifecycle behavior; they do not prove
Android native-renderer performance or physical API 35 phone performance.
The coordinator's integrated APK/device receipt is separate evidence.

To repeat the Flutter checks in the staged module, prepare Linux test libraries
before testing (the normal Android build also performs this preparation):

```sh
dart run rive_native:setup --platform linux
flutter analyze --no-pub lib test
flutter test --no-pub test/rive_control_test.dart --reporter expanded
```

The pinned setup verifies its published native library hash. Test snapshots
are written to `build/rive-evidence/*.png`; paused snapshots are byte-identical,
and matched-time 25%/85% and downloading true/false outputs differ.

From the integrated SDK root, repeat the native save acceptance using that
freshly generated trigger receipt and your prepared Ren'Py SDK:

```sh
python3 examples/rive/verify_native.py \
  --renpy-sdk /path/to/renpy-8.5.3-sdk \
  --xvfb /path/to/Xvfb \
  --event-json /path/to/staged-flutter/build/rive-evidence/event.json
```

Full per-process logs and receipts remain under `.android-build/rive-native-check`.

## Integrated Android evidence

The [API 35 combined artifact](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38142196387/artifacts/11702514282)
passes all three actual controller readiness manifests, number/boolean input
changes, looping playback, byte-identical pause, resume and Android
background/foreground callbacks. Quick load reconstructs progress 50 with
playback disabled; a fresh process restores progress 50 with playback enabled.
At game progress 100, the forest receives its declared visual value 99 and a
real signal trigger returns typed event properties to the native story exactly
once. Every observed ready controller in the final process is disposed.
The untouched download passes raw-file revalidation. The
[batch receipt](project-capabilities-batch.md) binds the SDK, harness and APK
identities. This establishes the exercised Android functionality; physical
phone performance remains the user's manual measurement phase.
