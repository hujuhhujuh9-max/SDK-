# Optional app starter acceptance

The explicit `app` startup template opens Home → Application records and can
start **The Lighthouse Note**, a callable native Ren'Py story. Its choice and
completion return plain data to the app. The default `story` template opens
**Before the First Light**. Both use the existing Ren'Py/SDL host and interpreter.

## Build and use

```sh
.android-build/venv/bin/python build_android.py --startup-template story
.android-build/venv/bin/python build_android.py --startup-template app
```

The default APK/artifact names are retained. App outputs use `runner-app-debug`
filenames and `runner-app-apk` / `runner-app-emulator-apk` artifact names.
The generated `project_config.py` matches in the native compile project and
packaged Python bundle. APK inspection rejects an unexpected mode or source
before device installation. Both modes retain the same 19 paired extensions,
resources, notices and verified Flutter AAR input identity.

In app mode, `/app` is home and `/app/records` opens the existing records store;
Back returns home. Start and Resume navigate only after native acknowledgement.
Return pauses the live interaction and pending choice. Quick save provides a
durable bookmark; completion retains that explicit bookmark for saved Resume.
Starting again requires confirmation when recoverable progress exists.

Native app saves, persistent state and `_reload-1` are isolated under the
platform-selected save root's `app-starter` directory. Application records keep
their existing native preferences key and are shared between startup templates.
Loading an older story never replaces newer records or the current app route.
See [session](app-session.md), [native story](app-story.md) and
[home UI](app-home.md) for the implemented boundary.

## Independent gates

E owns the acceptance harnesses and returns production failures to A–D.

```sh
.android-build/venv/bin/python scripts/check_runtime.py
.android-build/venv/bin/python scripts/check_app_starter.py --flet-root .android-build/runtime-inspection/flet
.android-build/venv/bin/python scripts/check_native_story.py --startup-template app --output .android-build/app-native-story-check
```

The prepared-Flet gate requires every selected test to run without skips. It
exercises real controls and method/event transport, stale acknowledgement and
completion rejection, Return/Resume acknowledgement, visible native results,
records independence, loading cancellation, unknown links, reconnect and
subscription cleanup. The complete prepared-Flet suite remains required.

The native gate launches eight real Ren'Py processes: default mobile seed,
independent app warm flow, app seed, cold recovery, saved Resume, completed
mobile seed/recovery, and original default recovery. It compares real default
save-file hashes through app-mode saves and loads. Separate local projects
prevent Ren'Py's desktop game-local save fallback from mixing the templates.
This local fixture is complemented by the actual Android gate.

The combined `integration/app-starter` workflow builds both modes from one
revision, then serializes the existing default Android suite and the app suite.
The app suite requires a same-source x86_64 default APK as its baseline:

```sh
.android-build/venv/bin/python scripts/device_smoke.py .android-build/outputs/runner-app-debug-x86_64.apk --abi x86_64 --startup-template app --baseline-apk .android-build/outputs/runner-debug-x86_64.apk --expected-display 1080 1920 420
```

On the same emulator it creates actual default quick/mobile saves, installs
the app APK without clearing app data, creates and edits records, loads an older
native checkpoint, completes the story, recovers a cold records link, compares
the original native save hashes and reinstalls the default APK to recover its
original scene. Success requires `app-starter.json`, mode/source inspections
for both APKs and the Android environment profile. Missing, empty or deferred
receipts fail the batch.

## Evidence status

Implementation is integrated from baseline
`c8d4dd1f2be678756d96bac228070b50b0539d14`. Local E validation passes the full
363-case prepared-Flet suite without skips, the 79-case app gate and two
additional source/ABI device-gate regressions. Protocol stress verifies 500
events over five backend cycles with no idle messages; service inspection
retains the same 14 services over 20 visits. The default native gate passes
68 checks across 12 processes; the app gate passes 24 checks across eight
processes, including original-default save recovery and unchanged save hashes.
Workflow lint, Python compilation and whitespace checks pass.

Review fixed an app unknown-route fallback that exposed a returned story choice
before Resume acknowledgement, and added visible records loading with Back
cancellation. Independent real-Flet regressions reproduce both defects and
verify the integrated fixes.

Combined APK/device evidence is pending and will be recorded after that gate
completes. Physical device setup and release signing are outside this batch.
