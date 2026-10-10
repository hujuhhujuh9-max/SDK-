# Make an application project

Create a project beside the SDK checkout:

```sh
python3 create_project.py ../my-app \
  --application-id com.example.notes \
  --display-name "Notes and Stories"
```

The destination must be new. The generator validates the complete project before
publishing its directory atomically on Linux, and refuses existing files,
directories and symlinks. It copies the working native `game/`, local `assets/`
and the small app template. It omits caches, compiled sources and build outputs;
it does not copy the SDK engine, runtime, extensions or toolchains. Use
`--source-root /path/to/SDK-` to take the sample from another SDK checkout.
`--package` and `--name` are aliases for `--application-id` and `--display-name`.

The resulting project contains:

```text
my-app/
  renfletpy.json
  app/my_app.py
  game/script.rpy
  game/app_starter.rpy
  game/tactics_display.py
  assets/runner.svg
  assets/runner-animation.json
  assets/webview.html
```

Edit `app/my_app.py` to replace the visible **My RenFletPy App** heading and
compose your Flet home. The template uses its copied `runner.svg` and wraps the
working built-in home, preserving application records, reusable controls and
Start/Resume/Return story actions. Edit the copied native story and add assets in
your project. Keep its integration screens, initialization and command polling
when replacing the story, as explained in [Ren'Py authoring](renfletpy.md).

## Configuration

`renfletpy.json` contains plain build inputs:

```json
{
  "application_id": "com.example.notes",
  "display_name": "Notes and Stories",
  "version_code": 1,
  "version_name": "0.1.0",
  "startup_template": "app",
  "game_dir": "game",
  "python_dir": "app",
  "assets_dir": "assets",
  "app_home": "my_app:app_home_view",
  "icon": null
}
```

| Field | Accepted values |
| --- | --- |
| `application_id` | At least two dot-separated ASCII segments, each beginning with a letter and containing letters, digits or underscores; at most 150 characters. Use your own package ID for distribution. |
| `display_name` | 1–80 printable UTF-8 characters, without surrounding whitespace. Sets the Android and native application name. |
| `version_code` | Integer from 1 to 2100000000; increase it for an update. |
| `version_name` | 1–50 ASCII letters, digits, `.`, `_`, `+` or `-`, beginning with a letter or digit. |
| `startup_template` | `app` or `story`. The generator selects `app`; SDK builds without a project retain the default story. |
| `game_dir`, `python_dir`, `assets_dir` | Existing, separate source directories relative to this JSON file. Native sources must include a `.rpy` file. |
| `app_home` | Optional `null` for the built-in home, or a top-level `module:function` such as `my_app:app_home_view`; the module must exist directly in `python_dir`. |
| `icon` | Optional `null` for the runner icon, or a relative path to an existing PNG with dimensions up to 8192 pixels per side. |

Unknown or duplicate fields are rejected. Source paths cannot be absolute, leave
the project directory, overlap, traverse symlinks or contain special files.
Source trees cannot contain saves, caches, dependency environments, compiled
Python/Ren'Py files, native libraries or packaged Android build output. Remove
those files or keep them outside the configured source trees.

Application Python is copied recursively, including package data. Top-level names
must not shadow SDK runtime modules, the fixed extension and service packages,
Python's standard library or the bootstrap's reserved files/directories. Import
the SDK's `app_home` module instead of copying it. Keep your own modules under
names such as `my_app`, `notes` or an application-specific package.
Game and application Python cannot supply the same top-level module/package name.
`game/_renfletpy_project.rpy` is reserved for generated identity settings;
`assets/_renfletpy_project_icon.png` is reserved when an icon is supplied.

External projects use their package ID as the Android link scheme, lowercased
with dots and underscores replaced by hyphens. For `com.example.notes`, use
`com-example-notes:///records` or `com-example-notes:///app/recipes` for the
existing pages. Internal Flet navigation keeps paths such as `/app/records`.
The SDK's built-in examples retain their `sdk-runner` scheme.

The app-home factory is synchronous:

```python
def app_home_view(page, navigate, status, request_story, *,
                  route="/app", large_text=False):
    # Build and return a flet.View; the runner mounts and navigates it.
    ...
```

The runner imports its configured factory once per Flet page session on Flet's
event loop and validates its returned `View`. Return the supplied `route` exactly;
the caller owns navigation and mounting. It owns native command
acknowledgement and service lifetimes. A factory must not execute native story
operations directly. `status` is a plain snapshot; `request_story` submits the
existing revision-guarded command. The generated runtime configuration contains
only `STARTUP_TEMPLATE` and `APP_HOME`, with no mutable save state. Application
records remain independent of native story saves.

## Build and release

Install the prerequisites in the [build environment guide](build-environment.md)
and create the Python 3.12 virtual environment using [the README commands](../README.md#build).
Run builds from the SDK checkout with its prepared interpreter and pass the
project's config file:

```sh
.android-build/venv/bin/python build_android.py --project ../my-app/renfletpy.json
.android-build/venv/bin/python build_android.py \
  --project ../my-app/renfletpy.json --build-type release
```

For `com.example.notes`, outputs are
`runner-com-example-notes-debug.apk` and
`runner-com-example-notes-debug-x86_64.apk`, or the corresponding `release`
filenames. Release uses the release Flutter AAR and separate verified cache;
debug retains its existing cache. Project inputs and metadata are hashed in the
APK's capability inventory separately from the SDK source revision. Staging is
recreated on each build so deleted or renamed project sources do not survive.

Supply all four signing environment variables to sign a release:

```text
RENFLETPY_KEYSTORE
RENFLETPY_KEY_ALIAS
RENFLETPY_STORE_PASSWORD
RENFLETPY_KEY_PASSWORD
```

The keystore stays outside the project/SDK source trees. Passwords are read from
the environment and are not passed as command arguments or committed. Without
signing values, release output is explicitly unsigned. Signed APKs must pass
`apksigner` verification. This workflow does not create production signing keys
or publish applications; Play Store AAB/asset delivery remains a follow-up.

If you need a signing key, create one once with the JDK's interactive prompts.
Replace `/absolute/path/notes.jks` with a path outside the source trees:

```sh
keytool -genkeypair -storetype JKS -keystore /absolute/path/notes.jks \
  -alias notes -keyalg RSA -keysize 2048 -validity 10000
export RENFLETPY_KEYSTORE=/absolute/path/notes.jks
export RENFLETPY_KEY_ALIAS=notes
read -rsp 'Keystore password: ' RENFLETPY_STORE_PASSWORD
printf '\n'
read -rsp 'Key password: ' RENFLETPY_KEY_PASSWORD
printf '\n'
export RENFLETPY_STORE_PASSWORD RENFLETPY_KEY_PASSWORD
.android-build/venv/bin/python build_android.py \
  --project ../my-app/renfletpy.json --build-type release
unset RENFLETPY_STORE_PASSWORD RENFLETPY_KEY_PASSWORD
```

The password prompts above use Bash. Enter the passwords selected by `keytool`;
use the store password again if the key uses the same password. Keep this key
for subsequent updates to the same package and increase `version_code`.

## First physical-device check

The first test target is **Android 15 / API 35**. Use the signed **universal**
release APK on an ARM phone; the `-x86_64` APK is for the emulator.

For the first test, [download the prebuilt example ZIP](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37943783718/artifacts/11623437433),
extract `runner-org-renfletpy-example-release.apk`, install it and open
**RenFletPy Example**. This avoids building or creating a signing key for the
initial phone check. This APK uses a disposable CI key; use your own stable key
above for your applications and subsequent updates.

The [API 35 phone check](api35-phone.md) automates this first pass with an
explicit ADB serial and verifies the APK signature, hash and installed bytes.
It exercises native Start/Return and creates a Record through the actual UI,
then force-stops and reopens the app to verify that Record in a new process.
Use that guide for the prebuilt example and retained screenshots/logs. The
existing project probe targets an API 36 x86_64 emulator.

For your own `com.example.notes` build, the commands below install the signed
APK and record the test profile.
Enable USB debugging and authorize the connected computer.
Replace `PHONE_SERIAL` with the serial shown by `adb devices -l`:

```sh
export PATH="$ANDROID_HOME/platform-tools:$PATH"
"$ANDROID_HOME/build-tools/36.0.0/apksigner" verify --verbose \
  .android-build/outputs/runner-com-example-notes-release.apk
sha256sum .android-build/outputs/runner-com-example-notes-release.apk
git rev-parse HEAD
adb devices -l
adb -s PHONE_SERIAL install -r .android-build/outputs/runner-com-example-notes-release.apk
adb -s PHONE_SERIAL shell am start -W -n com.example.notes/org.sdk.runner.RunnerActivity
adb -s PHONE_SERIAL shell getprop ro.product.model
adb -s PHONE_SERIAL shell getprop ro.build.version.release
adb -s PHONE_SERIAL shell getprop ro.build.version.sdk
adb -s PHONE_SERIAL shell getprop ro.product.cpu.abi
```

Confirm `ro.build.version.sdk` is `35`. Start with one simple pass: check the
custom home, icon and asset; start the story, open Menu and return to the app;
save one Record, fully close and reopen the app and confirm it is retained.
Record the model, Android version, ABI, SDK source and APK SHA-256 with those
outcomes.

After that passes, check media, control recipes and background/resume, then
install a newer version signed with the same key and confirm data survives the
update. The automated probe uses Android 36; Android 15 phone compatibility
needs this separate device evidence.

Camera, location/GPS and audio recording permissions are removed from the merged
manifest. The 19 paired extension packages, SDK notices and selected ABIs stay
packaged. Release ads initialization is disabled until owner-specific metadata
and initialization are deliberately added; debug diagnostics retain their
existing behavior. See [validation](validation.md) for the actual device profile
and acceptance evidence. Emulator results cover the exercised x86_64 Android
profile; ARM and physical-device performance require their own testing.
