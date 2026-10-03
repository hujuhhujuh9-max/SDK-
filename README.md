# SDK-: fixed Android runtime integration

This project builds one Android application on a Linux development workspace.
The app contains a fixed modified Flet/Flutter/Ren'Py stack. Its components
are assembled during the build and kept on separate Git branches.

`main` owns shared Android integration and extra build/runtime requirements.
Component changes and removals stay on their component branches. See
[CONTRIBUTING.md](CONTRIBUTING.md) for ownership rules.

| Component | Version | Owner branch |
| --- | --- | --- |
| Flutter SDK | 3.44.8 | `sdk/flutter-3.44.8` |
| Ren'Py SDK | 8.5.3 | `sdk/renpy-8.5.3` |
| Ren'Py Android packaging tools | 8.5.3 | `sdk/renpy-rapt-8.5.3` |
| Flet source | 1.0.3 | `sdk/flet-1.0.3` |

## Prepare build inputs

Python 3.12+, Git, and Git LFS are required. `sdk-lock.json` pins each component
commit, archive path, byte count, and checksum. The preparer downloads only
those archive objects and extracts them into an ignored local cache. It
attaches RAPT to the matching extracted Ren'Py SDK without altering any branch.

```sh
python3 prepare.py setup
python3 prepare.py status
```

For an existing download directory containing the original filenames:

```sh
python3 prepare.py --archives /path/to/archives setup
```

The Linux-to-Android toolchain requirements are recorded in
[docs/build-environment.md](docs/build-environment.md).

## Integration state

Build input preparation is implemented and tested. Ren'Py/SDL owns Android
startup and Python; Flutter/Flet is embedded into that host. The approved
design is recorded in [docs/runner-overlap.md](docs/runner-overlap.md).
The shared host builds an Android debug APK with the full Flet extension mix.
Android 35 emulator checks verify both renderers, shared Python state, native
services, local assets, input, navigation, rotation, background/resume, cold
and warm links, predictive Back, clean shutdown and force-stop/cold relaunch.
Checks verify durable data across processes and exact native file selections.
The capability page reuses nine services and one audio player across visits;
the native suite runs again after view reentry and both restart paths.
Build records, APK downloads, and the current validation scope are in [docs/validation.md](docs/validation.md).
The full client's Flet extensions and local assets are included in the fixed
build; [capability coverage](docs/flet-flutter-capabilities.md) explains their
integration and validation limits.

```sh
python3 -m unittest discover -s tests -v
```

With JDK 21 and Android SDK 36 installed:

```sh
python3 -m venv .android-build/venv
.android-build/venv/bin/python -m pip install -r requirements-build.txt -r runtime/requirements.txt
.android-build/venv/bin/python build_android.py
```

The build copies the pinned component inputs into an ignored assembly folder,
applies the checked Flet and RAPT branch patches, and produces
`.android-build/outputs/runner-debug.apk`. It contains a fixed integration
sample with a shared counter and a **Capabilities** page for checking services
and local assets. The
`Build RenPy-owned Android runner` workflow publishes the APK. The separate
`Check Android runner` workflow downloads that build and tests it on an emulator,
recording the APK and harness source commits with its results. Harness changes
can test the latest successful APK when its build inputs still match. The workflow
compares source commits before device execution and defers incompatible APKs.

The `Check runtime integration` workflow separately runs prepared-Flet lifetime
regressions, 500 real protocol events across five backend start/stop cycles,
and a 20-visit service registry check with stable service identities.
The APK build runs Flutter analysis and lifecycle tests before native assembly.
[Runtime measurements](docs/performance.md) record the scope of the timing probes
and the work removed from idle polls and disposed controls.

## Rights

Original work authored for `main` is **all rights reserved**; no permission
is granted by the project notice. Third-party components and derived material
retain their respective licenses. See [LICENSE](LICENSE).
