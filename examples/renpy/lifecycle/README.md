# Callable native story lifecycle

**The Last Lantern** is an optional native story and a small native app host.
Start opens a new story, Return hands control back to the caller, Resume continues
the live story, and Finish returns its completion result. **Load checkpoint** is
a separate operation that deliberately restores an older native timeline.

These files stay outside the runner's `game/` directory. The default
**Before the First Light** demo, shared Flet routes and Android package are
unchanged. Do not copy this host's `start` over the demo.

| File | Purpose |
| --- | --- |
| [game/story.rpy](game/story.rpy) | Callable story, native screen, plain continuation and checkpoint operations |
| [game/profile.rpy](game/profile.rpy) | Early, isolated save-directory selection, including Android |
| [game/host.rpy](game/host.rpy) | Standalone host demonstrating Start, Resume, Return, Load and completion |
| [app/host.rpy](app/host.rpy) | Alternative native host consuming A's confirmed app mailbox |
| [app/native_story_mailbox.py](app/native_story_mailbox.py) | Runtime-only command/session correlation, outside native snapshots |

## Run the recipe

From the repository root, with the prepared SDK and a desktop display:

```sh
python3 prepare.py setup renpy
mkdir -p .android-build/native-lifecycle-gallery
cp -R examples/renpy/lifecycle/game .android-build/native-lifecycle-gallery/
native_story_sdk="$(python3 -c 'from prepare import BuildInputs; print(BuildInputs(".android-build").sdk_root("renpy"))')"
"$native_story_sdk/renpy.sh" .android-build/native-lifecycle-gallery compile
"$native_story_sdk/renpy.sh" .android-build/native-lifecycle-gallery lint --error-code
"$native_story_sdk/renpy.sh" .android-build/native-lifecycle-gallery run
```

Use Xvfb when no desktop display is available. The standalone host offers
**Start**, **Resume live story**, **Load checkpoint** and **Close recipe**.
Every story phase offers **Return** and **Save checkpoint**. The standalone
host's native `game_menu` key (Escape on desktop) also returns to the caller.
Choose the garden or tower, then **Finish story**.
Resume becomes unavailable when the story completes; Start begins another run.
Start and completion retain the manual checkpoint.

## Call from another native app host

In a separate opt-in project's `game/`, copy `story.rpy` and `profile.rpy`.
Keep that project's own entry point and install the callbacks during init:

```renpy
init 1 python:
    sdk_native_story_install_profile()

default my_story_result = None

label my_app_story_start:
    call sdk_native_story("start")
    $ my_story_result = _return
    # status is "returned" or "completed"; control is back in this caller.
    return

label my_app_story_resume:
    call sdk_native_story("resume")
    $ my_story_result = _return
    return
```

Use ordinary top-level `call`, not `renpy.call_in_new_context`: native saves
capture the outermost context. `_return` is a plain dictionary containing
`story_id`, `run_id`, `status`, `phase` and `result`. On completion, `result` is
`"garden"` or `"tower"`. Return keeps the phase and chosen path in the live
`default sdk_native_story_state`. Resume reads that state and does no save I/O.
It returns `"unavailable"` when there is no returned live story, including after
completion. A second call while the story is already running returns `"busy"`.

`sdk_native_story_status()` and `sdk_native_story_can_resume()` supply confirmed
native status. `sdk_native_story_return()` ends the active native interaction so
the label returns its plain result to the caller; it returns `False` when there
is no active story screen. `sdk_native_story_save_checkpoint()` and
`sdk_native_story_load_checkpoint()` are native-thread operations; the supplied
screens demonstrate `Function(...)` actions. Successful Load transfers control
to the saved interaction, so it does not return normally. Missing or foreign
checkpoints, cancelled loads and normal I/O failures return `False` and publish
`sdk_native_story_message` while keeping live progress.

For a Flet app shell, use the [confirmed native mailbox host](app/README.md).
It consumes A's real Start/Resume/Return queue, confirms after native execution,
guards native input while busy, and publishes fresh status after loads. Keep
native calls and save operations out of Flet callbacks. Mounting app routes
belongs to the app host. The existing Android host sends Back to the shared Flet
menu; an opt-in app shell owns its Back/menu-to-Return mapping. Loading a story
should keep unrelated app navigation on
Flet's loop. Keep records/settings in independent application storage, as in
[Application records](../../../docs/form-list.md), rather than Ren'Py defaults:
a checkpoint restores the native caller context as well as the story.

Completion is delivered once per live or loaded timeline. Loading an older
checkpoint can reach completion again. App side effects should use `run_id` for
idempotence in independent application storage.

## Saves and Android recovery

The manual slot is `sdk-native-lantern-checkpoint`. Identity metadata includes
the `sdk-native-lantern-v1` profile, `lantern` story and schema `1`. Manual and
automatic recovery loads check this identity before loading. Foreign, missing,
corrupt and unsupported metadata stays unavailable and is never deleted by this
recipe. `RENPY_AUTO_LOAD` overrides are checked too.

Android's pinned engine ignores `config.save_directory` and writes background
recovery to the hardcoded `_reload-1` slot. `profile.rpy` therefore selects
`ANDROID_PRIVATE/saves/sdk-native-lantern-v1` explicitly in `python early`,
before the engine's initial persistent-data read. The demo continues to use its
original save directory. Manual saves, autosaves, persistent data and recovery
all stay in the optional profile. A successful load, new Start, Return or
completion consumes only an owned temporary recovery save, retaining the manual
checkpoint. Normal warm background/resume uses the engine's existing cleanup.

On desktop, the engine also writes `game/saves`, even with `--savedir`.
Use a separate project directory. Do not point `--savedir`, `extra_savedirs` or
sync directories at the demo's writable saves. Metadata validation guards loads;
it cannot prevent the engine from overwriting a shared recovery filename.

Only plain continuation data is stored. There are no saved services, threads,
locks, listeners, bridge instances or native renderer objects. The reusable
`story.rpy` alone installs no configuration or callbacks. Save-profile selection
and callback installation are explicit opt-in host steps.

## Verify

```sh
python3 prepare.py setup renpy
python3 scripts/check_native_lifecycle.py
python3 scripts/check_native_story.py
```

The lifecycle verifier compiles/lints a fresh isolated project, exercises the
actual pinned native engine under Xvfb and writes JSON receipts, logs and
screenshots to `.android-build/native-lifecycle-check/`. It covers live
continuation versus an older checkpoint, Return at each phase, caller completion,
first-interaction saves, fresh-process mobile recovery, profile guards and
unchanged demo save archives. The Android directory branch runs under a native
Linux probe; mobile recovery uses the real engine's `mobile_save` and auto-load.
These checks do not establish APK/device behavior. The app host must include the
recipe in its fresh integrated APK before Android device acceptance.

See [the lifecycle handoff](../../../docs/native-story-lifecycle.md) for the
ownership contract, evidence and remaining integration scope.
