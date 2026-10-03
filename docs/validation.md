# Runner validation

These results were recorded on 2026-10-03 for the fixed Flet/Flutter/Ren'Py
Android integration sample. Ren'Py owns startup and the single Python
interpreter; Flutter supplies the Flet UI with all 19 extensions.

| Check | Result | Evidence |
| --- | --- | --- |
| Input preparation, extension pairing, manifests, APK preservation, JNI callback contract, and initial/warm routing | 24 tests pass | [Build-input checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37092157479) |
| Real Flet protocol and shutdown | All 19 Python imports, handshake, UI patch, two stop/restart cycles, and shutdown during startup pass on Linux | `scripts/check_flet_bridge.py`, executed in the Android build |
| Flutter analysis and Android debug APK | Dart analysis, Flutter AAR, Ren'Py host, and the fixed backend assemble | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37085463712) |
| Packaged component preservation | 541 upstream Python package/resource files and 369 Ren'Py common assets match their original checksums | Device check's APK inventory |
| Native services and local assets | All 20 checks pass, including clipboard, preferences, secure storage, filesystem paths, authentication-support and permission-status queries, WebView, audio/video, Python native modules, JNI providers/worker callbacks, battery, connectivity, wakelock, brightness, accessibility, haptics, and URL-launch support | [Android device checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37092157473) |
| Input and platform callbacks | Text entry, picker cancellation, share dismissal, camera permission grant, rotation, background/resume, and ordinary Back pass | Same device run |
| Links and predictive Back | Implicit cold and warm `sdk-runner:///capabilities` links open the correct page; a real edge swipe produces fresh started/progressed/committed callbacks and returns to the shared counter | Same device run |
| Clean shutdown and relaunch | Flet stops before the Ren'Py process exits; an implicit linked launch starts a new process; all 20 capability checks pass again and both renderers update | Same device run |

The APK source is `202991bdda84bc3c05b31df0b39459e636d617fd`.
The device harness source is `38f79cc74e4ee549775f3c515796a60723ee5b21`. Its
`build-source.txt` records both source commits and the APK build run. All three
readiness markers agree on the process ID before and after relaunch. Fresh
marker counts are required for repeated capability checks; an earlier pass cannot
satisfy a later invocation.

The emulator is provisioned before app startup and uses gesture navigation.
The harness resolves Home after waking and unlocking the emulator, then
requires Runner focus and a single unchanged process during startup. If setup sends the live Activity into
the background, it brings that Activity forward; a missing or changed process
fails the check. This run needed one foreground restoration while Android's
`ImmersiveModeConfirmation` window held focus; startup retained PID `2353`.
Clean relaunch used PID `3463`, shared by all three readiness markers.
SDL's immersive window can consume the first edge swipe to reveal navigation
bars. The test immediately retries only when no new Back-start callback was
received, then requires actual start, progress, and commit callbacks plus the
shared counter and SDL framebuffer checks. Picker cancellation targets the
focused DocumentsUI window and waits for the app's result callback.

[Download the tested debug APK](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37085463712/artifacts/11260017952).
[Device verification artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37092157473/artifacts/11262706432) include screenshots,
UI trees, framebuffer samples, source receipts, logcat, and window/activity
diagnostics. GitHub artifacts expire; pinned component archives and source
remain available for rebuilding.

The final APK contains both native runtimes for `arm64-v8a`,
`armeabi-v7a`, and `x86_64`, and excludes the Serious Python/Dart bridge
runtime. Device checks use an Android 35 x86_64 emulator. Physical ARM devices,
actual biometric authentication, camera capture, recording, GPS, flashlight,
ads, and animation assets need dedicated device tests. Clean relaunch is
verified; arbitrary process-death recovery remains unverified. Both launches
reported Flutter's Impeller OpenGLES backend. Advanced GPU paths need dedicated tests. Media checks cover loading, duration,
and play/pause calls with muted assets, rather than audible output or decoded
video-frame fidelity.

Release signing is not configured. Final game content and layout are not
supplied by the SDK archives; the split view is an integration sample. See
[capability coverage](flet-flutter-capabilities.md) for integration limits.

Original main work remains all rights reserved. `PROJECT-NOTICE.txt` is
packaged in the app's private data, and third-party notices remain alongside
their corresponding code. Component changes stay on their owner branches;
main consumes their pinned patches during assembly.
