# SDK-: RenFletPy Android runtime

One Android application with a fixed modified Flet/Flutter/Ren'Py stack, built
on Linux. Ren'Py/SDL owns startup, the story loop and Python; Flutter/Flet is
embedded in that host for interludes, shared menus and device diagnostics.

| Component | Version | Owner branch |
| --- | --- | --- |
| Flutter SDK | 3.44.8 | `sdk/flutter-3.44.8` |
| Ren'Py SDK | 8.5.3 | `sdk/renpy-8.5.3` |
| Ren'Py Android packaging tools | 8.5.3 | `sdk/renpy-rapt-8.5.3` |
| Flet source | 1.0.3 | `sdk/flet-1.0.3` |

`main` owns the Android host, shared integration, dependencies, tests and docs.
Each component branch owns its archives and patches. Build assembly consumes
pinned inputs without merging those branches; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Prepare build inputs

Python 3.12+, Git and Git LFS are required. `sdk-lock.json` pins component commits,
archive paths, sizes and SHA-256 checksums. Preparation downloads and verifies
those archives into the ignored `.android-build/` cache.

```sh
python3 prepare.py setup
python3 prepare.py status
```

To use an existing directory of archives with their original filenames:

```sh
python3 prepare.py --archives /path/to/archives setup
```

## Build

Use Python **3.12** to match Ren'Py's packaged interpreter, JDK 21, Android SDK 36,
NDK 28.2.13676358 and FFmpeg. Set `JAVA_HOME` and `ANDROID_HOME` as described in
[the build environment guide](docs/build-environment.md).

```sh
python3 -m venv .android-build/venv
.android-build/venv/bin/python -m pip install -r requirements-build.txt -r runtime/requirements.txt
.android-build/venv/bin/python build_android.py
```

Startup is selected explicitly with `--startup-mode story` or `--startup-mode app`.
Omitting the option keeps the current story-first opening. App mode opens the
existing **Application records** recipe; an incoming deep link takes precedence
over either default. Ren'Py/SDL still starts the app and owns its interpreter.

```sh
.android-build/venv/bin/python build_android.py --startup-mode app
```

The build applies the pinned component patches in an ignored assembly folder,
runs Flutter analysis and lifecycle tests, and produces:

- `.android-build/outputs/runner-debug.apk`: arm64-v8a, armeabi-v7a and x86_64.
- `.android-build/outputs/runner-debug-x86_64.apk`: the emulator package.
- `.android-build/outputs/apk-builds.json`: source revision, selected startup mode,
  sizes, checksums and inventory results.

Both APKs retain all 19 Flet extensions, resources, assets and third-party
notices. Their shared payload hashes must match. The Android build workflow
publishes both packages; [validation](docs/validation.md) links the recorded builds
and device results.

An unchanged Flutter AAR is reused only after its input identity and complete
output inventory pass verification. Python/story changes still rebuild the APK.
Use `build_android.py --force-flutter-build` for a fresh AAR compilation.
Selecting another startup mode rebuilds the Android packages while preserving
verified Flutter output reuse. Both packages contain `runner-startup.json`, whose
mode and SHA-256 must match the APK inventory and build receipt.

## Story sample

**Before the First Light** uses native Ren'Py scenes and dialogue, a Flet star-map
minigame and a journal choice. **Plan a balcony route** opens the optional native
isometric board with terrain opacity, three camera modes, pan, zoom and rotation.
Flutter appears when an interlude or shared menu needs it.
Phone-camera access is disabled. Diagnostics include audible audio, moving
video and Lottie animation fixtures with play/pause controls; device checks
verify actual output and background/resume at 1080p.

**Menu** provides quick save/load, chronological story history, reading settings,
replay, diagnostics and quit. Saves retain active puzzles, board positions and
camera settings; Android background recovery captures current progress. Reading
preferences survive restart and stay current when loading an older story save.
Player rollback is removed from the modified Ren'Py SDK; load a save to return to earlier
progress. Story history remains available for reading.

**Device diagnostics → Application records** opens an optional reusable form/list
screen for persistent application data. The `sdk-runner:///records` link opens the
same screen. Records survive restart, story loading and replay; drafts are kept
when native writes need reconciliation. See [the form/list guide](docs/form-list.md).

Copyable native dialogue, choice, text input and ATL animation examples are in
[examples/renpy](examples/renpy/README.md). They are opt-in and keep the current
story entry point.

Use normal Ren'Py `Character` dialogue and scene statements. Call
`renfletpy_minigame("star_map")`, `renfletpy_minigame("tactics")` or
`renfletpy_panel(...)` for an interlude, then branch on `_return`. The
[authoring guide](docs/renfletpy.md) covers thread ownership and saves;
[tactics](docs/tactics.md) covers the board API and controls.

## Checks

Host-independent regression checks need only Python:

```sh
python3 -m unittest discover -s tests -v
```

The host-only run skips Flet-dependent cases. `check_runtime.py` prepares the
patched Flet source and runs those cases alongside real protocol checks. With
the build virtual environment installed:

```sh
.android-build/venv/bin/python scripts/check_runtime.py
.android-build/venv/bin/python scripts/check_service_lifetime.py .android-build/runtime-inspection/flet
.android-build/venv/bin/python scripts/check_host.py --flet-root .android-build/runtime-inspection/flet
```

`check_host.py` requires the complete prepared-Flet suite to pass without skips.
The story/app acceptance workflow builds and checks both startup modes; source,
ABI, checksum, mode or receipt mismatches fail before device installation.
See [startup and acceptance](docs/startup-acceptance.md).

Native rendering, save/load and recovery checks need the Ren'Py SDK and Xvfb:

```sh
python3 prepare.py setup renpy
python3 scripts/check_native_story.py
```

Android device setup and the full 1080p smoke-check command are in
[the build environment guide](docs/build-environment.md#apk-outputs-and-emulator-setup).

## Documentation

| Guide | Contents |
| --- | --- |
| [Authoring](docs/renfletpy.md) | Story APIs, shared menus, thread ownership and saves |
| [Application records](docs/form-list.md) | Reusable fields, persistent records and write recovery |
| [Native examples](examples/renpy/README.md) | Copyable dialogue, choices, input and ATL animation |
| [Tactics](docs/tactics.md) | Native board controls, saved state and limitations |
| [Runner ownership](docs/runner-overlap.md) | Approved Ren'Py/SDL and Flutter integration |
| [Capability coverage](docs/flet-flutter-capabilities.md) | Extension catalog and native-service checks |
| [Validation](docs/validation.md) | Latest recorded build, evidence and scope |
| [Performance](docs/performance.md) | Protocol, service, APK and frame measurements |
| [Validation history](docs/validation-history.md) | Earlier revisions and their recorded results |

## Rights

Original work authored for `main` is **all rights reserved**; no permission is
granted by the project notice. Third-party components and derived material
retain their respective licenses. See [LICENSE](LICENSE).
