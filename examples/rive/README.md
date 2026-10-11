# Rive transmission console

Build this standalone application from the SDK repository:

```sh
python3 build_android.py --project examples/rive/renfletpy.json
```

The project hook registers `rive_console`; the project's native story overrides
the opt-in app starter's story label. Start story from Home to enter the activity
through normal SDK navigation. No SDK route or activity-kind list is edited.
The Flutter supplement ships in the runner, so a new APK is required to install
this adapter. The pinned original Rive package remains in the 19-package catalog.

Change progress to 55%, toggle **Play the forest and looping rover**, then open Menu and
save. Return to Home, close/reopen the app, load that save, and Resume. The saved
progress and boolean return; the animation controller is recreated from those
values. Background/foreground freezes/resumes playback. Set progress to 100%
and press **Send signal**. The actual Rive `FireGeneralEvent` trigger emits
`SomeGeneralEvent` with typed properties. The native story receives one result
with progress, boolean and that receipt. **Cancel transmission** returns an
explicit cancelled result with progress derived by the native reducer, including
an edit queued immediately before cancelling. **Story menu** opens the normal
SDK menu; its Return action owns the native app/story handoff.

The signal artboard is intentionally a tiny official runtime event fixture. The
forest supplies number/boolean response and can naturally settle to a still
image. A third stock Rive control plays the official rover's looping `bouncing`
animation. The saved boolean also sets its speed to one or zero, so a paused
save reopens with a visible still rover. The three ready callbacks emit
`SDK_2D_READY` once per renderer only after all real controllers report their
manifests. The signal fixture has three trigger inputs; this UI exercises one.
`SDK_CAP_RIVE_READY`, `INPUT`, `EVENT` and `LIFECYCLE` diagnostics include the
controller role, activity revision and detached callback data. Native Android
semantics identifiers `cap-rive-forest`, `cap-rive-signal` and `cap-rive-loop` identify the
actual painting regions for device output checks.

The forest asset's native transitions exceed their iteration limit at input
100. The example projects that input to `min(progress, 99)` while displaying,
saving and returning the actual game value 100. This fixture limit does not
change the SDK's generic number-input API.

Saved version 2 data is only `progress`, `downloading` and `receipt`; old version
1 progress-only data migrates with `downloading=True`. Live controls, controller
objects, listeners and transient triggers are excluded. Exact animation phase
is not saved. Sources and licensing are in [the fixture notice](assets/rive/NOTICE.md).

See [the Rive API/lifecycle documentation](../../docs/rive-integration.md) for
supported callbacks, input limits and actual test evidence. Linux rendered
output does not establish Android GPU or physical phone performance.
The historical [two-controller Linux receipt](evidence/linux.json) and
matched-time snapshots record input/event/save evidence. The new
[loop receipt](evidence/loop-validation.json) records actual rover motion at
2, 5, 10 and 30 seconds of native animation time, paused reconstruction,
background/resume and native cleanup. The widget clock establishes
functionality, not a phone performance measurement.
The repeatable native save check is documented alongside the API.
