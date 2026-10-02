# SDK-: fixed Android runtime integration

This project builds one Android application on a Linux development workspace.
The app will contain a fixed modified Flet/Flutter/Ren'Py stack. Its components
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

Build input preparation is implemented and tested. The Android Activity,
rendering, and Python startup overlap is documented in
[docs/runner-overlap.md](docs/runner-overlap.md) for discussion with the project
owner. No shared Android runner or APK has been built yet.

```sh
python3 -m unittest discover -s tests -v
```
