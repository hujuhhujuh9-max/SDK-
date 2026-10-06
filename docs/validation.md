# Runner validation

## Unified story history and native recovery — 2026-10-06

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
