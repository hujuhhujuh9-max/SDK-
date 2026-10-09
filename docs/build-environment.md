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
counts, plus the Git source revision and explicit `story` startup template.
The build publishes `runner-apk` and `runner-emulator-apk`; each includes
the report. Device CI prefers the emulator artifact and checks source
compatibility before using it. Older compatible universal artifacts remain
supported.

### Optional app starter

The default command still opens **Before the First Light**. Select the optional
app-first home explicitly when packaging:

```sh
.android-build/venv/bin/python build_android.py --startup-template story
.android-build/venv/bin/python build_android.py --startup-template app
```

These commands use the same pinned SDKs, Flutter module and verified AAR cache.
The second invocation rebuilds the Python/game payload and Android packages;
it reuses Flutter compilation only when the existing input and output checks
pass. To verify a fresh AAR as well, add `--force-flutter-build` to the first
command. Each mode retains the complete catalog, assets, ABIs and notices.

CI selects Flutter AAR candidates using source identity and the installed Java
and Android toolchain. The builder still validates complete input identity and
every cached Maven file before reuse. CI compares verified receipts before and
after the build: an unchanged valid candidate creates no extra cache entry;
a rejected or changed candidate is published under a fresh run/attempt key.
Prefix restore finds that replacement on later runs, since GitHub cache keys
cannot be overwritten. Failed or incomplete output cannot be published.
The combined validation also restores a newly published entry and requires
identical verified contents after its unchanged and Python-only warm checks.

| Startup template | Universal APK | Emulator APK | Build receipt |
| --- | --- | --- | --- |
| `story` | `runner-debug.apk` | `runner-debug-x86_64.apk` | `apk-builds.json` |
| `app` | `runner-app-debug.apk` | `runner-app-debug-x86_64.apk` | `apk-builds-app.json` |

All files are under `.android-build/outputs/`. App-mode CI artifacts are
`runner-app-apk` and `runner-app-emulator-apk`. The existing default artifact
names stay unchanged. Both variants use the same Android package identity;
install the selected variant before its scenario. Native story checkpoints
and background recovery use the selected template's save namespace.

The checked-in `runtime/project_config.py` selects `story`. Assembly writes its
selected copy into both the native compilation project and Android Python
bundle. It never rewrites the checked-in module or relies on an Android
environment variable. Native compilation uses separate `renpy-project` and
`renpy-project-app` directories so desktop game-local save locations do not
overlap across modes.

The APK inventory records `startup_template`, `source_sha` and the packaged
configuration's SHA-256. Inspection verifies the configuration bytes and their
literal selection before installation. Matching Git revisions alone cannot
prove matching startup modes. Earlier APKs without this mode identity need a
fresh build for the new checks.

The combined **Verify integrated app recipes** workflow automatically validates
both modes when build inputs, runtime code, tests, verification scripts or
workflows change on `main`. Documentation-only changes do not trigger this
batch. One build produces both modes from the same revision and runs their
native checks; Android acceptance runs story first, then app, and requires
actual source-compatible receipts for both. The combined runtime gate replaces
the standalone runtime push, and this batch owns the automatic main build and
device checks.

Each Android CI job owns its hosted runner and emulator. Story and app jobs
within one combined batch stay serial; their concurrency group uses the batch
run ID so a different batch cannot replace a pending device job.

The workflow also supports `integration/app-starter` and the existing
`integration/abc-app-recipes` branch. Manual combined runs select both modes by
default; `build_app_starter: false` selects story only outside the app-starter
branch. A manual **Build RenPy-owned Android runner** run can set
`build_app_starter` to publish both variants; its default remains the story build.

For a manual device run, pass the same build run ID and `startup_template`
to **Check Android runner**. Leaving the run ID blank selects the latest
successful main build from either the combined or standalone build workflow.
Set `require_receipts` for an acceptance run:
source incompatibility fails, and the app gate requires successful nonempty
`app-starter.json` evidence plus APK-mode inspection and emulator profile.
Default acceptance still requires records and storage persistence receipts.
The runtime workflow also requires the full prepared-Flet suite without skips.

Device CI runs an Android 36 x86_64 emulator at 1080p with two guest CPU cores,
2 GiB configured memory and SwiftShader software graphics with guest Vulkan disabled.
It uses the Google APIs API 36 image and SDK-managed emulator. The emulator
version is recorded in each run; the current build is 37.2.12 (16428233).

| Profile | Pixels | Density | Logical display (dp) |
| --- | --- | --- | --- |
| 1080p | 1080 × 1920 | 420 dpi | 411.429 × 731.429 |

1080p is the single workflow profile for the full capability and story suite.
The Ren'Py sample uses a 720×1280 virtual UI scaled to the physical 1080p display;
virtual coordinates are independent of framebuffer resolution. AVD LCD, density and
skin settings are explicit; actual device settings must match before installation.
Both phone cameras and host microphone input are disabled. CI uses the emulator's
headless binary and its QEMU WAV output driver, which writes samples from the
virtual sound card without a host sound server. PulseAudio's implementation in
the headless binary is stubbed; it cannot supply that output path.
The workflow uploads `runner-device-check-1080p`.
`emulator-profile.json` records configured values;
`device-environment.json` records actual API, ABI, display, density and host CPU count.

Configure the output capture before starting a local emulator:

```sh
mkdir -p .android-build
export QEMU_AUDIO_DRV=wav QEMU_AUDIO_DAC_FIXED_FREQ=48000 QEMU_WAV_FREQUENCY=48000
export QEMU_WAV_PATH="$PWD/.android-build/emulator-output.wav"
export RUNNER_AUDIO_WAVE="$QEMU_WAV_PATH"
```

Run the emulator with audio enabled, `-no-window -gpu swiftshader`,
`-feature VirtioSndCard,-Vulkan`, `-camera-back none -camera-front none`, and the
1080p/420 dpi AVD settings above. Set `hw.audioOutput=yes` and
`hw.audioInput=no` in its AVD config. Omit `-no-audio` for playback validation.
With the emulator already running:

```sh
python3 scripts/device_smoke.py .android-build/outputs/runner-debug-x86_64.apk --abi x86_64 --expected-display 1080 1920 420
```

Use `--startup-template app` and `runner-app-debug-x86_64.apk` for the app
scenario. Its driver writes `.android-build/device-check/app-starter.json`
only after the selected scenario succeeds; default media/story regression
and app validation are separate serialized scenarios.

CI copies the SDK's system image and changes the tinyalsa period multiplier
from 2 to 8 in its dynamic vendor partition before boot. This increases the PCM
buffer during software rendering; the image copy and original hashes are
recorded in `emulator-profile.json`.
The workflow links the other image files into a prepared directory, passes it
with `-sysdir`, and sets
`RUNNER_AUDIO_PERIOD_MULTIPLIER=8` to require the actual boot value. The driver
uses `adb root` only to read this protected property, then restores ordinary
shell privileges before installing the game. A local run can use the workflow's
image-copy preparation; omit that variable when using an unchanged SDK image.
The read-only property cannot be changed with runtime `setprop`, and emulator
`-prop` accepts only `qemu.*` properties.

The expected-display option verifies the 1080p configuration before installation.
Without that option, the standalone driver records the actual display settings.
The WAV driver writes 48 kHz stereo PCM. Each capture starts at its current end,
reads at least 1.2 seconds of fresh samples, and averages the two channels without
resampling. Raw mono PCM and 440 Hz/RMS results are retained; each result includes
its sample rate. QEMU finalizes WAV length fields only at shutdown, so the live
capture verifies the PCM header and reads the newly written data directly.
Silence, unrelated sounds, short captures and playback errors fail validation.
The standalone checker also supports a real PulseAudio output monitor when
`RUNNER_AUDIO_WAVE` is unset, with `pulseaudio-utils` installed and
`RUNNER_AUDIO_MONITOR` selecting the monitor; that capture is 16 kHz mono.

To validate a branch APK without merging it, dispatch **Build RenPy-owned
Android runner** on that branch. After it succeeds, dispatch **Check Android
runner** on the same branch with its run ID in `build_run`. Source comparison
still rejects an APK with different application build inputs.

Without `--abi`, the driver requires the universal three-ABI APK. The supplied
ABI must match the APK contents; missing capability metadata fails before
device execution.

ADB commands have deadlines: 60 seconds ordinarily, 15 for PID lookup and
diagnostic reads, 30 for raw framebuffer capture, and 180 for the initial
device wait. Fresh logs are saved after initial capability checks, clean
relaunch, frame profiling and view reentry. Final collection attempts device,
window, activity, input-method, Android audio service, audio mixer, logcat and
screenshot diagnostics independently.
`diagnostics.json` lists unavailable snapshots. An earlier log is retained if
a later read fails. Cleanup cannot replace the primary test error, and missing
diagnostics after an otherwise successful suite still fail verification.

Every native suite invocation also scrolls to the local SVG and bar chart,
requires full fixture heights before checking expected RGB pixels inside their
semantic bounds, and saves
screenshots and `local-visuals.json`. Fresh `core-service-reuse.json` receipts
require the same seven core service IDs on repeated checks in one process.
The complete prepared-Flet page/service set contains 14 instances.

The fullscreen SDL host cannot rely on Android's ordinary window resize when
the keyboard opens. It lays out both renderer panels within the usable window,
using IME insets on Android 30+ and the visible display frame on older Android.
Flutter receives translated keyboard insets because its panel already sits above
the keyboard. Closing the keyboard restores the normal 60% SDL / 40% Flutter
split. The emulator explicitly enables its software keyboard even with host keyboard
attachment. The Android suite requires the IME input view to be shown,
checks its native surface height, and requires a visible focused field and an
unobscured Flutter panel and a fresh Python text-change marker; `keyboard-viewport.json`
retains the native layout and input bounds.

These packaging changes reduce the native libraries transferred to x86_64 CI.
They do not establish runtime FPS or physical ARM execution.
See [validation.md](validation.md) for verified artifacts and measurements.

## External projects and release builds

Use [the project template](project-template.md) to create a project with its own
package name, version, app code, story, assets and optional PNG icon. The same
Linux prerequisites apply. `--build-type release` compiles `flutter_release`
and assembles release APKs; it does not relabel a debug artifact.

Release Flutter output has a separate `.android-build/flutter-aar-release`
cache. Its complete receipt must contain release AAR/POM files; a debug
repository cannot satisfy it. The existing debug cache and CLI remain available.
Both modes retain the full extension catalog, Python resources, notices and
selected native ABIs.

The combined workflow generates a project, signs its release APKs with a
disposable CI key and checks them after the existing story/app device suites.
The key is deleted before artifacts upload. This verifies the signing path;
it does not supply a production signing identity. Owner signing credentials
are passed through environment values, never Gradle command arguments or
tracked files. Both mode caches use before/after verified receipts and exact
restoration checks. Unchanged valid caches avoid duplicate publications.

Camera, location/GPS and microphone recording permissions and the location
service are removed from merged APK manifests while their plugin code remains.
Release examples disable eager advertising initialization; they have no ads.
Signed release packaging and emulator acceptance precede physical ARM and
older-Android compatibility testing. Store AAB packaging/asset delivery is a
separate step for projects targeting Google Play.

The pinned Ren'Py 8.5.3 component removes player rollback in its source.
Its archive already includes the component's published source diff; assembly
must not apply that diff again. Save/load and recovery keep the active load
point, including mutable objects and random state. The archive hash selects
a fresh SDK cache directory, keeping the original installation separate.
