# Runner validation

The fixed integration sample builds and runs on Android. These results were
recorded on 2026-10-02; they cover the shared runner, not a finished game.

| Check | Result | Evidence |
| --- | --- | --- |
| Branch input preparation and device-wait regression | Eight tests pass | `python3 -m unittest discover -s tests -v` |
| Real Flet protocol and shutdown | Handshake, UI patch, two stop/restart cycles, and shutdown during startup pass on Linux | `scripts/check_flet_bridge.py`, executed during the Android build |
| Android debug build | Ren'Py host, Flutter AAR, and fixed Flet backend assemble successfully | [Build run 36977015765](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/36977015765) |
| Android 35 x86_64 emulator | Both UIs render; the Flet button changes Ren'Py's counter; shared state survives background/resume | [Device check 36977524938](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/36977524938) |

The tested APK was built from `17db43224483936ab1954492c4cef6b58be44588`.
Ren'Py, Flet, and Flutter reported the same process ID, and the counter update
crossed from Flet's event handler to Ren'Py's screen through the shared Python
module. APK inspection verifies both native runtimes for `arm64-v8a`,
`armeabi-v7a`, and `x86_64`, and excludes the Serious Python/Dart bridge runtime.

[Download the tested debug APK](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/36977015765/artifacts/11214156068).
The device-check run contains the screenshot, UI trees, source-commit receipt,
and logcat output. GitHub artifacts currently expire after 90 days; the source,
lock files, and component archives remain in the repository for rebuilding.

Android checks have used the x86_64 emulator. Physical ARM devices, Android
rotation/back navigation, and Android quit/relaunch still need validation.
Release signing is not configured. The sample's split view is an integration
check; final game content and layout are not supplied by the SDK archives.

The original main-owned notice is packaged as `PROJECT-NOTICE.txt` in the app's
private data. Third-party notices remain alongside their corresponding code.
