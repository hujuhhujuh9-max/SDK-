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
the integrated build and emulators. Physical-phone operation and measurements
belong to the user alone. Workers report actual checks and skips.

Integration ownership additions: the coordinator owns the shared release-config
test expectation, `examples/capabilities/`, the new project-capabilities CI
workflow, its opt-in inputs/artifact steps in the existing build/integration
workflows, the manual phone handoff and final capability-matrix/documentation
links. The Activities worker owns the new
`scripts/check_project_capabilities.py` Android functionality harness, its
tests and a project-only native observer under `examples/capabilities/game/`
and `examples/capabilities/app/capabilities_observer.py`;
device operations remain with the coordinator. The Extensions worker
also owns extension-aware APK inspection/source inputs and the pinned YAML
build dependency. These additions do not change SDK archive ownership.

Integration review reproduced a pinned Flet protocol error when a method reply
arrives after its control is unmounted. The coordinator owns the component
patch/manifest on a separate Flet component worktree and its separate
`sdk-lock.json` integration change. No component branch is merged or cherry-picked
into the app branch. Rive owns its detached-callback guard and wire regression.
The coordinator owns review repairs in `runtime/renfletpy.py`,
`runtime/story_activities.py` and `tests/test_story_activities.py` while the
Activities worker finishes the Android harness. The Extensions worker owns
the generated Android Gradle configuration repair and its shared
`tests/test_flutter_cache.py` regression; the coordinator alone rebuilds the APK.
The coordinator owns the project-example input coverage in
`scripts/check_apk_source.py` and `tests/test_apk_source.py`.

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
renderers accept an `ActivityContext` and return a list of controls or an optional
`ActivityView` whose controls and complete SDK ancestry survive ordinary commits.
Load, Return, large-text layout changes and reconnect dispose that transient view
and reconstruct it from committed game values. The context
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

The complete prepared-Flet host suite passes **728 tests with zero failures,
errors or skips**. The integrated Flutter module passes analysis and **26 widget
tests**, including actual native Rive playback and project PulseDial lifecycle.
The five deliverables have separate acceptance evidence:

| Deliverable | Implemented behavior | Current evidence and remaining gate |
| --- | --- | --- |
| [Application navigation](project-navigation.md) | Project route parameters and aliases, bounded Back history, dialog dismissal, direct links, acknowledged Start/Resume/Return and session-owned screen models. Records and Saved games use the same registration interface. | Real pinned Flet page/protocol tests preserve drafts and selection through routes, story transitions and view reconstruction; stale route acknowledgements and detached asynchronous factories cannot replace newer intent. Combined Android emulator journey remains pending. |
| [Story activities](story-activities.md) | Versioned plain models, native-owner reducers, bounded command mailbox, atomic migrations, explicit completion/cancellation and optional retained control lifetime. | [Native receipts](../examples/activities/evidence/results.json): 19 assertions in five independently compiled Ren'Py processes, real quick/mobile saves, fresh-process restore, older-save migration and meaningful results. Real Flet socket/page tests preserve multichar edits and continuous gestures, and dispose transient services on load/removal/reconnect. Combined Android emulator journey remains pending. |
| [Flutter project packages](project-extensions.md) | Paired Python/Dart packages, generated registration, assets/notices, pinned dependency handling, clear setup failures, source inventories and cache invalidation. | New PulseDial renders custom pixels, accepts properties, sends typed events and cleans its ticker through five widget tests. The combined module retains all 19 SDK extensions, passes analysis and 26 widget tests. Fresh Android packaging and emulator component checks remain pending. New Dart/native code requires rebuilding the APK. |
| [Rive](rive-integration.md) | Consistent selected-artboard dimensions, number/boolean/trigger inputs, named event properties, disposal, background pause/resume and reconstruction from saved values. | [Loop receipts](../examples/rive/evidence/loop-validation.json): actual native `bouncing` pixels change at 2, 5, 10 and 30 seconds; paused/backgrounded pixels stay fixed; saved false restores frozen playback. Ten native Flutter widget checks and 19 native story/save assertions pass. Three-controller Android playback and lifecycle checks remain pending. |
| [2D workload scale](2d-acceptance.md) | Predeclared nominal/stress workloads, native ATL/compositing/two original shader effects, transformed Canvas, lazy lists, bounded editable tables and asynchronous filtering. | [Host samples](../examples/2d/evidence/host-protocol.json) record five repetitions and 20 inputs each; [native pixels/saves](../examples/2d/evidence/native/results.json) prove five Linux checks across two processes. Stress callbacks cost about 184/212 ms at p95 for Canvas/table on this cloud host. Android combined-flow functionality remains pending. Physical API 35 frame/input/startup/PSS limits remain unverified. |

The external [combined project](../examples/capabilities/README.md) exercises
all five interfaces together without adding SDK routes. Pushes to
`integration/project-capabilities`, or a manual **Verify integrated app recipes**
run with `verify_project_capabilities=true` and `build_app_starter=true`, build
the default story, app starter, combined debug APK and signed combined release
APKs. The API 35 emulator driver retains source/APK hashes, actual native saves,
control observations, gesture values, controller readiness/events/pixels and
cleanup logs. Default story and app suites remain separate gates.

Workspace network failures returned HTTP 503 while fetching Google Maven
dependencies after passing Flutter checks. They do not establish Android
packaging or device success. Remote CI performs the Android validation;
only a successful retained emulator receipt can complete that gate.

Physical measurements are the user's final manual phase, following
[the phone handoff](project-capabilities-phone-check.md). The AI uses emulators.
Missing raw hardware measurements remain `unverified`; Linux costs and emulator
functionality cannot establish phone frame-time, responsiveness, startup or PSS
limits. The executable [workload specification](../examples/2d/workloads.json)
and evidence verifier keep nominal and stress results separate.
