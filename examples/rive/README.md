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

Change progress to 55%, toggle **Grow the animated forest**, then open Menu and
save. Return to Home, close/reopen the app, load that save, and Resume. The saved
progress and boolean return; the animation controller is recreated from those
values. Background/foreground freezes/resumes playback. Set progress to 100%
and press **Send signal**. The actual Rive `FireGeneralEvent` trigger emits
`SomeGeneralEvent` with typed properties. The native story receives one result
with progress, boolean and that receipt. **Cancel transmission** returns an
explicit cancelled result with saved progress.

The signal artboard is intentionally a tiny official runtime event fixture. The
forest supplies visible animation and number/boolean response. The two ready
callbacks emit `SDK_2D_READY` only after both real controllers report their input
manifests. The signal fixture has three trigger inputs; this UI exercises one.
`SDK_CAP_RIVE_READY`, `INPUT`, `EVENT` and `LIFECYCLE` diagnostics include the
controller role, activity revision and detached callback data. Native Android
semantics identifiers `cap-rive-forest` and `cap-rive-signal` identify the
actual painting regions for device output checks.

Saved version 2 data is only `progress`, `downloading` and `receipt`; old version
1 progress-only data migrates with `downloading=True`. Live controls, controller
objects, listeners and transient triggers are excluded. Exact animation phase
is not saved. Sources and licensing are in [the fixture notice](assets/rive/NOTICE.md).

See [the Rive API/lifecycle documentation](../../docs/rive-integration.md) for
supported callbacks, input limits and actual test evidence. Linux rendered
output does not establish Android GPU or physical phone performance.
The [recorded Linux receipt](evidence/linux.json) and matched-time snapshots
provide actual playback/input/event/save evidence with those limits explicit.
The repeatable native save check is documented alongside the API.
