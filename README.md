# SDK-: RenFletPy Android runtime

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

## Story experience

The default **Before the First Light** sample uses Ren'Py for its main event
loop, scenes and normal dialogue. It opens a Flet star-map minigame between
scenes, then returns its result to the script. A Flet journal choice leads into
the last scene and an ending with explicit replay or close actions. Flutter is hidden during normal
story interactions; interludes and the shared menu appear only when needed.
Puzzle progress survives menu navigation and background/resume. **Menu → Quick
save** stores the Ren'Py scene, active puzzle progress and story history;
**Quick load** restores them, including after closing the app.
Android background recovery also captures the latest Flet moves and resumes
them after process loss. **Story history** shows native dialogue and interlude
results together in order.
**Menu → Reading settings** changes text size across the native story, Flet
panels and history, and offers instant or animated dialogue. Those preferences
survive restart and remain current when loading an older story save. Shared
menus hold completed interlude results until you return to the story.

Use ordinary Ren'Py `Character` dialogue and scene statements. Call
`renfletpy_minigame("star_map")` or `renfletpy_panel(...)` for a temporary Flet
interaction and branch on `_return`. The bridge rejects delayed and repeated
completions and applies Ren'Py actions on the story thread. See
[the authoring guide](docs/renfletpy.md) for examples and save/rollback limits.
The journal's **Plan a balcony route** opens an optional native isometric board
adapted from the owner's `2d-test` project. It shares the same menu, saves and
history; [native tactics](docs/tactics.md) describes the callable activity.

The counter and **Capabilities** page remain available under **Menu → Device
diagnostics**, with the existing native-service and lifecycle checks.

## Integration state

Build input preparation is implemented and tested. Ren'Py/SDL owns Android
startup and Python; Flutter/Flet is embedded into that host. The approved
design is recorded in [docs/runner-overlap.md](docs/runner-overlap.md).
The shared host builds an Android debug APK with the full Flet extension mix.
Android 35 emulator checks verify both renderers, shared Python state, native
services, local assets, input, navigation, rotation, background/resume, cold
and warm links, predictive Back, clean shutdown and force-stop/cold relaunch.
Checks verify durable data across processes and exact native file selections.
In diagnostics, the host keeps both renderer panels above the software keyboard,
restores their normal split when it closes, and verifies visible, focused text entry.
The capability page and core checks retain 16 services, including one audio
player, across visits. The native suite runs again after view reentry and both
restart paths, checking painted SVG/chart output as well as service calls.
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
`.android-build/outputs/runner-debug.apk` plus a smaller
`.android-build/outputs/runner-debug-x86_64.apk` for emulator checks.
Both contain the full extension catalog, resources and fixed integration sample,
with the story sample and diagnostic counter/**Capabilities** pages for checking
services and local assets. The build requires identical shared payload hashes; native ABI
selection accounts for the smaller emulator APK.
The `Build RenPy-owned Android runner` workflow publishes both APKs. The separate
`Check Android runner` workflow selects the x86_64 artifact when available and
tests it on Android 35 emulators at 720p/280 dpi and 1080p/420 dpi, preserving
the same logical viewport. It records actual display settings, APK and harness
source commits, selected ABI, APK checksum and phase log checkpoints. Harness changes
can test the latest successful APK when its build inputs still match. The workflow
compares source commits before device execution and defers incompatible APKs.

The `Check runtime integration` workflow separately runs prepared-Flet lifetime
regressions, 500 real protocol events across five backend start/stop cycles,
and a 20-visit registry check retaining the same 16 service identities through
cyclic collection. Prepared-Flet regressions also require unowned services to
unmount without removing application-owned services.
The APK build runs Flutter analysis and lifecycle tests before native assembly.
[Runtime measurements](docs/performance.md) record the scope of the timing probes
and the work removed from idle polls and disposed controls.

## Rights

Original work authored for `main` is **all rights reserved**; no permission
is granted by the project notice. Third-party components and derived material
retain their respective licenses. See [LICENSE](LICENSE).
