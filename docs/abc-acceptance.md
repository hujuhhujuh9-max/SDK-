# A/B/C integration acceptance

D owns review, the shared optional route hook, and combined validation.
Integration branch: `integration/abc-app-recipes`.
Starting main revision: `b17a816144899665919462cd5d68e737c3fe0c6a`.
Main and the SDK component branches are not integration targets.

## Handoffs

| Worker | Expected job | Suggested source branch | Current handoff |
| --- | --- | --- | --- |
| A | Safe Flutter build-output reuse | `work/build-cache` | Not published at preparation time |
| B | Optional native dialogue/choice/input/ATL examples | `work/native-examples` | Not published at preparation time |
| C | Optional persistent Flet form/list recipe | `work/flet-app-recipes` | Not published at preparation time |

Names are suggestions until the owner/worker confirms them. D records each actual
branch/PR and reviewed head SHA before integration. A handoff includes changed
files, callable/CLI contracts, checks actually run, skips and remaining blockers.
An unfinished branch is not an accepted feature.

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

C supplies a top-level runtime module and an async page-entry callable. A preferred
interface, to confirm against C's handoff, is:

```python
async def open_page(page, route="/app-recipes", *, on_back=None):
    ...
```

`page` is the existing Flet page; `route` retains its query string; an optional
`on_back` is an async zero-argument callback supplied by D. D can adapt a small
compatible interface at the route seam instead of rewriting C's implementation.
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
- The current build/device workflows support `workflow_dispatch`; their automatic
  main-only build triggers do not validate this integration branch by themselves.
  Do not merge into main to cause a build. Use supported branch validation or a
  suitable local environment, and report unavailable prerequisites explicitly.

## Status

Acceptance criteria prepared; A/B/C reviews, merges, route implementation and
combined application validation are pending their published handoffs.
The preparation commit contains existing reviewed agent guidance and the small
Flet extraction-cache path correction; it does not contain worker feature code.
This workspace initially lacks JDK/Android build tooling, Xvfb and an emulator;
host checks are available. Record actual check receipts as prerequisites/work
become available rather than reporting the combined result as passed early.
