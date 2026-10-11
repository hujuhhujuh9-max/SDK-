# Project extension validation receipt

Date: 2026-10-11. Source base: `0fc79f001b2177a9a31dea31fd781b4cc298a510`,
with the project extension workstream changes. No SDK archive or lock pins changed.
This receipt covers workstream 3; Android integration is recorded separately by
the batch coordinator.

## Exercised

| Check | Result |
| --- | --- |
| Project extension validation/staging/cache/removal tests | 12 passed. Paired source/dependency collisions, pinned Flet preservation, cache reuse/invalidation and deleted-package cleanup. |
| Extension APK inventory tests | 4 passed. Actual Python/asset/notice bytes and literal setup configuration are required by sealed claims; old project receipts remain accepted. |
| Real pinned-Flet protocol tests | 2 passed without skips. Typed selection/lifecycle events update plain state; rebuilt controls retain selection and note. |
| Isolated Flutter dependency resolution | Passed using Flutter 3.44.8 and the patched pinned Flet 1.0.3 source. All 19 bundled paired packages remain direct dependencies. |
| Flutter analyzer | No issues in staged `lib` and `test`. |
| New component widget/integration tests | 5 passed. Generated registry renders the component, actual raster pixels change after a property update, tap events carry selection, asset/error callbacks work, background pauses/resume plays, and disposal leaves no ticker or late callback. Reconstruction restores the Python selection. |
| Broader host packaging/cache/regression group | Integration includes the legacy literal-config assertion for `PROJECT_SETUP=None`; the complete prepared-Flet suite passes 774 tests without skips. |

The local generated module was
`/workspace/sdk-extensions/.android-build/extension-validation/flutter`, with
an isolated copied Flutter SDK and Pub cache. The machine-readable receipt is
in that checkout's ignored `.android-build/extension-validation-result.json`;
it records the final component test/source identities and the Rive adapter used
for compiling the shared registry. The Rive worker's adapter was copied into
private staging only; this workstream does not own or patch it.

The component test suite caught and corrected a resume-test timing assumption:
the first resumed ticker sample has zero elapsed time. An initial frame precedes
the measured resumed interval. The final source and staged tests match. The
analyzer also caught an unused test import, which was removed.

## Reproduce

```sh
PYTHONPATH=tests:/path/to/prepared/flet/sdk/python/packages/flet/src \
  python3 -m unittest test_project_extensions test_project_extension_apk test_project_extension_flet
python3 examples/flutter_component/prepare_example.py /tmp/project-pulse
python3 build_android.py --project /tmp/project-pulse/renfletpy.json
```

The normal project build copies package tests into the generated runner and runs
Pub, analyzer and Flutter tests before building an AAR. Its Linux Rive tests
prepare the pinned native library with `dart run rive_native:setup --platform
linux`; Android native assembly remains Gradle's responsibility.

The integrated project-selected debug and signed release APKs build successfully
in [run 38135327048](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38135327048),
from SDK source `14eb81c8eae439357b8d1f5449a51106e82038b9`.
Their inventories verify all 19 retained SDK packages and the selected project
Python, Dart, asset and notice bytes. Both generated debug and release modules
pass analysis and all 32 Flutter tests. The release universal and x86_64 variant
have identical hashes for all 984 shared payload entries; the universal APK's
v2 signature verifies. Full Android acceptance is recorded in the
[batch receipt](project-capabilities-batch.md).

The [API 35 combined artifact](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38142196387/artifacts/11702514282)
also verifies the project-selected PulseDial on Android: actual painted motion,
selection events, value/intensity changes, pause/resume, removal/recreation with
retained model values and background/resume. The complete raw receipt passes
revalidation without operating a device.

A baseline SDK APK without the manifest-selected pulse package does not validate
the project package build path. No physical API 35 frame-time, startup or memory
claim is made here.
