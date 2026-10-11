# Project capabilities batch

Base: `0fc79f001b2177a9a31dea31fd781b4cc298a510`. These are five separate
deliverables, with integration dependencies and independently recorded evidence.

## Ownership before implementation

| Owner | Worktree / responsibility | Files |
| --- | --- | --- |
| Coordinator | Navigation and final integration | `runtime/sdk_bridge.py`, `runtime/story_ui.py`, new `runtime/app_navigation.py`, `runtime/project_api.py`, existing Records/Saved games state adapters, navigation tests/docs, `examples/project_app/` |
| Activities | Saveable project story activities | `runtime/renfletpy.py`, new `runtime/story_activities.py`, native activity label in `game/script.rpy`, activity tests/docs and `examples/activities/` |
| Extensions | Project Python/Dart build path | `project.py`, `build_android.py`, `runtime/project_config.py`, `flutter/lib/extensions.dart`, Flutter pubspec/lock, new extension staging module, extension tests/docs and `examples/flutter_component/` |
| Rive | Interactive adapter and lifecycle | new Rive Python/Dart modules, Rive fixtures/tests/docs and `examples/rive/`; no central registry or build edits |
| Scale | Demanding 2D workloads and measurement | new workload modules, profiling scripts/tests, `docs/2d-acceptance.md`, `examples/2d/`; no Android host or central routing edits |

Component branches, SDK pins, Android startup and interpreter ownership are
reserved to the coordinator and remain subject to component ownership rules.
Each worker uses a separate worktree and mutable cache. The coordinator operates
the integrated build and any device. Workers report actual checks and skips.

## Boundary contract

Project configuration gains an optional `project_setup` callable (`module:function`).
The SDK invokes it once for registration before first use. A `ProjectAPI` object
exposes `register_screen` and `register_activity`; project code can also register
activities from native init Python. Registration contains factories/functions,
never saved renderer or service instances.

Screen state belongs to the navigation session, outside Ren'Py saves and outside
rebuilt Flet views. Screens receive a context with their state, navigation/Back,
dialog and story command methods. Native acknowledgements return to the invoking
app route, guarded against newer explicit navigation.

Activities register a versioned plain game-state model, renderer and explicit
completion/cancellation result. The story mailbox owns revisions and atomic
command consumption; only native story code executes Ren'Py operations. Flet
renderers accept an `ActivityContext` and return a list of controls. The context
exposes copied `state`, `revision`, `navigate`, `large_text`, `command`, `complete`
and `cancel`. Saved values exclude live controls/controllers/services.

Extension metadata selects paired project Python/Dart packages, their constructor,
assets and dependencies. Generated registration supplements the retained 19
extensions. SDK wrappers are added only for operations absent from the pinned
API. New Dart/native code requires APK rebuilding.

Rive uses the activity contract, versioned number/boolean values and meaningful
event results. Triggers are commands, not durable queued actions. Controllers are
recreated on mount/load and disposed on removal; background/resume is explicit.

Workload sizes and limits are specified before measurements. Linux protocol and
emulator functionality cannot establish physical API 35 phone performance.

## Evidence

Implementation and validation receipts will be added per deliverable. Unavailable
hardware checks remain unverified and must not be reported as completed.
