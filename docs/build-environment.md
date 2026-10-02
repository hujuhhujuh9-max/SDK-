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
sdkmanager --sdk_root="$ANDROID_HOME" "platform-tools" "platforms;android-36"
```

`build_android.py` uses the RAPT Gradle wrapper, keeps native Ren'Py startup,
builds Flutter as a debug AAR, and links both into the main-owned host. Its
debug APK uses Gradle's debug signing; release signing is not configured.
The build preserves third-party notices and uses MsgPack's Python fallback
instead of copying a Linux extension into Android.
