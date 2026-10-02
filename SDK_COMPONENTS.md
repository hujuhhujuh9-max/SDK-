# SDK component imports

These SDK distributions are staged independently for a later combined project.
Each branch starts at the original `main` commit `91f491f9841abba85b65a88f233c5dd7e5e70043`.
The root README and `main` were preserved. No integration or merge into `main`
has been performed.

| Component | Version | Branch | Component folder |
| --- | --- | --- | --- |
| Flutter Linux SDK | 3.44.8 stable | `sdk/flutter-3.44.8` | `components/flutter/` |
| Ren'Py SDK | 8.5.3 | `sdk/renpy-8.5.3` | `components/renpy/` |
| Ren'Py Android packaging tools | 8.5.3 | `sdk/renpy-rapt-8.5.3` | `components/renpy-rapt/` |

## Archive storage

Original archive bytes are tracked using Git LFS. Their total size is
1,767,496,062 bytes. Each component's `manifest.json` records the original
filename, size, SHA-256, source transfer, archive format, and unpacked root.
The complete distributions retain their original bundled licenses and notices.
No archive was executed or modified.

Install Git LFS before cloning or checking out these branches:

```sh
git lfs install
git clone --branch sdk/flutter-3.44.8 https://github.com/hujuhhujuh9-max/SDK-.git
cd SDK-
git lfs pull --include="components/flutter/archives/*"
```

To obtain another component, check out its branch and run `git lfs pull` with
that component's archive folder. See its component README for unpacking.

## Later integration

The three component folders use separate paths. Shared import documentation,
the Git LFS attributes, and the import helper are identical on all branches.
This keeps the staged work ready to combine when integration is requested.
SDK binaries are preserved as distributions; integration code and a shared
application are still future work. Flutter and Ren'Py are separate runtimes.
RAPT belongs with the matching Ren'Py SDK.

## Source and verification

Source: https://www.swisstransfer.com/dl/01a0fab0-e682-7215-9280-624cca43ef7f

The original transfer expires at `2026-10-17T03:38:12+00:00`. The imported Git LFS archives
do not depend on that transfer once they have been uploaded. The import
workflow downloads only the current branch's archive, verifies its byte count
and SHA-256, and pushes only that same `sdk/` branch. It never pushes to `main`.
The workflow may be rerun on an existing component branch to verify its archive.
