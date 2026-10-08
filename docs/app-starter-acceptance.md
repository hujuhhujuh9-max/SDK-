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

The native gate launches twelve real Ren'Py processes: default mobile seed,
independent app warm flow, app seed, cold recovery, saved Resume, completed
mobile seed/recovery, unsigned-save refusal/acceptance through both saved Resume
and Menu → Quick load, and original default
recovery. The unsigned fixture removes only the signature entry from a real
bookmark; Ren'Py performs its normal signature check and native confirmation.
The native-only fixture models a connected host; separate real-Flet and Android
checks establish connection, routing, presentation and device input. It compares real default
save-file hashes through app-mode saves and loads. Separate local projects
prevent Ren'Py's desktop game-local save fallback from mixing the templates.
This local fixture is complemented by the actual Android gate.

The combined **Verify integrated app recipes** workflow builds both modes for
relevant `main` pushes and `integration/app-starter` acceptance from one revision,
then serializes the existing default Android suite and the app suite.
The app suite requires a same-source x86_64 default APK as its baseline:

```sh
.android-build/venv/bin/python scripts/device_smoke.py .android-build/outputs/runner-app-debug-x86_64.apk --abi x86_64 --startup-template app --baseline-apk .android-build/outputs/runner-debug-x86_64.apk --expected-display 1080 1920 420
```

On the same emulator it creates actual default quick/mobile saves, installs
the app APK without clearing app data, creates and edits records, loads an older
native checkpoint, completes the story, recovers a cold records link, compares
the original native save hashes and reinstalls the default APK to recover its
original scene. It also exercises an unsigned real app bookmark with visible
native Yes/No touches through saved Resume and Menu → Quick load, retains newer
Records intents after refusal and acceptance, restores the checkpoint after
acceptance and restores the signed fixture bytes. Success
requires `app-starter.json`, mode/source inspections
for both APKs and the Android environment profile. Missing, empty or deferred
receipts fail the batch.

## Audit corrections — 2026-10-08

Delayed native Menu and Resume callbacks now require the original navigation
revision. Native navigation also tracks client delivery and acknowledgement,
so an already-sent request cannot replace a newer Records route or draft.
Guarded client repairs respect further route changes; repeated native requests
avoid waiting for route events that Flet suppresses. Ordinary buttons and Back
retain their normal Flet route calls. Independent tests separate actual client
route state, buffered events and method replies.

Saved Resume gives native
signature confirmation full presentation and input until load exits. It keeps
the latest requested app view, including across Flet reconnect and backend
restart, then releases busy state without replacing that view. App mode also
initializes the upstream confirmation adapter and its native Yes/No screen.

Menu → Quick load also owns native presentation while `renpy.load()` runs.
Only a consumed load command can acquire it, and only its ownership token can
release it. Cancellation, errors and successful native control transfer release
the scope in `finally`; newer routes and reconnects cannot cover the prompt.
Release restores the latest requested presentation without navigating the page.
Quick save and the default story's startup remain unchanged.

The [fresh combined batch](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37800002372)
builds source `ae8697b43c23db5559415ac854874db8831b9953`. Local and CI
prepared-Flet suites pass 405 host tests with zero skips; the app gate passes
96 tests. Protocol stress passes 500 events over five cycles with no idle
messages, and downloaded service receipts retain 14 identities over 20 visits.
Native receipts pass 72 default checks in 14 processes, including original-story
bookmark compatibility, and 28 app checks in ten processes. The app native gate
exercises actual unsigned-save refusal and acceptance, fresh checkpoint
restoration and retained default save bytes. Native examples compile and run.

The build job passes Flutter analysis/tests for both modes and both reuse
phases. It rejects the restored AAR candidate and compiles one current AAR,
then verifies reuse for the app variant and both warm phases. Unchanged and
Python-only phases each compile zero AARs with fingerprint
`38feffb858c5a5b897818603387afcc66640bdbe8cfe698f8d44772d76f342f2`.
All four APK inspections identify this source and their expected startup mode,
with 19 extensions, 541 upstream Python resources and 367 common Ren'Py assets.
Each universal/x86_64 pair has 980 byte-identical shared payload entries.

| Fresh APK | Bytes | SHA-256 |
| --- | --- | --- |
| Default universal | 601287896 | `9c7c2c41a953ff98177b989192cf836c0c7d71017f8185996f5b50b10eb837b6` |
| Default x86_64 | 229894980 | `9cce91d0709e2229af9585742bf688e84786014afb1dcf31c8145eb9319340d8` |
| App universal | 601290168 | `10ed92acfa6f04a4eeb3bfffdcb5d63b06da95d360c5c1a0dc4123793c2c536f` |
| App x86_64 | 229897252 | `8bf5ff7996b1ac21f6ccff2214748080c905f18c3b61787fa070bcb341988bda` |

Both fresh Android jobs pass on API 36 x86_64 at 1080×1920/420 dpi:
[default](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37800002372/job/113397145050)
and [app](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37800002372/job/113409397726).
The default suite includes seven durable Records scenarios, native story,
input, media and relaunch checks. The app suite passes all eleven scenarios,
including the previously failing older-checkpoint/newer-Records case.

Actual Android No/Yes touches exercise an unsigned app bookmark in PID `6850`,
app UID `10216`. Prompt screenshots and viewport receipts show a full native
scene, zero Flet height and zero keyboard overlap. Refusal retains the newer
Records route and releases busy state; acceptance restores the real bookmark,
completes the story and retains current records. The fixture removes only the
signature member. Both writes preserve its inode, owner, group and mode, and
the restored signed SHA-256 exactly matches the original. Read-only save
inspection restores shell UID `2000`; the app remains under its own UID.
Original default quick/mobile hashes remain unchanged, and reinstalling the
same-source default APK recovers its original scene in PID `7885` while keeping
the edited app record. Earlier No/Yes raw logcat is cleared before that final
reinstall; screenshots, fixtures and success-only assertions support those
checks, while retained logcat confirms the final default recovery.

The preceding
[batch](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37788795900), from
`6ecc04360758134cd9c6c79ebce55ec831383e69`, passed native/build and default
Android but exposed an in-flight native Resume arriving after a newer Records
link and replacing its view. The edited record remained in native preferences.
The latest routing correction, independent wire regressions and fresh Android
gate resolve that failure. The following historical APK/device receipts cover
the initial feature source, before these audit corrections.

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
