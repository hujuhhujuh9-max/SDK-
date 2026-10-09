# Working on RenFletPy

Read [CONTRIBUTING.md](CONTRIBUTING.md) before changing branch-owned inputs.
The product is one Android app, developed on Linux. Ren'Py/SDL owns startup,
the story loop and the single Python interpreter. Flutter is embedded;
Flet runs on its own event loop in that interpreter.

The user wants **general-purpose Android apps with story features** while
preserving the existing setup. Extend the current runner and bridge with
optional app screens, navigation, data and service recipes. Preserve the
existing story-first demo and its entry point; a general-purpose app shell is
an opt-in template or project feature, not a replacement default. Ren'Py/SDL
keeps startup/interpreter ownership. Keep app data independent of story
bookmarks; loading a story must not restore older application data.

Prefer additive, bounded changes using existing APIs. Do not replace the
integration, change default startup/navigation, remove existing behavior or
expand into a broad refactor as part of adding an app recipe. Validate affected
existing behavior and the new feature. A requested product focus is not an
instruction to redesign the SDK or overwrite the working sample.

## Parallel work

For work with independent deliverables, use up to four workers with one
coordinator. The user gives the coordinator one goal; the coordinator divides
it, assigns ownership, resolves dependencies and integrates the result.
Handle a small isolated fix directly when splitting it would add overhead.

Use the task tree and task template in
[parallel development](docs/parallel-development.md). The four lanes are:

- Build: preparation, reusable Flutter output, packaging and build workflows.
- Ren'Py: story entry/resume/return, native authoring, state and saves.
- Flet/Flutter: app navigation, reusable screens, app data and existing services;
  Dart extensions
  only for a specific capability absent from the pinned Flet API.
- Integration: acceptance fixtures, regression checks and combined validation.

Before workers edit code, record one owner for every changed file and the
small command/result/state contract between dependent tasks. Reserve central
routing, the Android host, SDK pins and extension registration for one named
owner. The lane table is a starting point; each task's exact file list wins.

Use separate worktrees from the same base revision for parallel implementation.
Keep writable SDK installations, `.android-build`, generated Flutter/Gradle
projects and output directories separate. Current staging deletes directories,
and SDK tools write their installations. Share only verified immutable artifacts.
Disjoint documentation edits can share a checkout without index/branch changes.
One owner operates a given emulator/device and integrates the final artifact.

SDK archives, patches and manifests stay on their component branches. Consume
them through a separate `sdk-lock.json` integration change on `main`; never
merge or cherry-pick component branches into `main` or into one another.

## Preserve capabilities

Keep the paired 19-extension Flet catalog, resources, assets, native libraries
for the selected ABI, and original third-party notices. Keep phone-camera
access, GPS/location and audio recording disabled through Android manifest
merger removals, while retaining their bundled plugin code. Keep player
rollback removed: these are explicit product choices.

Prefer existing Ren'Py configuration/authoring and Flet APIs for application
features. Distinguish packaged, exposed, tested and unavailable capabilities.
Neither package retention nor import success proves all operations work.
Flet does not expose every Flutter package automatically; identify the specific
missing operation before adding Dart code or changing SDK internals.

Flet callbacks submit plain commands/results; Ren'Py's story thread executes
native flow, rendering, save/load and preference operations. Schedule Flet UI
changes on Flet's loop. Preserve revision guards, single consumption, menu
completion gating, save restoration/migrations and worker class-loader handling.
Never save live services, locks, listeners, native surfaces or renderer objects.

New runtime feature modules should be top-level `runtime/*.py` unless their
packaging is deliberately added: current assembly does not copy nested modules.

## Validation and handoff

Select checks using [agent checks](docs/agent-checks.md). Run appropriate fast
checks during iteration, then the required integration checks for the finished
change. Do not repeat passing checks without new changes, failures or unresolved
concerns. Existing required CI checks still apply.

Coordinate one combined APK/device validation for a finished batch instead of
giving every worker an independent full build. Do not run simultaneous stateful
device suites against one device. Skipped or unavailable checks remain unverified.
Cache reuse must validate input identity and completeness; a clean build remains
available to verify behavior when build caching changes.

Workers report changed files, acceptance evidence, actual checks/skips, remaining
dependencies and blockers. Surface scope growth into engine/host changes or save
migrations promptly. The coordinator reviews the combined diff, resolves shared
contracts, records the integrated source/artifact, and reports the outcome.
