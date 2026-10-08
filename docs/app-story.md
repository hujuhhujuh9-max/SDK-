# Native story in the optional app starter

Build with `build_android.py --startup-template app` to select the app starter.
The checked-in configuration selects `story`; the normal build still starts
**Before the First Light**. App selection comes from the packaged
`project_config.STARTUP_TEMPLATE`, never from a story save or an Android
environment variable. [The batch plan](app-starter-plan.md) describes ownership
and the shared application contract.

[game/app_starter.rpy](../game/app_starter.rpy) adds **The Lighthouse Note**, a
short callable native story. It uses Ren'Py dialogue, an existing Flet choice
panel and a plain string return value. It leaves the observatory's labels,
statement identities and source unchanged. In app mode only, the existing
`config.label_overrides` mechanism selects `app_recipe_entry`.

## Native flow and the handoff

`app_recipe_entry` displays the native integration screen, installs the command
polling overlay and waits at `app_recipe_home`. The Flet home queues a command
through the shared `app_session.session` mailbox. A timer on Ren'Py's thread
consumes it once. Flet never calls Ren'Py flow, rendering or save APIs.

- **Start** acknowledges the accepted command, captures its fresh session
  revision and jumps to `app_recipe_start`, which calls `app_recipe_story`.
  Replacing live or saved progress requires the UI's explicit confirmation.
  Native checkpoint discovery repeats before Start; an early click cannot
  silently replace a checkpoint discovered later. A confirmed replacement
  clears the former nested call stack using `renpy.set_return_stack([])`.
- **Return** acknowledges navigation to app home and preserves the native
  interaction. It does not save, jump, close an interlude or consume a choice.
  The app-only choice-poll wrapper also holds results while the command is
  pending and after the session becomes hidden, before the Android surface
  change finishes.
- **Continue story** acknowledges a live Resume and reveals the same native
  interaction. A retained live interaction is not a claim of disk persistence.
- **Resume saved story** loads a confirmed active native bookmark. Successful
  `renpy.load(...)` never returns. The after-load callback acknowledges the
  exact pending Resume command, publishes a fresh revision and rejects stale
  controls. A declined signature prompt or load failure releases the command
  without announcing successful navigation.
- **Completion** records the label's plain result, then waits until the shared
  mailbox and save/preference gates permit publication. The result is published
  once and app home opens. The application is neither quit nor restarted.
  A confirmed active manual bookmark remains available for saved Resume,
  including immediately after completion. Loading a completed background
  snapshot releases its waiting native screen without publishing a second
  completion result.

The example returns either `You kept a note from the lighthouse.` or
`You shared the lighthouse note.`. A new native story can use normal Ren'Py
labels, `call` and `return` with a plain result. Keep the command overlay,
revision guard, after-load callbacks, save adapter and waiting interlude labels
when adapting the recipe. Native timers and flow belong to Ren'Py's thread.

## Saves and recovery

The app recipe's manual slot is `app-recipe-quick`. An available filename alone
does not enable saved Resume: `renpy.can_load(...)` must succeed and native slot
metadata must contain a validated, version 1, active `app_story` record.
The save contains the real native script position and the existing
`renfletpy.SaveState` interlude snapshot; Python does not reconstruct script flow.

The sole additional saved model is the native default `_app_recipe_state`:

```python
{"version": 1, "story_id": "app-recipe", "phase": "active", "value": None}
```

`phase` is `ready`, `active` or `completed`. Only `completed` contains a nonempty
string result. The save metadata includes a detached copy of this same record.
The native controller, pending command ID, session revision, listeners and
renderer references remain in the runtime module, outside the native saved
store. Application records and routes are also outside story snapshots.
Unsupported native recipe state returns safely to the native home wait with
fresh controls; it does not rewrite observatory saves or application data.

The pinned SDK's Android `path_to_saves(...)` ignores `config.save_directory`.
Changing that name therefore does not isolate `_reload-1`. The documented
`config.savedir` override runs in `python early`, before persistent data, save
locations and automatic recovery initialize. App mode derives the SDK-selected
writable save root and uses its `app-starter` child directory. This isolates
manual saves, autosaves, native persistent preferences and the native Android
background slot `_reload-1`. Story mode does not override its save directory.

Native recovery first uses the existing interlude restoration, then restores
the recipe's phase and a fresh session revision. Automatic recovery preserves
an explicit app/records destination. Explicit saved Resume has its own guarded
navigation acknowledgement. Quick bookmarks remain deliberate recovery points
after completion; Return alone creates none.

Two platform details matter for authoring and probes:

- The SDK's `--savedir` command-line argument overrides `config.savedir` after
  the early block. A check that always supplies it cannot prove automatic
  app/default namespace selection.
- Desktop Ren'Py also scans a writable project-local `game/saves` directory.
  Use separately staged app and story projects, as the build does, rather than
  sharing writable projects when testing both modes. Android does not add that
  desktop location.

`SDK_RUNNER_NATIVE_SAVE_DIR` reports the actual native directory in both modes;
`SDK_RUNNER_APP_SAVE_DIR` reports app namespace selection. Native phase markers
include action, revision and process ID for lifecycle checks. They are
validation logs, not application navigation or a second save system.

## Validation

Run the focused native boundary tests from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_app_story.py' -v
```

The finished batch also runs the default native story checks and the app-mode
native probe using the pinned SDK:

```sh
.android-build/venv/bin/python scripts/check_native_story.py --startup-template story
.android-build/venv/bin/python scripts/check_native_story.py --startup-template app
```

Native checks cover Start, live Return/Resume with an already selected result,
manual save/load, cold saved Resume, background recovery in a new process,
fresh revisions, completed-state recovery and unchanged default save files.
The Android validation must prove both modes on their identified artifacts,
including a real same-device app/default save-isolation scenario. Linux native
evidence and an Android path-resolver fixture do not replace that device proof.
