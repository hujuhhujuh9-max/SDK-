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

JDK 21 is required by the
[Ren'Py Android documentation](https://www.renpy.org/doc/html/android.html).
The Android SDK and Gradle values above come from the pinned RAPT archive:
`buildlib/rapt/install_sdk.py`, `prototype/build.gradle`, and
`prototype/renpyandroid/build.gradle`. The bundled prototype currently lists
minimum Android API 21; the final app's minimum depends on the integrated
Flutter/Flet requirements and has not been selected.

Set `JAVA_HOME` to an installed JDK 21 and `ANDROID_HOME` to the Android SDK.
With Android command-line tools installed, the required baseline packages are:

```sh
sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-36"
```

The shared Android build will use a Gradle wrapper. Its final build-tools/NDK
versions and native dependency set depend on the agreed host design. They
must be recorded on `main` when chosen. This preparation stage does not
accept SDK licenses, generate signing keys, or claim a working Android build.
