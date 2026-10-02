# Flutter Linux SDK 3.44.8

Branch: `sdk/flutter-3.44.8`

This is the Linux stable SDK. The source filename ends in `.tar.xz.tar`, but the verified file header is XZ-compressed tar; the original filename and bytes are preserved.

The original archive is stored at `archives/flutter_linux_3.44.8-stable.tar.xz.tar` with Git LFS.
Its size is 1,545,329,948 bytes and its SHA-256 is:

```text
672089e001571a9fbb209a495c583580c0c6c73ef98999264ba07fa93ace332d
```

From the repository root:

```sh
git lfs pull --include="components/flutter/archives/*"
cd components/flutter
tar -xf archives/flutter_linux_3.44.8-stable.tar.xz.tar
```

The extracted root folder is `flutter/`. Read the licenses and notices
inside the original distribution. `manifest.json` records the import details.
See `../../SDK_COMPONENTS.md` for the other branches and future integration.
