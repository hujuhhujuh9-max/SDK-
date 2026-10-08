# Next batch: optional app starter

Planning baseline: `main` at `c8d4dd1f2be678756d96bac228070b50b0539d14`.
The post-merge build and actual Android 36, 1080×1920/420 dpi run passed:
[build 37708311922](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37708311922),
[device 37709257597](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37709257597).
The device APK SHA256 is
`e992bac53bdf21f8ac36acd6232b7a55c58726705298a3284cf50af35ee5bad7`.

This is the implementation contract for the next batch. A–D have delivered
their owned changes; E integrates them and independently validates the result.
Current evidence and remaining gates are recorded in
[app-starter acceptance](app-starter-acceptance.md).

## Goal and observable result

Provide an explicitly selected app-first starter that opens an app home,
reuses the existing persistent records screen, and can start, resume and return
from one short native story. Completion displays a plain result on app home.
The default build continues to open **Before the First Light**.

Use an additive short story recipe rather than extracting or renaming the
existing observatory story. Reuse existing Flet APIs, records persistence,
native saves, build caching and checks. Ren'Py/SDL still owns startup, native
flow and the single Python interpreter.

## Work packets: A–D implement, E validates

Each implementation packet is sized for roughly 90–150 minutes of code,
focused tests and handoff: about 6–10 agent-hours total, excluding E's
integration and validation. These are effort estimates, not completion deadlines.
E coordinates the contracts and judges the finished behavior independently;
E is not a fifth production-feature implementer.

| Owner | Deliverable | Exclusive file ownership |
| --- | --- | --- |
| A — shared app runtime (`next_validation`) | Implement session commands/status, single consumption and revision guards; app routes, contextual Back, recovery and reconnect lifecycle | `runtime/sdk_bridge.py`, new `runtime/app_session.py`, new `tests/test_app_session.py`, `tests/test_sdk_bridge.py`, `tests/test_shared_refresh.py`, new `docs/app-session.md` |
| B — native story (`next_native`) | Implement the callable story, native-thread handlers, live return/resume, completion and isolated native checkpoints/recovery | New `game/app_starter.rpy`, new `runtime/app_story.py` only if needed, new `tests/test_app_story.py`, new `docs/app-story.md` |
| C — application UI (`next_ui`) | Implement home and native status controls; reuse records; handle busy/loading/errors/results and conditional Return control in the story menu | New `runtime/app_home.py`, `runtime/story_ui.py`, new `tests/test_app_home_flet.py`, new `docs/app-home.md` |
| D — startup/build/CI (`next_build`) | Implement explicit selection, identical packaged configuration, variant identity and mode-aware CI gates | `build_android.py`, new `runtime/project_config.py`, `scripts/check_apk.py`, `.github/workflows/build-android.yml`, `.github/workflows/check-android.yml`, `.github/workflows/check-runtime.yml`, `.github/workflows/check-form-list.yml`, `.github/workflows/integration-abc.yml`, new `tests/test_startup_template.py`, `tests/test_apk_packaging.py`, `docs/build-environment.md` |
| E — orchestrator and independent validator (`/root`) | Freeze contracts and ownership, integrate/review A–D, author independent acceptance fixtures, validate both modes, reject incomplete evidence and return failures to their owners | `scripts/check_native_story.py`, `scripts/native_story_driver.py`, new `scripts/check_app_starter.py`, new `scripts/app_starter_device_checks.py`, `scripts/device_smoke.py`, `tests/test_device_smoke.py`, new `tests/test_app_starter_protocol.py`, new `tests/test_app_starter_integration.py`, new `tests/test_app_starter_device_checks.py` if needed, new `docs/app-starter-acceptance.md`, `README.md`, `docs/validation.md`, this plan |

Only A writes shared production routing/mailbox code. E approves ownership
changes before another worker edits shared files. No Android-host, SDK or Dart
change is currently planned. Requests for another file go to E before editing.
The records implementation and observatory script are outside the planned edits.

## Shared contracts

These interfaces are implemented by the four packets. Commands additionally
carry a unique `command_id`; status includes `showing_story` and event details
used to acknowledge navigation without replacing a newer route.

### Startup and artifacts

- Build selection: `build_android.py --startup-template story|app`; default `story`.
- `runtime/project_config.py` has a checked-in `STARTUP_TEMPLATE = "story"`.
  App assembly overrides the generated copy, identically in the native compile
  project and packaged Python bundle. Android runtime does not need an environment
  variable. The template selection is never restored from a story snapshot.
- App mode enables the additive native entry using the existing
  `config.label_overrides["start"]` mechanism. Story mode leaves the existing
  entry and save identities intact.
- Package inventories, build receipts and artifact names record the selected mode.
  Equal Git SHAs do not prove equal modes; device checks require both source and
  expected mode agreement before installation. Both modes keep the same Flutter
  AAR input identity and completeness verification.

### Routes and records

- In app mode, the home is `/app`, records are `/app/records`, and contextual
  Back from records returns home. Existing story, menu and diagnostics routes
  retain their current behavior. App startup selection is explicit.
- Reuse `create_form_list_view` and the existing records key/service/store.
  Story saves never include application records or the current app route.
- Preserve query-only drafts, Reload recovery for unconfirmed writes, mounting
  cancellation and disconnect/reconnect guards. Recovery must respect explicit
  app and records links instead of always forcing the story route.

### One native story

```text
Command: {story_id: "app-recipe", revision, action: start|resume|return}
Status:  {story_id, revision, phase: ready|active|completed,
          busy, resume_available, resume_kind: live|saved|unavailable,
          message, result}
Result:  {story_id, outcome: completed, value: plain story result}
```

- Flet submits plain commands; Ren'Py's thread performs native flow and save/load.
  One owner accepts each command once. Duplicate, stale and conflicting commands
  are rejected; failure releases busy controls and publishes a useful message.
- Start begins the one story at the native home wait. Replacing recoverable
  progress requires explicit UI confirmation; cancellation leaves it unchanged.
- Return opens app home while preserving the live native interaction and pending
  choice. Return alone does not claim that a checkpoint was saved to disk.
- Resume distinguishes a retained live interaction from a confirmed native saved
  checkpoint. Native quick/background saves provide durable recovery; no Python
  copy reconstructs a script position. Keep native save confirmation visible.
- Completion returns plain data to app home without restarting or quitting the
  whole application. A late result cannot replace a newer route or session.
- Live callbacks, listeners, route state and revision counters stay out of native
  snapshots. Restoration creates fresh revisions and preserves existing pending
  command/result gating.

## Order of work

1. E freezes the names above with A–D. B and D first
   verify optional entry and save isolation in the pinned SDK, especially Android
   save paths and `_reload-1`. A distinct manual slot alone does not prove recovery
   isolation. Do not migrate existing demo saves or assume `save_directory` works
   differently on Android without evidence.
2. A implements the shared contract and routes. B implements the native story
   and recovery. C works against the agreed plain fixture. D implements startup
   selection and artifact identity. E authors independent acceptance cases.
3. E integrates and reviews all four deliverables. A owns fixes to routes and
   shared dispatch; B, C and D fix failures in their own production code.
4. Run appropriate fast checks, then the full prepared-Flet suite without skips,
   real protocol/lifetime checks and native story checks. Build both modes from
   the same integrated revision, reusing the verified AAR where valid.
5. Orchestrator serializes default-regression and app-starter Android scenarios
   against explicitly identified artifacts. Use one coordinated validation batch;
   workers do not each launch full builds or compete for an emulator. Existing
   default regression and new starter receipts must both be present.

Each implementation worker uses a separate main-derived worktree and writable
`.android-build` cache. Source compatibility and artifact mode checks precede
reuse. CI needs a batch trigger beyond the old integration branch, and required
device receipts must fail on deferral or missing evidence for the new batch.

If save isolation or optional entry requires an SDK/host redesign or unsafe
default-save migration, stop that expansion and re-scope with the orchestrator.
The bounded fallback is a native save-slot browser behind Flet controls.

## Acceptance

- Default startup, native story, menus, choices, manual/background saves and
  recovery still work. SDK pins, all 19 paired extensions and notices are retained;
  camera stays disabled and player rollback stays removed.
- Explicit app mode opens home; Records opens and returns correctly. New records
  survive story save/load, replay, warm navigation and cold recovery.
- Start is consumed once; Return/Resume preserve dialogue and pending interludes;
  completion produces one result without quitting. Native errors release controls.
- Old revisions, repeated clicks and delayed results cannot complete a new session
  or hijack a route. Pending save/load continues to gate story completion.
- Explicit cold app links, background/resume and reconnect retain the intended
  destination. Disconnect/shutdown leaves no subscriptions or resurrected callbacks.
- Real pinned-Flet cases run without skips. Artifact receipts record source SHA,
  startup mode, SHA256/ABI and Android profile; session/recovery receipts include
  fresh revisions and process identifiers. Unavailable checks remain unverified.

The next UI-only follow-up can add editor/table/color/loading recipes using the
already packaged extensions. It is outside this starter batch.
