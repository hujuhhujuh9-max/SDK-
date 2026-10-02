# Ren'Py SDK 8.5.3

Branch: `sdk/renpy-8.5.3`

This is the complete Ren'Py SDK distribution. The matching Android packaging tools are staged separately on `sdk/renpy-rapt-8.5.3`.

The original archive is stored at `archives/renpy-8.5.3-sdk.tar.bz2` with Git LFS.
Its size is 153,611,590 bytes and its SHA-256 is:

```text
eb0a9be7f0fb13632fe25ceade9a8bed5a1b4d6b6e83bd19eeeb29e1a1bb4a45
```

From the repository root:

```sh
git lfs pull --include="components/renpy/archives/*"
cd components/renpy
tar -xf archives/renpy-8.5.3-sdk.tar.bz2
```

The extracted root folder is `renpy-8.5.3-sdk/`. Read the licenses and notices
inside the original distribution. `manifest.json` records the import details.
See `../../SDK_COMPONENTS.md` for the other branches and future integration.
