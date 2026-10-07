# Checks for parallel development

Use fast checks while editing and validate the combined result when a batch is ready.
The coordinator assigns scope, ownership and evidence using [parallel development](parallel-development.md).
These local choices do not disable automatic CI or replace required checks.

## Choose checks by the change

| Change | During iteration | Finished batch |
| --- | --- | --- |
| Documentation or agent instructions | Review links and commands | No APK build needed |
| UI text or layout | Relevant UI/bridge host tests; real Flet checks when events/navigation change | Inspect the changed screen; include in the next applicable integrated artifact check |
| Preparation, caching or packaging | Preparation, extension and APK-preservation host tests | Cold/warm/invalidation evidence; merged build and payload checks; device regression as appropriate |
| Story bridge, saves, preferences or native game state | Story, routing and shared-refresh host tests | Full host suite, real Flet checks, native Ren'Py probe, merged APK and device suite |
| Capability module or assets | Its feature tests; capability/storage tests as applicable | Real Flet/service checks when relevant; fresh APK and meaningful output or service evidence |
| JNI, Android host, Flutter lifecycle or plugin attachment | JNI/ownership/packaging tests; existing Flutter tests as relevant | Broad integration checks and fresh APK/device lifecycle, input and worker verification |
| Device/media harness only | Device, media-output and APK-source host tests | Existing source-compatible APK can be reused; run the affected verification when warranted |
| SDK internals or pins | Component checks and affected host tests | Archive then main pin/checksum; broad checks, fresh merged APK/device; save compatibility when affected |

## Commands from the repository root

Run one relevant host test file while editing, then the full suite for integration:

```sh
python3 -m unittest discover -s tests -p 'test_renfletpy.py' -v
python3 -m unittest discover -s tests -v
```

Other patterns: `test_prepare.py`, `test_flet_extensions.py`, `test_capability_preservation.py`, `test_apk_packaging.py`, `test_apk_source.py`,
`test_sdk_bridge.py`, `test_shared_refresh.py`, `test_tactics.py`, `test_capability_demo.py`, `test_core_capability_checks.py`,
`test_storage_checks.py`, `test_android_jni.py`, `test_android_jni_executor.py`, `test_device_smoke.py` and `test_media_output.py`.
Select the files that exercise the changed behavior.

Use the [Linux build environment](build-environment.md). Prepare Python 3.12 once;
reinstall dependencies only when requirements change:

```sh
python3.12 -m venv .android-build/venv
.android-build/venv/bin/python -m pip install -r requirements-build.txt -r runtime/requirements.txt
```

Real protocol, shutdown, lifetime and story/menu checks prepare pinned Flet
without an APK. Service ownership is a separate probe:

```sh
.android-build/venv/bin/python scripts/check_runtime.py
.android-build/venv/bin/python scripts/check_service_lifetime.py .android-build/runtime-inspection/flet
```

`check_runtime.py` already runs `check_flet_bridge.py`, including extension imports
and the prepared-Flet lifetime suite; do not repeat that command in the same gate.
`--output` changes the receipt location, not its mutable staging cache.

Native story/render/save checks need Xvfb and the prepared Ren'Py SDK:

```sh
.android-build/venv/bin/python prepare.py setup renpy
.android-build/venv/bin/python scripts/check_native_story.py
```

For save compatibility, append `--legacy-renpy-sdk /path/to/original/sdk`.
`--renpy-sdk` and `--output` select another installed SDK and receipt directory.
These are native Linux checks, separate from Android.

Build once after integrating application changes. The build analyzes/tests
Flutter, checks Flet and verifies both APKs and shared payloads:

```sh
.android-build/venv/bin/python build_android.py
.android-build/venv/bin/python scripts/device_smoke.py .android-build/outputs/runner-debug-x86_64.apk --abi x86_64 --expected-display 1080 1920 420
```

The device command assumes the configured Android 36 emulator and fresh PCM
capture from [build environment](build-environment.md); it does not create one.
CI runs the native probe before building and the complete device scenario separately.
Use that existing workflow for reproducible evidence.

## Ownership and evidence

Give each worker its own test files or reserve shared tests to one owner.
Use separate worktrees and mutable caches: staging deletes directories and runtime
checks use the checkout's `.android-build`. Receipt paths alone do not isolate builds.
Serialize the stateful device suite; it has no section selector or ADB serial option.
The coordinator owns one integrated artifact/device verification per finished
batch when required by its scope.

Keep SDK changes on their component branch: archive/manifest first, then a
separate main lock/checksum change; never merge SDK branches into main. Current
assembly copies top-level `runtime/*.py`; nested modules need a packaging change.
Preserve all 19 paired extensions, notices, native saves/input and renderer/thread
ownership. Camera stays disabled and player rollback stays removed.

Host lifetime tests may skip without prepared Flet; its real probe rejects skips.
Imports/catalog inclusion prove availability; output, native calls and fresh-process
receipts prove only exercised behavior. Record checks, skips, source SHA,
APK hash/ABI, device profile and remaining gaps.
Hardware features need suitable devices; emulator passes do not establish ARM
performance or every extension's functionality. Harness/docs changes may reuse a
compatible artifact through `check_apk_source.py`; changed app inputs require a
fresh APK. Repeat expensive checks after failures or relevant subsequent changes.
