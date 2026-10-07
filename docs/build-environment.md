# Linux build environment for Android

The development host is Linux x86_64; the product runs on Android. The supplied
Flutter Linux SDK supplies the build tools for the Android target.

| Requirement | Baseline | Purpose |
| --- | --- | --- |
| Python | 3.12 or later | Verify and prepare branch-owned archives |
| Git and Git LFS | Installed on the build host | Fetch pinned archive objects |
| JDK | 21, including `javac` | Ren'Py Android packaging and Gradle |
| Android SDK platform | `platforms;android-36` | RAPT compile/target SDK 36 |
| Android platform tools | `platform-tools` | Device installation and diagnostics |
| Android Gradle plugin | 8.13.0, bundled RAPT prototype | Existing Ren'Py build baseline |
| Gradle wrapper | 9.1.0, bundled RAPT prototype | Shared Android build |
| Android NDK | 28.2.13676358 | Flutter 3.44.8 module build |
| Python build packages | `requirements-build.txt` | Render the component's build template |
| Python runtime packages | `runtime/requirements.txt` | Fixed Flet backend dependencies |
| FFmpeg | Installed on the build host | Generate the small local-video integration fixture |
| Xvfb | Required for native story checks | Exercise actual Ren'Py rendering, saves and recovery |

JDK 21 is required by the
[Ren'Py Android documentation](https://www.renpy.org/doc/html/android.html).
The Android SDK and Gradle values above come from the pinned RAPT archive:
`buildlib/rapt/install_sdk.py`, `prototype/build.gradle`, and
`prototype/renpyandroid/build.gradle`. The bundled prototype currently lists
minimum Android API 21. The integrated host uses minimum API 24, matching
the supplied Flutter SDK's `FlutterExtension.kt`.

Set `JAVA_HOME` to an installed JDK 21 and `ANDROID_HOME` to the Android SDK.
With Android command-line tools installed, the required baseline packages are:

```sh
sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-36" \
  "build-tools;36.0.0" "ndk;28.2.13676358"
```

`build_android.py` uses the RAPT Gradle wrapper, keeps native Ren'Py startup,
builds Flutter as a debug AAR, and links both into the main-owned host. Its
debug APK uses Gradle's debug signing; release signing is not configured.
The build preserves third-party notices and uses MsgPack's Python fallback
instead of copying a Linux extension into Android.
The fixed extension catalog is assembled from the pinned Flet source. AndroidX
Fragment 1.8.9 and AppCompat 1.7.1 supply the shared host's fragment and theme
requirements; their integration declarations belong to main.

The generated Flutter module uses RAPT's AGP 8.13.0 too. Flutter 3.44's default
AGP 9 module disables built-in Kotlin, but the pinned file-picker plugin skips
its Kotlin plugin on AGP 9, leaving its Android classes uncompiled. Aligning the
generated module with the host resolves that build mismatch without changing
either SDK. `flutter/pubspec.lock` pins the resolved Dart dependencies.

## APK outputs and emulator setup

The default build produces two debug APKs from one staged Flutter AAR, Python
bundle, game assets and native host:

| File | Native ABIs | Use |
| --- | --- | --- |
| runner-debug.apk | arm64-v8a, armeabi-v7a, x86_64 | Debug installs across the packaged ABIs |
| runner-debug-x86_64.apk | x86_64 | Android emulator verification |

The second host assembly uses `-PrunnerAbi=x86_64`; the Flutter AAR is built
once. Unsupported ABI values fail Gradle configuration. Both APKs must retain
the complete 19-extension catalog, Python package/resource inventory and Ren'Py
common assets. SHA-256 comparisons require identical shared payload entries,
including code, resources, notices and retained native libraries. Only removed
ABI folders and regenerated signature entries may differ.

`apk-builds.json` records filenames, ABIs, byte counts, checksums and verification
counts. The build publishes `runner-apk` and `runner-emulator-apk`; each includes
the report. Device CI prefers the emulator artifact and checks source
compatibility before using it. Older compatible universal artifacts remain
supported.

Device CI runs an Android 35 x86_64 emulator at 1080p with two guest CPU cores,
2 GiB configured memory and SwiftShader software graphics:

| Profile | Pixels | Density | Logical display (dp) |
| --- | --- | --- | --- |
| 1080p | 1080 × 1920 | 420 dpi | 411.429 × 731.429 |

1080p is the single workflow profile for the full capability and story suite.
The Ren'Py sample uses a 720×1280 virtual UI scaled to the physical 1080p display;
virtual coordinates are independent of framebuffer resolution. AVD LCD, density and
skin settings are explicit; actual device settings must match before installation.
The emulator version probe also uses `-no-window -no-audio`, selecting the
headless binary without requiring desktop audio libraries.
The workflow uploads `runner-device-check-1080p`.
`emulator-profile.json` records configured values;
`device-environment.json` records actual API, ABI, display, density and host CPU count.

With an Android 35 x86_64 emulator already running:

```sh
python3 scripts/device_smoke.py .android-build/outputs/runner-debug-x86_64.apk --abi x86_64 --expected-display 1080 1920 420
```

The expected-display option verifies the 1080p configuration before installation.
Without that option, the standalone driver records the actual display settings.

Without `--abi`, the driver requires the universal three-ABI APK. The supplied
ABI must match the APK contents; missing capability metadata fails before
device execution.

ADB commands have deadlines: 60 seconds ordinarily, 15 for PID lookup and
diagnostic reads, 30 for raw framebuffer capture, and 180 for the initial
device wait. Fresh logs are saved after initial capability checks, clean
relaunch, frame profiling and view reentry. Final collection attempts device,
window, activity, input-method, logcat and screenshot diagnostics independently.
`diagnostics.json` lists unavailable snapshots. An earlier log is retained if
a later read fails. Cleanup cannot replace the primary test error, and missing
diagnostics after an otherwise successful suite still fail verification.

Every native suite invocation also scrolls to the local SVG and bar chart,
requires full fixture heights before checking expected RGB pixels inside their
semantic bounds, and saves
screenshots and `local-visuals.json`. Fresh `core-service-reuse.json` receipts
require the same seven core service IDs on repeated checks in one process.
The complete prepared-Flet page/service set contains 16 instances.

The fullscreen SDL host cannot rely on Android's ordinary window resize when
the keyboard opens. It lays out both renderer panels within the usable window,
using IME insets on Android 30+ and the visible display frame on older Android.
Flutter receives translated keyboard insets because its panel already sits above
the keyboard. Closing the keyboard restores the normal 60% SDL / 40% Flutter
split. The emulator explicitly enables its software keyboard even with host keyboard
attachment. The Android 35 suite requires the IME input view to be shown,
checks its native surface height, and requires a visible focused field and an
unobscured Flutter panel and a fresh Python text-change marker; `keyboard-viewport.json`
retains the native layout and input bounds.

These packaging changes reduce the native libraries transferred to x86_64 CI.
They do not establish runtime FPS, physical ARM execution or release readiness.
See [validation.md](validation.md) for verified artifacts and measurements.
