# First Android 15 phone pass

This pass checks one physical **Android 15 / API 35 ARM phone**: install, launch,
native story Start/Return, and a saved Record after fully closing and reopening.
Use the already validated signed example APK; no SDK build or signing key is
needed. Media, updates, background/resume and performance follow this basic pass.

## APK and tools

Download [project-release-apks.zip from run 37943783718](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37943783718/artifacts/11623437433)
and extract `runner-org-renfletpy-example-release.apk`. This is the universal
package, with ARM libraries, application ID `org.renfletpy.example`, label
**RenFletPy Example**, and version `0.1.0` / code `1`.

| Identity | Expected value |
| --- | --- |
| Build source | `49f50a39a7ba62b7c238ce4607f1e56314b61ce7` |
| APK bytes | `244158034` |
| APK SHA-256 | `f95ba38abb3e7b2c53218c8dae9e667977a5eae5e5e36df9248e6d49cc3fb186` |
| ZIP SHA-256 | `91e1fb421e9f0cfb8f58e7fedef22d3ae773e23ae2a1509fe91bcdafa3f9ccae` |
| Signing certificate SHA-256 | `733981ba2bdacfb7b782ac7043f27cef1e7aefb43b48a9543c203a45846876f1` |

The disposable CI signing key is sufficient for this example test. Applications
you distribute need your own stable signing identity, as described in the
[project guide](project-template.md#build-and-release).

The test computer needs Python 3.12+, Java, Android platform-tools (`adb`) and
build-tools 36.0.0 (`aapt`, `apksigner`). Use the
[existing Linux setup](build-environment.md); Flutter, Ren'Py and prepared Flet
are not required to run this prebuilt-APK check. `ANDROID_HOME` points to the
installed Android SDK.

## Run

Enable USB debugging, connect the phone, authorize the computer and keep the
screen unlocked in portrait orientation. From the SDK checkout:

```sh
export PATH="$ANDROID_HOME/platform-tools:$PATH"
adb devices -l
```

Choose the phone's serial from the entry with state `device`. Replace
`PHONE_SERIAL` and `/path/to/runner-org-renfletpy-example-release.apk` below:

```sh
python3 scripts/check_phone.py /path/to/runner-org-renfletpy-example-release.apk \
  --serial PHONE_SERIAL \
  --sha256 f95ba38abb3e7b2c53218c8dae9e667977a5eae5e5e36df9248e6d49cc3fb186 \
  --source-sha 49f50a39a7ba62b7c238ce4607f1e56314b61ce7 \
  --aapt "$ANDROID_HOME/build-tools/36.0.0/aapt" \
  --apksigner "$ANDROID_HOME/build-tools/36.0.0/apksigner"
```

Leave the phone available while the command operates it. All ADB commands select
that serial, so another connected device is not used. `--adb /path/to/adb` can
select the tool explicitly.

The check verifies the signed APK, project identity, disabled camera/location/
recording permissions, and installed APK bytes before exercising the app. It
requires API 35, an ARM ABI and a physical-device profile before installation.
It then:

1. Installs the APK and launches **RenFletPy Example**, requiring native Ren'Py,
   Flutter and Flet readiness in the same app process.
2. Starts the native story, checks painted dialogue, opens Menu and returns to
   the visible app home in that process.
3. Adds a uniquely named `API35Record...` through Application records and checks
   the saved row.
4. Force-stops the example, launches a fresh process and checks the same Record
   through Application records again.

The test retains the Record and existing application data. A repeat run confirms
**Start new story** if the example already has story progress. It does not clear
application storage or uninstall the app. An installation/signing failure stops
the check and retains diagnostics; resolve the reported cause before retrying.

## Evidence and completion

Each run creates a new ignored `.android-build/phone-api35-<UTC timestamp>/`
directory. `--output /new/path` selects another new directory; existing output
directories are refused so earlier receipts cannot be mistaken for this run.

`api35-phone.json` records success or the failed stage, source/APK/project hashes,
signing certificate, installed package, model, Android version, ABI, display and
original/reopened process IDs. Screenshots, fresh UI snapshots, APK inspection
and app-process logs accompany the completed steps. A successful receipt requires
all four checks; fixture tests and emulator runs do not establish phone success.

Review these files and record the actual outcome in [validation](validation.md).
If a step fails, keep its evidence and fix or explain that failure before broader
testing. The existing API 36 emulator gate remains a separate validation scope.
