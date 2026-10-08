# Optional app runtime and native story

The shared runtime mounts the application screens from
[`application_screens.py`](../runtime/application_screens.py) and sends story
commands through [`sdk_bridge.py`](../runtime/sdk_bridge.py). The opt-in
[app project](../examples/app/README.md) connects those commands to **The Last
Lantern** through [`native_app_bridge.py`](../runtime/native_app_bridge.py).
The default **Before the First Light** project keeps its existing entry point.
Opening `/app` mounts the shared app screens; executing the callable story
requires the opt-in host or another project's native consumer.

## Routes and Back

| Route | Screen | Back |
| --- | --- | --- |
| `/app` | Home and confirmed story status | Stay at home |
| `/app/records` | Persistent application records | App home |
| `/app/settings` | Shared reading settings | App home |
| `/app/story` | Story controls | App home |
| `/app/story/start` | Confirm replacement Start | Story controls |
| `/app/story/cancel` | Confirm Cancel | Story controls |
| `/app/story/result` | Confirmed completion or cancellation result | App home |
| `/` | Native story/interlude | Request native Return when an app story is active |

Query strings and the app parent's route are retained. Opening or leaving a
confirmation screen does not submit a command. The optional host maps the
shared menu's Replay and `/restart` to replacement confirmation. Default demo
replay keeps its existing native behavior. Return is also available from the
shared story/menu controls and the native story screen.

A command may navigate only when its originating page, connection generation,
route and navigation revision still match, and its expected confirmed state is
still current. Native Return and completion navigate only from the current
story route. Visiting records, settings or another screen while native work is
pending keeps that screen selected when the work finishes. Status still updates.

Old callbacks cannot submit story choices, preferences or Back from another
route or connection. A cached records view renews its Back callback after query
changes and reconnect while retaining its fields and services. Reading/theme
refreshes on the same route do not invalidate an otherwise current command.
Disconnect releases listeners; reconnect reads current native truth and keeps
the selected route. Recovery publishes state without choosing a screen.

## Mailbox contract

A project first calls `configure_app_story(story_id, story_title,
initializing=True, native_host=True)` on initialization. Publishing recovery
truth clears the loading state. `native_host=True` selects the optional host's
replacement confirmation behavior; it does not start an interpreter or story.

Flet submits plain data:

```python
request_id = request_story(
    "start", "lantern", return_route="/app",
    expected_revision=app_story_status()["revision"],
)
```

Actions are `start`, `resume`, `return` and `cancel`. Acceptance returns a
positive process-local ID; rejection returns `None`. The screen adapter returns
an exact boolean to the view contract. Expected revision and eligibility are
checked atomically. Replacement Start requires `replace=True` and a matching
revision, supplied only by the confirmation screen. One command may be pending,
including after consumption. Save, reading, quit and legacy restart cannot
overlap it. Submission sets busy and a progress message; confirmed state stays
unchanged until the native reply.

Ren'Py's thread consumes `take_story_command()` once. Its dictionary has exactly
these five keys:

```python
{
    "request_id": 1,
    "session_id": 1,
    "action": "start",
    "story_id": "lantern",
    "return_route": "/app",
}
```

After executing the operation, the native consumer calls
`confirm_story_command(request_id, success=True, message="...")`. Successful
Start/Resume confirms `active`, Return confirms `suspended`, and Cancel confirms
`cancelled`. A failure releases busy, keeps preceding confirmed state, and
publishes an error. Untaken, duplicate and stale confirmations return `False`.
Use `navigate=False` when confirming entry after native flow has already ended;
publish its returned/terminal phase immediately without opening the ended scene.

`story_status()` returns detached native state with `story_id`, `session_id`,
`state`, `return_route`, `busy`, `request_id`, `action`, `message` and raw `result`.
`app_story_status()` adds the view's monotonic `revision`, `loading`, aggregate
`busy`, `active`, `resume_available`, `resume_reason`, `error`, title and readable
result mapping. Plain scalar results, including zero and false, are preserved;
nested values are rendered as JSON. Native result payloads accept JSON data only.

`finish_story(session_id, outcome="completed", result=..., message="...")`
accepts a current terminal result once. `cancelled` is also supported. An older
session cannot complete a pending replacement. `return_from_story(session_id)`
publishes a native Return made outside the mailbox. A session survives
Return/Resume; successful Start and native restoration create fresh identities.

After native load or recovery, call
`restore_story_status(story_id, state="active"|"suspended"|"completed"|"cancelled",
result=..., message="...", return_route="/app")` with native truth, or pass
`None` to clear the session. Restoration retires pending requests and old
results, clears loading, and never navigates. Request/session IDs, locks, page
callbacks and services remain in runtime modules and never enter story saves.
The existing `resume_story()` callback remains for legacy demo recovery.

## Opt-in native consumer

The app host uses ordinary top-level Ren'Py `call` statements, with its command
timer and return handler on Ren'Py's thread. Flet runs on its own loop in the
same interpreter. The adapter validates native run UUIDs before publishing a
reply. It handles native Return before the first acknowledgement, concurrent
Resume/Return and replacement/ending races without replaying an older run.

Resume uses the live continuation and does no save I/O. An already restored
active interaction is acknowledged in place. **Load checkpoint** is a separate,
explicit native operation; after-load refreshes runtime identities and preserves
the application's route, records and draft. Cancel unwinds native flow and clears
its live continuation, retaining the independent manual checkpoint. Native Save
refreshes shared bookmark status. Failed reading preference writes release busy
and keep preceding confirmed values.

The app owns the early `sdk-app-lantern-v1` save profile. Native metadata must
match the story profile, schema and exact integer `sdk_app_host=1`. Missing,
boolean or unsupported caller schemas cannot load into this host, and their
archives are retained. The standalone native recipe and default demo use their
own profiles and caller stacks.

## Ownership and packaging handoff

A owns shared routing, mailbox, native adapter, optional app host and integration
regressions. C owns the reusable app views; B owns the callable native story.
The integrated screen and native handoffs are C `0e68fd1` and B `df11def`.
A also owns the narrow `_runner_back_control` binding in `form_list.py` for
renewing cached navigation callbacks. Application storage remains outside
Ren'Py defaults and story bookmarks.

D owns Android host/startup/packaging. The opt-in app is not yet selected by the
current Android builder. D must assemble a fresh separate game from the app
host/profile plus the callable `story.rpy`, select initial `/app`, recreate the
staging directory when switching modes, and include all selected sources in APK
input identity. See [the recipe's packaging handoff](../examples/app/README.md#android-packaging-handoff).
A changed the shared runtime workflow; D's packaging files and SDK pins are
untouched. Build a fresh combined app APK and run its app-specific device suite
before claiming Android acceptance.

## Verification

With the build virtual environment and pinned SDKs prepared:

```sh
.android-build/venv/bin/python scripts/check_runtime.py
.android-build/venv/bin/python scripts/check_native_app_bridge.py
.android-build/venv/bin/python scripts/check_native_story.py
```

The native app check prepares inputs when needed, requires Xvfb, and accepts
`--renpy-sdk`, `--flet-sdk`, `--xvfb` and `--output` overrides. It creates an
isolated writable project/SDK, compiles/lints it, and exercises real native
flow and pinned Flet event/control encoding in one interpreter with separate
threads. Preference service replies are simulated; native scenes, saves, loads
and fresh-process recovery are real. Receipts are written only after success.

Local validation on 2026-10-08:

- Complete pinned-Flet host suite: 380 passed, zero skips.
- Native app bridge: 46 checks across 10 processes, including fresh active,
  returned and completed recovery, explicit checkpoint load, early Return,
  replacement, cancellation and foreign caller metadata.
- Default native story: 72 checks across 14 processes, including the older
  script's bookmark, rendering, quick saves, choices, reading, tactics and
  mobile recovery.
- Real Flet: 500 socket events across five backend cycles with zero idle
  messages; 20 lifetime cases; existing story/save/reading protocol passed.
- Form/list: 45 checks. Capability lifetime: 20 visits retain the same 14
  page-owned services. Python compilation and whitespace checks passed.

Receipts/logs are in `.android-build/host-tests.log`,
`.android-build/native-app-bridge-check/results.json`,
`.android-build/native-story-check/results.json`,
`.android-build/runtime-final.log`, `.android-build/runtime-check/protocol.json`,
`.android-build/form-list-final.log` and `.android-build/service-lifetime-final.log`.
CI publishes native-app and runtime receipts with their source commit.
APK assembly, Flutter analysis/tests and Android device execution remain
unverified here: Android SDK/NDK, `javac`, `adb` and an emulator are unavailable.
