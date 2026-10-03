# Runner validation

These results were recorded on 2026-10-03 for the fixed Flet/Flutter/Ren'Py
Android integration sample. Ren'Py owns startup and the single Python
interpreter; Flutter supplies the Flet UI with all 19 extensions.

| Check | Result | Evidence |
| --- | --- | --- |
| Preparation, branch boundaries, package preservation, JNI, routing, concurrency, durable evidence, file reads, and APK compatibility | 62 host-independent Python tests pass; 15 prepared-Flet cases are intentionally skipped here and run below | [Build-input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155774140) |
| Real prepared Flet lifetime regressions | All 15 tests pass with zero skips, including cancellation, late replies, send errors, channel cleanup and executor ownership | [Runtime integration](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155774195), repeated in the APK build |
| Protocol and shutdown | All 19 imports, handshake, UI patches, stop/restart cycles, and shutdown during startup pass | Same runtime check |
| Protocol stress | 500 events over five start/stop cycles produce exact fresh UI patches, without idle traffic or remaining backend threads | Same runtime check; [measurements](performance.md) |
| Service references on repeated navigation | The same nine page-owned service IDs remain across 20 visits with cyclic collection disabled, including one audio service | Same runtime check; Python registry scope, native route acknowledgements stubbed |
| Flutter analysis and regressions | Strict Dart analysis plus all 11 Flutter tests pass: eight backend lifecycle and three profiling cases | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155774163) |
| Android debug APK | Flutter AAR and Ren'Py host assemble for arm64-v8a, armeabi-v7a and x86_64 | Same APK build |
| Packaged components | 541 prepared Python package/resource files and 369 Ren'Py common assets match recorded checksums | [Android device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37157449019) |
| Native services and assets | All 24 checks pass on four invocations across three processes: 96 fresh capability markers | Same device run |
| Durable storage | One random challenge survives clean exit and force-stop unchanged in app files, preferences and secure storage; existing values are read before writes | Same device run; storage-persistence.json |
| Native file selection | Four system-picker selections return exact binary fixture names, sizes and SHA-256 hashes, before and after forced restart | Same device run; file-selections.json |
| Reused native services | A reopened view passes the full suite again in the same process; three visits initialize one audio player | Same device run; capability-service-reuse.json |
| Input and platform callbacks | Focused text entry, picker cancellation, share dismissal, camera permission grant, rotation, background/resume and ordinary Back pass | Same device run |
| Links and predictive Back | Cold/warm query links and a root link reach the correct view; an edge swipe produces fresh start/progress/commit callbacks | Same device run |
| Shutdown and forced restart | Clean exit stops Flet first; clean and forced cold launches use new processes, reattach services and retain both renderers | Same device run |
| Hardware key and frame probe | F1 is delivered once per down/up; 20 additional counter events reach both renderers, with a bounded Flutter timing report | Same device run; [timing scope](performance.md) |

The tested APK source is `ad0ecd4624b7bca148a472fa5772a7691c29e9d5`
([build 37155774163](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155774163)).
The device harness source is
`5dc08af933583e9540e3123b778bf353eeacc60f`.
The harness verifies source compatibility before downloading/executing an APK.
Harness/documentation changes may reuse an APK; app-input changes, including
renamed inputs, require a compatible rebuild. Unknown, divergent, reverse or
truncated comparisons are deferred. A deferred workflow is not device evidence.
Read-only GitHub metadata requests have up to three attempts for transient API failures; failed response output is
discarded before retrying.

The successful device evidence is from attempt 2 of run `37157449019`.
Attempt 1 lost its ADB connection after the emulator reported a bad color-buffer
handle; it did not complete the suite. The repeat used the same APK and harness.

The latest device run uses PID `2270` initially, `3462`
after clean relaunch and `4273` after force-stop. Its challenge digest was
`be5ebe6b0b3f09b215c01fb020b1eae90df1334bf5803e4563c5b93dc9f3b131`.
All three readiness markers agree on one process within each launch. Every suite invocation
requires fresh capability and storage results; the second process runs the
suite again after reopening the view. The storage receipt retains its original
source PID and challenge digest through both restarts. Missing or mismatched
evidence fails instead of reseeding it. Test values are synthetic. Structured
storage receipts contain digests; full debug protocol logs can also include the synthetic service values.

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

The emulator is provisioned, awake, unlocked and in gesture navigation before
installation. Immersive help cannot obscure its framebuffer; startup requires
focus and one unchanged process. Text injection waits for committed focus;
the driver reacquires current bounds and permits at most three focus taps before failing.
Picker cancellation targets focused DocumentsUI and requires its result.

SDL's immersive window can consume the first edge swipe to reveal bars.
The gesture check retries immediately and requires new started/progressed/
committed callbacks, correct returned Flet state and the SDL framebuffer.
SystemUI diagnostics record enablement, visibility, exclusions and motion.

[Download the tested debug APK](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155774163/artifacts/11285284952).
[Device artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37157449019/artifacts/11286585304)
include source receipts, storage/file/service results, screenshots, UI trees,
framebuffer samples, logcat, input/window/activity and gesture diagnostics,
and Flutter frame/memory probes.
[Runtime artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155774195/artifacts/11285377056)
include the 500-event and 20-visit measurements with their source receipt.
Artifacts expire; pinned archives and source remain available for rebuilding.

Device execution uses Android 35 x86_64, SwiftShader software graphics and
Flutter Impeller OpenGLES. The APK includes both native runtimes for all three
target ABIs and excludes Serious Python/Dart bridge runtime code. Debug
raster times remain high; physical-GPU and release-speed improvements have
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
remain on sdk/flet-1.0.3 at `3f23214e37e2f443cdeb8abe5da255b0f311b9e3`.
Component branches and archives retain their ownership; main consumes pinned
patches during assembly.
