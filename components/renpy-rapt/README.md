# Ren'Py Android Packaging Tool (RAPT) 8.5.3

Branch: `sdk/renpy-rapt-8.5.3`

These are the Android packaging tools for Ren'Py 8.5.3. The ZIP unpacks into `rapt/`; place that folder within the matching extracted Ren'Py SDK when Android packaging is needed.

The original archive is stored at `archives/renpy-8.5.3-rapt.zip` with Git LFS.
Its size is 68,554,524 bytes and its SHA-256 is:

```text
8a12be34a2f5238d125ff6dd76a56772fd8e44838af864f81bca82c1059b00e6
```

From the repository root:

```sh
git lfs pull --include="components/renpy-rapt/archives/*"
cd components/renpy-rapt
unzip archives/renpy-8.5.3-rapt.zip
```

The extracted root folder is `rapt/`. Read the licenses and notices
inside the original distribution. `manifest.json` records the import details.
See `../../SDK_COMPONENTS.md` for the other branches and future integration.

## Fragment-compatible SDL host

`patches/fragment-activity.patch` is an altered SDL Java source version. It
changes the base Activity to AndroidX `FragmentActivity` for Flutter plugins
that need fragments, including biometric authentication. SDL/Ren'Py still
owns native startup, its interpreter, surface, and callbacks. The original
archive stays unchanged. The shared build supplies the AndroidX dependency.

The SDL-derived patch follows SDL's zlib license, retained in
`SDL-LICENSE.txt`. It is not covered by main's reserved-rights notice.

## Canceled Android activity results

`patches/null-activity-result.patch` fixes Ren'Py's activity-result logging when
Android returns a null `Intent`, including cancellation of Flutter's system
file picker. The original code calls `toString()` on that null result and
crashes before the Flutter callback runs. The patch uses `String.valueOf()`
for the log message and forwards the original result unchanged.

This Ren'Py-derived patch follows the original distribution's license,
retained in `RenPy-LICENSE.txt`; main's reserved-rights notice does not apply.
The original RAPT archive remains unchanged.
