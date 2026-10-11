# Project Python/Dart components

Projects can add paired Flet packages without changing the SDK's central
registry. Add the package to `extensions` in `renfletpy.json`, then rebuild the
APK. Python properties and events use the pinned Flet 1.0.3 wire protocol;
Flutter widgets, tickers, services and Android plugins use their normal APIs.

The pinned Flet package already exports `FletExtension.createWidget`,
`createService`, `ensureInitialized`, `Control` property readers, event dispatch
and method listeners. Python exports `@ft.control`, `LayoutControl`, `Service`
and typed `Event` handlers. These existing interfaces are the supported runtime
API; the SDK adds package validation and generated registration. Source review:
[FletExtension](https://github.com/flet-dev/flet/blob/a87ca7fc8a813b9d821858083c7539e8e79ab3ba/packages/flet/lib/src/flet_extension.dart),
[Control](https://github.com/flet-dev/flet/blob/a87ca7fc8a813b9d821858083c7539e8e79ab3ba/packages/flet/lib/src/models/control.dart),
[paired Python example](https://github.com/flet-dev/flet/blob/a87ca7fc8a813b9d821858083c7539e8e79ab3ba/sdk/python/packages/flet-spinkit/src/flet_spinkit/spinkit.py).

## Manifest

```json
{
  "project_setup": "my_app:register",
  "extensions": [
    {
      "name": "project_pulse",
      "python_package": "components/pulse/python/project_pulse",
      "dart_package": "components/pulse/flutter/project_pulse",
      "dart_entrypoint": "project_pulse.dart",
      "dart_extension": "Extension",
      "control_types": ["project_pulse.PulseDial"],
      "service_types": [],
      "license": "components/pulse/LICENSE",
      "python_dependencies": []
    }
  ]
}
```

These are optional fields added to the usual project identity and source
configuration. Existing projects and the default story demo remain valid.
`project_setup` is a top-level `module:function` in `python_dir`. The SDK invokes
that callable with `ProjectAPI` for screen/activity registration before use.
Validation checks its path without importing project code; runtime verifies that
the referenced value is callable. The selected `PROJECT_SETUP` literal is staged
beside `APP_HOME` in `project_config.py` and sealed into the input inventory.

| Extension field | Contract |
| --- | --- |
| `name` | Shared, unique Python/Dart package name: lowercase letters, digits and underscores, starting with a letter. SDK, standard-library, application and selected package collisions fail. |
| `python_package` | Project-relative directory containing `__init__.py`; copied as that named package beside project Python modules. Nested source/data files are retained. |
| `dart_package` | Project-relative Flutter package with `pubspec.yaml` whose `name` matches the manifest. |
| `dart_entrypoint` | Dart file relative to the package's `lib/`; defaults to `<name>.dart`. |
| `dart_extension` | Exported zero-argument class extending `FletExtension`; defaults to `Extension`. Pub/analyzer enforce the actual type and constructor. |
| `control_types`, `service_types` | Unique wire names prefixed with `<name>.`, for example `project_pulse.PulseDial`. At least one is required. A name cannot be both kinds. |
| `license` | Nonempty project-relative notice file, retained unchanged in `third-party-notices/project-extension-<name>-LICENSE.txt`. |
| `python_dependencies` | Omit or use `[]`. Project pip installation and native Python wheels are unsupported; bundle licensed pure Python source. |

Source roots must be separate from `game_dir`, `python_dir`, `assets_dir`, and
other selected package roots. Escaping paths, links, generated caches, compiled
Python and prebuilt native output fail before SDK preparation. Package imports
must use the declared Python name; Python package discovery has no central list.

## Dependencies and assets

Declare Dart dependencies and assets in the package's own `pubspec.yaml`.
Supported dependencies are hosted version constraints, Flutter SDK dependencies,
and relative paths to other **declared paired** project packages. The builder
copies local packages and rebases those paths into private staging. Git sources,
unselected path packages, workspaces and project `dependency_overrides` fail with
a specific error. Flet and its 19 bundled package sources remain pinned to the
SDK. Normal Pub resolution produces the lock used in the AAR identity.

The ordinary Flutter Android plugin path is supported: local Android/Kotlin/Java
or native source belongs in the package, and hosted plugin dependencies resolve
through Pub and Gradle. Android/plugin compilation and final APK/device checks
remain required for each new native capability. Arbitrary Python native modules,
prebuilt binaries in project sources, and custom host/interpreter replacement
are outside this path. Camera, GPS and recording permission removals continue
to apply to merged plugin manifests.

Flutter asset and font declarations must select existing in-package files.
String file/directory entries and font assets are supported. Flavored or
transformed asset objects are currently rejected. A directory declaration
includes its direct files, matching Flutter; declare subdirectories explicitly.
Use `packages/<package>/<asset-path>` with `rootBundle`, or the normal `package`
argument on Flutter image widgets. Flet assets remain separately selectable via
the project's `assets_dir` and its normal `src` API.

Selected Dart source, asset, test and dependency bytes, generated registration,
resolved lock and the extension builder participate in AAR cache identity.
Python-only model edits can reuse the Flutter AAR. Every build recreates staging;
removed packages and tests cannot survive. The sealed APK project receipt records
paired Python files, Dart input fingerprints, package asset bytes and original
notices. APK inspection verifies Python/assets/notices and the literal setup
hook; Dart compilation consumes the recorded inputs rather than shipping Dart
source files as Python assets.

## Factories, errors and lifetime

Return `null` for a wire type your factory does not handle. Build a widget for
the declared type, read values through `Control`, and call `triggerEvent` for
typed Python results. Use Flet's existing method listener API for explicit
commands; remove every listener on disposal. Services follow Flet's existing
registration and disposal model. Extension initialization runs once during app
startup. Constructor and synchronous initialization failures include the project
package name and retain the original Dart stack; compile/dependency failures stop
the build. Async initialization failures should produce a defined error result
or event and release partially created resources.

Widget-owned controllers, subscriptions, native objects and asynchronous work
are reconstructed on mount and released on removal. Guard late callbacks after
disposal. Define foreground/background and `TickerMode` behavior. Plain game
values belong in the screen/activity model; a Flutter control or service must
never enter a Ren'Py save. Project activities communicate through the registered
activity context commands/results; native story operations remain on the story
thread. Changing Dart, assets, dependencies or native source requires a rebuilt
APK; changing only saved Python values does not create a new Flutter component.

## Example and evidence

The [pulse example](../examples/flutter_component/README.md) implements a new
Flutter `CustomPainter` and local animation ticker. Python changes its value,
intensity and playback. Tapping returns a typed selection result. Its package
asset supplies its color; lifecycle callbacks report playback changes. The
project registers `/app/pulse` through `ProjectAPI`, with note/selection state
owned by the navigation session across view rebuilding and story transitions.

Project Dart tests are copied into the staged runner's `test/project_extensions/`
and run with the normal Flutter gate. Their dev dependencies resolve in that
runner. Use `package:<name>/...` library imports in these tests; file fixture
paths are relative to the generated runner. The example includes both component
tests and a runner integration test that calls the generated registry, renders
the component and receives a tap.

Validation has separate scopes:

- Host tests exercise schema/source/dependency collisions, cold/warm cache reuse,
  invalidation and removal, plus sealed APK Python/assets/notices/setup claims.
- Real pinned-Flet tests exercise encoded properties, typed events and rebuilding
  controls from the same plain state.
- Flutter widget tests exercise generated registration, actual changed raster
  pixels, property patches, package assets, selection events, background/resume,
  error callbacks, disabled input, disposal and reconstruction.
- A fresh integrated Android APK and device run establish Android functionality.
  Linux widget tests cannot establish phone frame times or physical API 35
  performance.
