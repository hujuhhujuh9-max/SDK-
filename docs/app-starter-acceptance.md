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
subscription cleanup. Confirmation cases preserve newer Records routes and
drafts through cancellation and native acknowledgement. The complete
prepared-Flet suite remains required.

The native gate launches ten real Ren'Py processes: default mobile seed,
independent app warm flow, app seed, cold recovery, saved Resume, completed
mobile seed/recovery, unsigned-save refusal/acceptance, and original default
recovery. The unsigned fixture removes only the signature entry from a real
bookmark; Ren'Py performs its normal signature check and native confirmation.
The native-only fixture models a connected host; separate real-Flet and Android
checks establish connection, routing, presentation and device input. It compares real default
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
original scene. It also exercises an unsigned real app bookmark with visible
native Yes/No touches, retains a newer Records intent after refusal, restores
the checkpoint after acceptance and restores the signed fixture bytes. Success
requires `app-starter.json`, mode/source inspections
for both APKs and the Android environment profile. Missing, empty or deferred
receipts fail the batch.

## Audit corrections — 2026-10-08

Delayed native Menu callbacks now require the original navigation revision,
so a newer Records link retains its destination. Saved Resume gives native
signature confirmation full presentation and input until load exits. It keeps
the latest requested app view, including across Flet reconnect and backend
restart, then releases busy state without replacing that view. App mode also
initializes the upstream confirmation adapter and its native Yes/No screen.

Independent local validation passes 395 prepared-Flet host tests with zero
skips, and all 89 app checks. The app native gate passes 28 checks in ten processes, including actual
unsigned-save refusal and acceptance, fresh checkpoint restoration and retained
default saves. Protocol stress passes 500 events over five cycles; service
inspection retains 14 identities over 20 visits. The default native gate passes
68 checks across 12 processes. Fresh APK and Android validation for these audit
corrections is pending; the following APK/device receipts cover the initial
feature source, before these runtime changes.

## Initial feature evidence

Implementation is integrated from baseline
`c8d4dd1f2be678756d96bac228070b50b0539d14`. Local E validation passes the full
369-case prepared-Flet suite without skips, including the device evidence-policy
regressions, and the 79-case app gate. Protocol stress verifies 500
events over five backend cycles with no idle messages; service inspection
retains the same 14 services over 20 visits. The default native gate passes
68 checks across 12 processes; the app gate passes 24 checks across eight
processes, including original-default save recovery and unchanged save hashes.
Workflow lint, Python compilation and whitespace checks pass.

Review fixed an app unknown-route fallback that exposed a returned story choice
before Resume acknowledgement, and added visible records loading with Back
cancellation. Independent real-Flet regressions reproduce both defects and
verify the integrated fixes.

The [combined run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37716841759)
builds source `5d745ec386de895620a5336a390187ee3dd7446a`.
CI passes all 365 prepared-Flet cases without skips. Its default native gate
also includes the original-story save compatibility fixture: 72 checks across
14 processes. The eight app native processes pass all 24 checks, and the
standalone native examples compile and run. Flutter analysis/tests pass for
both variants and both reuse phases; unchanged and Python-only phases each
report zero AAR compilations with fingerprint
`8748aab4fd36b7b314c90bbd60544d8d6fa1a0aec2213dacf68ae26713c437c4`.

Both modes retain 19 extensions, 541 upstream Python resources and 367 common
Ren'Py assets. Each universal/x86_64 pair has 980 byte-identical shared payload
entries. All four APK inspections identify the same source and expected mode.

| APK | Bytes | SHA-256 |
| --- | --- | --- |
| Default universal | 601282880 | `5c2670b427dce55d91b91d56c8cb0afd0ca7e8e07640e834570e9033ff7a07d1` |
| Default x86_64 | 229889964 | `2a4814232b920b59c6bee48aa094a3a552cf28b4fd36e21b2dbeea7418896de1` |
| App universal | 601283448 | `a2770ba240cfae57ba1c2389bd9294da30563f8888634151757046cde9a59f13` |
| App x86_64 | 229890532 | `c4758624b8d791ecd9201330eaa94e05531900c837941ac1ad5aaa1d6e388c53` |

The [default Android job](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37716841759/job/113119256408)
passes on Android 36 x86_64 at 1080×1920/420 dpi. Its receipts verify real
audio/video/Lottie output, native story and tactics, service reuse, files,
storage and records across older native loads, warm navigation and fresh
process recovery. Final diagnostic collection reports no errors.

The original combined run failed in E's app acceptance harness while reading
the default baseline's external save files, before the app APK was installed.
The corrected harness inspects the emulator's external-storage backing files
as root and restores ordinary ADB privileges after the read. The app process
keeps its own UID; required save digests and both APK identities remain checked.
The [targeted app gate, attempt 2](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37721403226/attempts/2)
passes all nine actual Android scenario checks. It uses the same verified APKs
with harness `a2b5875319a6563bc0704030305d148af4c7a3fa`; source comparison
confirms unchanged APK inputs. Its first attempt lost the emulator's ADB
connection during setup, before installing either APK. The successful retry
includes required receipts and complete diagnostics with no errors.

The baseline runs as PID `3615`, app flow as `5057`, completed cold recovery as
`6754`, and final original-default recovery as `7110`. App UID `10216` stays
unchanged across read-only save snapshots; ADB returns to shell UID `2000`.
The native app save directory is exactly the default root plus `/app-starter`.
Start, Return, live Resume and completion retain one app process; the cold
records link loads current records and retains the completed result on Back.
Loading an older native checkpoint preserves the newer record, and reinstalling
the default APK loads its original opening recovery with that shared record.

The default quick/mobile saves remain byte-identical through app installation,
manual loads, completion and completed cold recovery:

| Default native save | SHA-256 retained |
| --- | --- |
| `_reload-1-LT1.save` | `e0d4f0cbcdd0ddc3a0cac0a8ea3b236b28eee3e3cb4d740c8c64359cb46d29f3` |
| `renfletpy-quick-LT1.save` | `0aa94faff9c11a1a6302f49081645b5909f37dcf9d4450bb4226f22f6c7fa764` |

E downloaded and independently checked the runtime, native, default-device and
app-device receipts, APK identities, Android profiles and source compatibility.
Physical device setup and release signing are outside this batch.
