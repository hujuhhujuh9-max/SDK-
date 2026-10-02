# Runner validation

These results were recorded on 2026-10-02 for the fixed Flet/Flutter/Ren'Py
Android integration sample. Ren'Py owns startup and the single Python
interpreter; the sample contains both views and the full 19-extension Flet mix.

| Check | Result | Evidence |
| --- | --- | --- |
| Input preparation, paired extension packaging, and notices | Eleven tests pass | `python3 -m unittest discover -s tests -v`; [checks](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37062363789) |
| Real Flet protocol and shutdown | All 19 Python imports, handshake, UI patch, two stop/restart cycles, and shutdown during startup pass on Linux | `scripts/check_flet_bridge.py`, executed in the Android build |
| Flutter analysis and Android debug build | Dart analysis passes; full Flutter AAR, Ren'Py host, and fixed Flet backend assemble | [Build run 37023739518](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37023739518) |
| Android native services and assets | Clipboard, preferences, secure storage, filesystem paths, authentication-support and permission-status queries, local WebView, and local audio/video loading and playback controls pass | [Device run 37062363689](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37062363689) |
| Android input and lifecycle | Text entry, picker opening/cancellation, portrait/landscape changes, background/resume, and Back navigation pass | Same device run; UI trees and logcat in `runner-device-check` |
| Both renderers and shared Python state | SDL canvas pixels are checked at startup, after resume, and after Back before another update; both views then display the second counter increment | `renpy-*.json`, `returned.xml`, and `runner.png` in the same device artifact |

The tested APK was built from `96b2ba955893507b501fd9fb15d8e8f102559f51`.
The device-check harness was at `6fda0fb062d0d1a21a3cc0e95b0bb7c21c8c3d71`;
its artifact includes the APK's source-commit receipt. Ren'Py, Flet, and Flutter
reported process ID `2188`, and both views finished with `Count: 2` through
the shared Python module. APK inspection verifies both native runtimes for
`arm64-v8a`, `armeabi-v7a`, and `x86_64`, and excludes the Serious Python/Dart
bridge runtime.

[Download the tested debug APK](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37023739518/artifacts/11234611701).
The device artifact contains the final screenshot, UI trees, framebuffer pixel
samples, source receipt, and logcat. GitHub artifacts expire; the source, lock
files, and original component archives remain in the repository for rebuilding.

Device checks used an Android 35 x86_64 emulator. Physical ARM devices, real
biometric authentication, camera/recording/GPS/flashlight operation, ads, and
animation assets still need suitable-device tests. Clean Android quit/relaunch
and process-death recovery remain unverified. Predictive-back gestures and
Impeller are disabled in this proof build; see
[capability coverage](flet-flutter-capabilities.md) for integration limits.
Release signing is not configured. Final game content and layout are not
supplied by the SDK archives; the split view is an integration sample.

Original main work remains all rights reserved. `PROJECT-NOTICE.txt` is
packaged in the app's private data, and third-party notices remain alongside
their corresponding code. Component changes stay on their owner branches;
main consumes their pinned patches during assembly.
