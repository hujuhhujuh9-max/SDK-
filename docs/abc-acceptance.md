# A/B/C integration acceptance

D owns review, the shared optional route hook, and combined validation.
Integration branch: `integration/abc-app-recipes`.
Starting main revision: `b17a816144899665919462cd5d68e737c3fe0c6a`.
Main and the SDK component branches are not integration targets.

## Handoffs

| Worker | Expected job | Confirmed suggestion | Reviewed source |
| --- | --- | --- | --- |
| A | Safe Flutter build-output reuse | `work/build-cache` | [`build/safe-flutter-output-reuse`, PR #4](https://github.com/hujuhhujuh9-max/SDK-/pull/4), `884b9480f6872641c3f29663d29fb29bb6f27b4b` |
| B | Optional native dialogue/choice/input/ATL examples | `work/native-examples` | `examples/renpy-dialogue-choice-input-animation`, `6b31426787e3ae97419c6bb03e78afef0989a227` |
| C | Optional persistent Flet form/list recipe | `work/flet-app-recipes` | `feature/reusable-form-list`, `fc2298ff9b29f313f3d051b0276d7b7601e37467` |

The owner confirmed the suggested names after A/B/C had published under the
actual names above. Their existing branches are retained. A handoff includes changed
files, callable/CLI contracts, checks actually run, skips and remaining blockers.
An unfinished branch is not an accepted feature.
These heads are the frozen source cut for this batch, including the published
follow-ups. Later worker commits require a separate review and validation.

## Preserve the existing setup

- Keep the current story-first demo and default root route. New examples and
  app recipes are optional; do not replace startup, the host or native saves.
- Keep Ren'Py/SDL as startup/story/interpreter owner. Flet callbacks submit data;
  native flow/save/load/preferences run on Ren'Py's thread, UI updates on Flet's.
- Keep the SDK pins/component archives, paired 19-extension catalog and notices.
  This batch does not need component-source, registry, permissions or host changes.
- Keep CAMERA permission/hardware removal and the modified rollback-free engine.
  Preserve manual/autosave/mobile recovery, history, saved RNG/mutable state,
  stale-event rejection, input/Back and existing diagnostics routes.
- Give one writer to each shared file/test. D owns `runtime/sdk_bridge.py`, the
  optional shared menu/diagnostics hook and new integration regression tests.
  D reviews proposed edits to reserved files rather than silently accepting them.
- Keep writable build trees isolated. Serialize the final stateful device suite.

## A: cache behavior

Acceptance requires behavior and evidence, not a cache-present flag alone:

1. An unchanged complete AAR/Maven output is reused. A Python/game-only change
   still produces a fresh APK but can reuse that Flutter output.
2. Relevant Dart, local plugin, SDK/patch, dependency and build-tool inputs
   invalidate reuse. Local path plugins are not identified by `pubspec.lock`
   alone. Record the actual cache-key inputs and cache schema/recipe identity.
3. Missing, incomplete, corrupt or failed output rebuilds. Publish successful
   output atomically and preserve a supported force-rebuild path.
4. Retain the complete Maven repository/metadata/plugin artifacts and prevent
   stale resolution under the fixed `flutter_debug:1.0` coordinates.
5. Keep Flutter analysis/tests and default universal + emulator APK verification.
   Keep both APK inventories, all 19 extensions and matching shared payloads.
6. Review meaningful hit/miss/invalidation/failure tests. Measure cold, warm and
   Python-only-change phases when build prerequisites are available; cache reuse
   does not establish FPS or device behavior.

## B: native examples

1. New examples are opt-in labels/files with distinct names. They do not change
   default `label start`, configuration, existing transforms or save semantics.
2. Examples compile and the documented native entry points actually run. Exercise
   dialogue, choice/result, text input and animation using the pinned engine.
3. Ren'Py invokes native operations on its thread. Reuse existing labels/result
   conventions; do not introduce another interpreter or a replacement save engine.
4. Verify affected native behavior and the existing story/save/recovery checks.
   Original-save compatibility remains required when save semantics change.

## C and D: optional app route and persistent recipe

C supplies top-level runtime modules and this async view factory:

```python
async def create_form_list_view(page, *, route="/records", title="Application records",
                                fields=DEFAULT_FIELDS,
                                storage_key=DEFAULT_STORAGE_KEY, on_back=None):
    ...
```

`page` is the existing Flet page; `route` retains its query string. `on_back` is a
Flet button event handler supplied by D. The factory returns a loaded View and
leaves mounting/navigation to D. See [form/list API](form-list.md) for its complete
signature. D routes `/records` from diagnostics or an explicit app link, reuses
the same view for query changes, and discards unfinished loads on route departure.
Current packaging copies top-level `runtime/*.py`, not arbitrary nested modules.

1. Keep the new screen optional, with a bounded hook from diagnostics or an
   explicit link. Ordinary launch and existing routes keep their behavior.
2. Cold/warm/query links open one recipe view. Repeated routing/reentry avoids
   duplicate views, players/services and subscriptions. Back/close returns to the
   correct existing route and restores native input/presentation when returning.
3. Opening the recipe holds pending story choices. Return to the story preserves
   their state/revision; duplicate or stale completions cannot advance it.
4. Observable form/list actions persist under application storage, independently
   of story snapshots. Reentry and a fresh process recover records. Loading an
   older story save and replay do not restore older app data or preferences.
5. Validate normal and invalid input plus meaningful I/O failure behavior; do not
   silently replace existing data after a failed read/write. Verify pinned Flet
   constructor/callback signatures and real protocol results, not imports alone.
6. Keep explicit app links during background recovery, existing deep links and
   routing/Back behavior. Native-service lifecycle changes need device evidence.

## Combined gates

Use [agent checks](agent-checks.md) for commands and prerequisites:

- Review each source diff against its base, reserved files and handoff evidence.
  Record source head SHAs and resolve any collisions before combining main-derived
  worker commits. Component branches are consumed through archives/pins, never merged.
- Run focused new cache/recipe/route tests, then the complete host suite on the
  integrated revision. Keep preparation, capability-preservation, APK/source,
  story/shared-refresh and JNI tests passing. Record skipped prepared-Flet cases.
- Run real prepared-Flet protocol/lifetime/service checks after routing changes.
  Add a real recipe event/result scenario once C's controls/API are known.
- Run the actual Ren'Py/Xvfb probe plus B's native examples. Add original-save
  compatibility verification if a reviewed change affects those semantics.
- Produce one final integrated build and validate its catalog/ABI/shared payloads,
  then run the full stateful Android suite against that source-compatible artifact,
  including the new optional route/data evidence. A's cache timing exercises are
  separate build-optimization evidence; they are not four independent final builds.
- `integration-abc.yml` runs only on `integration/abc-app-recipes` changes and
  calls the existing runtime/build/device workflows. The device job consumes
  artifacts from that same run, after both build and runtime succeed. Existing
  main/dispatch triggers stay intact. A newer integration build cancels a
  superseded integration build; main retains its serialized build behavior.
  No merge into main is needed for validation.

## Status

Source reviews and local combination completed on 2026-10-07. Changes are limited
to the build cache, optional native examples, optional form/list modules, D's
route/checks and documentation. SDK pins, Android host/permissions, Flutter client,
camera exclusion and rollback removal are unchanged. The root game's startup and
entry point are preserved; D adds one checkpoint after opening initialization to
fix pre-existing quick-load and mobile-recovery failures at the first interaction.

Local receipts on the combined tree:

| Check | Evidence |
| --- | --- |
| Complete host suite with pinned Flet | 247 passed, zero skips; without prepared Flet, 212 passed and 35 cases explicitly skipped |
| Prepared Flet coverage | All 35 dependent cases passed: 20 lifetime, 6 form/list control/protocol, 7 actual socket, 2 combined route/data |
| Complete form/list check command | 42 checks passed without skips, including native read/write timeouts, uncertain writes and stale records |
| Existing real socket protocol | 500 events across 5 backend cycles, zero idle messages; existing story/save/reading scenarios passed |
| Capability service lifetime | 20 navigation cycles retain the same 14 services |
| Native story suite | 72 checks across 14 actual processes; all original 55 passed, plus opening quick save/load, valid baseline-bookmark compatibility and fresh/replayed opening mobile recovery |
| Optional native examples | Four independent compiles, gallery compile/lint and 48 live checks passed, including first-interaction save/load, host variable preservation and native rendering |
| Native example rollback guard | Rollback APIs/actions/key bindings/forward state absent before and after native input save/load; checkpoint remains available |
| Workflow/static review | actionlint 1.7.11, Python compilation and whitespace checks passed |

Generated receipts are under `.android-build/runtime-check/`,
`.android-build/native-story-check/` and `.android-build/d-native-example-check/`.
The expanded B review receipts are in the isolated review worktree under
`.android-build/d-native-final/` and `.android-build/d-native-rollback/`; CI runs
the same committed verifier and uploads `.android-build/renpy-examples-check/`.
The extended save review receipt is
`/tmp/sdk-d-opening-mobile/full-native-suite/results.json`; CI runs those modes in
the existing native runner and uploads its JSON/logs with the same artifact.
The prepared-Flet native preference replies are emulated on Linux; these tests
do not prove Android SharedPreferences persistence by themselves.

The [final combined CI build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37676378548)
passed its runtime and build jobs on source
`e66a2aaa8e066a2851425976399b8db343b7bdd4`. Both APKs passed inventory, camera
permission, ABI and shared-payload checks: all 19 extensions, 541 upstream Python
files and 367 Android assets were verified. The universal APK supports
`arm64-v8a`, `armeabi-v7a` and `x86_64`; the emulator APK supports `x86_64`.

| Artifact | SHA-256 |
| --- | --- |
| `runner-debug.apk` | `e250749569fb5304e0a8eeaf2bbe222bf317d767579f6b56ae57fd2d6bd3b9f0` |
| `runner-debug-x86_64.apk` | `8a80be93dae3ec261ef0705d9ba744d2770e2fc46a9ff6a19a11521096b1dc99` |

Cold AAR compilation in the preceding frozen-worker build took 237.2 seconds.
The final game-only fix reused that verified AAR across CI runs, with zero AAR
compilations in the build and both probes. The actual warm Flutter stage took 23.3
seconds; a Python-only-change stage took 22.3 seconds. Both warm phases ran
create/dependency resolution/analysis/tests.
These measurements describe this CI runner/toolchain and do not measure FPS.
The verified receipt fingerprint is
`01e4eb420ebea3f7717c5c0c4a7cc935d2b0328b852c7174d845aff893089cf3`.
All 978 shared APK entries have matching SHA-256 hashes. Artifact IDs are
`11507940937` (universal APK, 601,263,069 bytes) and `11508925278` (emulator APK,
229,870,153 bytes). The native check artifact is `11508445645`.

Full device validation is pending. The first device run passed the existing
checks but caught a recipe defect: the pinned Flet API serializes `TextField.error`,
while C used the older `error_text` name. Empty input was rejected, but its field
error never reached Flutter. D corrected the property and added a real encoded
patch regression for required/length errors and clearing them after a valid save.
The [preceding worker-source Android run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37668248775)
passed the existing suite, required-field display, record creation and editing,
then exposed the opening-scene quick-load failure. Both original `b17a816` and
combined `f3531fb` fail that load: the native restore callback loses its default
state and leaves the menu busy. The original code also loses opening defaults on
mobile recovery immediately after first launch or Replay. One checkpoint after
opening initialization fixes both paths. It preserves the exact opening history,
releases the busy state, consumes the background recovery save, and also restores
a valid one-move bookmark written by the original script. Native rollback guards
pass before and after those loads. Startup and after-load callbacks are unchanged.
The committed native runner now covers these cases; CI seeds the compatibility bookmark
using the immutable starting-main script. A fresh combined APK/device run is
required for this bounded fix. The final hashes above include it. That run's
Android job passed audio, video play/pause/resume and animation play/pause before a
HOME/resume ordering
race left the harness polling Launcher. D now waits for native backgrounding,
confirms runner focus on resume and asserts the same PID across every warm resume
scenario. This changes only the harness; it reuses the verified emulator APK.
The final source cut also incorporates A's pre-compilation source snapshot and
CMake installation, B's independent first-interaction saves/local input result,
and C's bounded native preference calls, Reload guards and actual socket suite.

The device harness also tightens Replay selection, requires a native recovery
marker for the new PID, and requires actual device receipts. The APK source
comparison must pass. Harness-only changes do not trigger another build. The
fallback artifact pin is `37676378548`; a source mismatch fails integration
acceptance. The fast form/list workflow also includes the integration branch,
so a check-script-only change does not need another APK to exercise that check.
The normal main build/dispatch behavior remains intact.

The device suite adds actual record creation,
editing, older story load/replay independence, Back/reentry, background resume,
fresh-process persistence with an explicit app link, and deletion. The build
keeps both APKs and runs `check_flutter_reuse.py` afterward without creating more
APKs. Record that run's source/artifacts/results before declaring Android passed.
