# Runner validation

These results were recorded on 2026-10-03 for the fixed Flet/Flutter/Ren'Py
Android integration sample. Ren'Py owns startup and the single Python
interpreter; Flutter supplies the Flet UI with all 19 extensions.

| Check | Result | Evidence |
| --- | --- | --- |
| Preparation, branch boundaries, package pairing/preservation, JNI contract/executor, routing, demo cleanup, idle refresh, and APK compatibility | 45 host-independent Python tests pass; 15 prepared-Flet cases are intentionally skipped here and run below | [Build-input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128060536) |
| Real prepared Flet lifetime regressions | All 15 tests pass with zero skips: cancellation, late replies, send errors, session/channel cleanup, RawImage remount, and socket executor ownership | [Runtime integration](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37127007128), also repeated in the APK build |
| Real Flet protocol and shutdown | All 19 Python imports, handshake, UI patch, two stop/restart cycles, and shutdown during startup pass | Same runtime check |
| Protocol stress | 500 Increment events over five start/stop cycles produce the exact fresh UI patches, without idle traffic or remaining backend threads | Same runtime check; [measurements](performance.md) |
| Flutter analysis and regressions | Strict Dart analysis plus all 11 Flutter tests pass: eight backend lifecycle cases and three profiling cases | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37127007117) |
| Android debug APK | Flutter AAR, Ren'Py host, and the pinned backend assemble for all three target ABIs | Same APK build |
| Packaged component preservation | 541 prepared Python package/resource files and 369 Ren'Py common assets match their recorded checksums | [Android device check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128819256) |
| Native services and assets | All 23 checks pass, then pass again in a fresh process; includes explicit JNI workers, Page.run_thread, pubsub, and asyncio.to_thread, with Python/native storage agreement | Same device run |
| Input and platform callbacks | Text entry after committed focus, picker cancellation, share dismissal, camera permission grant, rotation, background/resume, and ordinary Back pass | Same device run |
| Links and predictive Back | Implicit cold/warm query-string links and a root link reach the correct view; a real edge swipe produces fresh start/progress/commit callbacks | Same device run |
| Clean shutdown/relaunch | Flet stops before Ren'Py exits, linked relaunch uses a new process, native services reattach, and both renderers continue | Same device run |
| Unhandled hardware key | F1 produces exactly one real down and one real up, with zero repeat/synthesized events | Same device run |
| Flutter frame probe | 20 more counter clicks update the Flet UI and Ren'Py counter; 52 timing samples recorded with zero dropped samples | Same device run; [timing scope and results](performance.md) |

The tested APK source is `46cf41161cf75050737ed763862f272b37f236a9`
([build 37127007117](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37127007117)).
The latest device harness source is
`a3be4b3bad3fe132e5c15d4b352bf7c534366d58`.
It verifies source compatibility before downloading/executing the APK.
Harness/documentation changes may reuse an APK; changes to app inputs,
including renamed inputs, require a compatible rebuild. Unknown, divergent,
reverse, or truncated comparisons are deferred. A deferred workflow is not
device-test evidence.

An earlier full run,
[37128748428](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128748428),
also passed with the same APK and harness
`051072379c1a31b545acbac56b43c0cbc46b6bb7`. The repeat run used
PID `2289` initially and `3335` after clean relaunch. The first full run
used `2311` and `3355`. Within each launch, all three readiness markers
agree on one process; fresh capability marker counts are required on each
invocation. Each full run contains 46 capability passes.

The emulator is provisioned, awake, unlocked, and in gesture navigation before
installation. First-use immersive help is marked confirmed so it cannot cover
the framebuffer. Startup requires app focus and a single unchanged process.
Text injection waits for the field's committed accessibility focus. Picker
cancellation targets the focused DocumentsUI window and requires its result
callback.

SDL's immersive window can consume the first edge swipe to reveal bars.
Both successful runs show zero gesture callbacks on that first swipe and
fresh started/progressed/committed callbacks on the immediate second swipe.
The harness accepts no earlier Back callbacks. SystemUI diagnostics record
gesture enablement, navigation visibility, exclusion regions, and the actual
motion log; returned Flet state and the SDL framebuffer must also pass.

[Download the tested debug APK](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37127007117/artifacts/11275780341).
[Device verification artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128819256/artifacts/11275922512)
include source comparisons/receipts, screenshots, UI trees, framebuffer samples,
logcat, window/activity/input-method diagnostics, SystemUI gesture state, and
frame/memory probe output.
[Protocol artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37127007128/artifacts/11274692659)
contain the 500-event measurement JSON and source receipt. Artifacts expire;
pinned component archives and source remain available for rebuilding.

The APK contains both native runtimes for `arm64-v8a`, `armeabi-v7a`,
and `x86_64`, and excludes Serious Python/Dart bridge runtime code.
Device checks use Android 35 x86_64 software graphics, with Impeller OpenGLES
reported on both launches. Debug raster timings are high; physical-GPU and
release-speed improvements have not been measured.

Physical ARM execution, actual biometric authentication, camera capture,
recording, GPS, flashlight, ads, animation assets, advanced GPU paths, and
arbitrary process-death recovery remain outside this validation. Media checks
verify muted loading, positive duration, and play/pause calls. Audible output
and decoded video-frame fidelity are unverified. The image-disposal guards are
source-inspected/compiled; no deterministic decoder-race or image-memory
benchmark has been recorded.

Release signing remains unconfigured. Final game content/layout is not supplied
by the SDK archives; the split view is an integration sample. See
[capability coverage](flet-flutter-capabilities.md) for integration limits.

Original main work remains all rights reserved. `PROJECT-NOTICE.txt` is
packaged in private app data, and third-party notices remain with their code.
Flet patches live on `sdk/flet-1.0.3`, pinned at
`3f23214e37e2f443cdeb8abe5da255b0f311b9e3`. Other components and archives
remain on their owning branches. Main consumes pinned patches during assembly.
