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

## Final review after `c29fa79`

The coordinator owns the follow-up edits to `runtime/sdk_bridge.py`,
`project_extensions.py`, `flutter/lib/rive_control.dart`,
`scripts/scale_evidence.py`, their dedicated navigation/extension/Rive/evidence
tests, the integration workflow filter and the affected documentation.
Independent runtime and extension/Rive reviews were read-only.

The coordinator also owns the final API 35 harness repair in
`scripts/check_project_capabilities.py` and `tests/test_project_capabilities.py`.
The parser keeps complete concatenated JSON markers bound to their original
Android log PID and line, and rejects corrupt payloads or unrelated suffixes.
This harness-only change uses the source-compatible APK from the fresh build.

Source `243310fa4f97dc84a819480dfd0b0f8381b91ff8` fixes Android Back at Home
after initial or unknown-link normalization, includes the exact Flutter asset
variants for directory and file declarations, and recovers a mounted Rive
control after correcting an initial selector/input error. A complete eligible
physical bundle exceeding thermal severity 2 now fails; missing evidence remains
unverified. The integration push filter also covers project extension and
example inputs. No SDK pin, startup owner or physical-device policy changed.

The new navigation, asset and evidence regressions fail before their fixes.
Focused Python validation passes 75 checks, followed by 45 harness checks.
The required prepared-Flet CI suite passes **783 tests without skips**.
The integrated debug and release modules pass analysis and **34 Flutter tests**,
including both initial Rive error-recovery regressions.
[PR #40](https://github.com/hujuhhujuh9-max/SDK-/pull/40) remains ready for review
and unmerged. Physical performance remains unverified.

## Evidence

The complete prepared-Flet host suite passes **783 tests with zero failures,
errors or skips**. The integrated Flutter module passes analysis and **34 Flutter
tests**, including actual native Rive playback and project PulseDial lifecycle.
The five deliverables have separate acceptance evidence:

| Deliverable | Implemented behavior | Current evidence and remaining gate |
| --- | --- | --- |
| [Application navigation](project-navigation.md) | Project route parameters and aliases, bounded Back history, dialog dismissal, direct links, acknowledged Start/Resume/Return and session-owned screen models. Records and Saved games use the same registration interface. | Real pinned Flet page/protocol tests preserve drafts and selection through routes and view reconstruction. API 35 assertions pass for direct links, Android Back, dialogs, Start/Return and the existing screens; retained XML confirms the project draft and selection. |
| [Story activities](story-activities.md) | Versioned plain models, native-owner reducers, bounded command mailbox, atomic migrations, explicit completion/cancellation and optional retained control lifetime. | [Native receipts](../examples/activities/evidence/results.json): 19 assertions across five compiled Ren'Py processes, older-save migration and meaningful results. API 35 Canvas/Rive activities quick-save/load and recover after process loss with exact game values and native owner proofs. Real Flet socket/page tests cover retained edits/gestures and transient service disposal/reconstruction. |
| [Flutter project packages](project-extensions.md) | Paired Python/Dart packages, generated registration, assets/notices, pinned dependency handling, clear setup failures, source inventories and cache invalidation. | Five PulseDial widget tests and actual API 35 pixels, property updates, typed selection events, remove/recreate and background/resume checks pass. The combined module retains all 19 SDK extensions, passes analysis and 34 Flutter tests, and builds inspected debug/signed-release APKs. New Dart/native code requires rebuilding the APK. |
| [Rive](rive-integration.md) | Consistent selected-artboard dimensions, number/boolean/trigger inputs, named event properties, disposal, background pause/resume and reconstruction from saved values. | [Loop receipts](../examples/rive/evidence/loop-validation.json), twelve Rive adapter tests and 19 native story/save assertions pass. API 35 verifies all three controllers, moving/frozen/resumed pixels, saved number/boolean restoration, a real trigger event, one meaningful native result and disposal of every ready controller. |
| [2D workload scale](2d-acceptance.md) | Predeclared nominal/stress workloads, native ATL/compositing/two original shader effects, transformed Canvas, lazy lists, bounded editable tables and asynchronous filtering. | [Host samples](../examples/2d/evidence/host-protocol.json) retain five repetitions and 20 inputs each; [native pixels/saves](../examples/2d/evidence/native/results.json) prove five Linux checks. API 35 nominal native animation, Canvas selection/pan/two-pointer zoom, table editing/async work and the combined story flow pass. Stress callbacks cost about 184/212 ms at p95 for Canvas/table on this cloud host. Physical API 35 frame/input/startup/PSS limits remain unverified. |

The external [combined project](../examples/capabilities/README.md) exercises
all five interfaces together without adding SDK routes. Pushes to
`integration/project-capabilities`, or a manual **Verify integrated app recipes**
run with `verify_project_capabilities=true` and `build_app_starter=true`, build
the default story, app starter, combined debug APK and signed combined release
APKs. The API 35 emulator driver retains source/APK hashes, actual native saves,
control observations, gesture values, controller readiness/events/pixels and
cleanup logs. Default story and app suites remain separate gates.

The [Android build job](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38146631432/job/114491259062)
passes from SDK source `243310fa4f97dc84a819480dfd0b0f8381b91ff8`, including
the final application repairs. The later harness repair changes no APK input.
Its project input SHA-256 is
`195e081e6997f6a4379c0f9a9840018804d25f011bbacfcee66e0583ba8aad3e`.

| Artifact | APK SHA-256 | Verified scope |
| --- | --- | --- |
| [Combined x86_64 debug APK](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38146631432/artifacts/11705189234) | `8bdb35e863b8767ad4dd33be4dec92036d78a3d465fe4d40d7f409ef82958bd6` | App startup, exact packaged callback-context repair, project registration, all 19 extensions, 541 upstream Python files and 368 Ren'Py assets. |
| [Combined signed release APKs](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38146631432/artifacts/11705710498) | Universal: `3a8be7ef4872f60ded4c654937630c0f31a059dcf2cc5305d66629df0937e88b` | ARM64/ARMv7/x86_64 universal plus x86_64 variant; both v2 signatures verified; all 984 shared payload entries match. |

The separate Android 36 x86_64 regression suites pass from that same source:
[default story](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38146631432/artifacts/11706328483)
and [app starter](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38146631432/artifacts/11707155200).
Both retain successful native save/recovery and app-recipe receipts, with no
diagnostic errors or skipped app-recipe checks. The app suite also verifies
that switching startup templates preserves the default story's real saves and
newer application records.

The [API 35 combined journey](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38149614252)
passes with zero skips, using harness source
`85d95c6d998197741f3fe83233fd47ded8125fcc` and the exact debug APK above.
The source comparison rejects changed application/build inputs. This successful
run supersedes the earlier parser-only combined-gate failure in the build
workflow. Two complete JSON markers shared one Android log line; the repaired
parser retains both with the same origin PID/line and preserves duplicate-key,
nonfinite-value, malformed-payload and unexpected-suffix rejection.

Its [complete raw artifact](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38149614252/artifacts/11705877947)
contains `capabilities-device.json` and 100 sealed app files. The untouched
download passes `scripts.scale_functionality.evaluate_functionality`: every
recorded hash and size, actual native archives, owner-thread records, gestures,
Rive inputs/events/pixels, single results and disposal checks revalidate.
The three independently started app PIDs are `3495`, `7792` and `9184`.
The read-only emulator archive reader restores shell UID 2000 and verifies the
same app PID/UID before publishing each archive. Background capture requires
fresh controller readiness and replacement of the prior recovery archive.
The live `emulator.log` remains a separate diagnostic file because shutdown
appends to it after sealing; app evidence retains strict hash checks.

Use the harness source recorded above to revalidate the downloaded directory
without connecting to a device:

```sh
python3 scripts/check_2d_evidence.py \
  --functionality /path/to/capabilities-device.json \
  --output /tmp/capabilities-evidence-status.json
```

With no physical bundles this reports functionality `pass`, performance
`unverified`, exactly 16 missing measurements, and exits 1. That is the expected
status before the user's manual phone phase.

Physical measurements are the user's final manual phase, following
[the phone handoff](project-capabilities-phone-check.md). The AI uses emulators.
Missing raw hardware measurements remain `unverified`; Linux costs and emulator
functionality cannot establish phone frame-time, responsiveness, startup or PSS
limits. The executable [workload specification](../examples/2d/workloads.json)
and evidence verifier keep nominal and stress results separate.
