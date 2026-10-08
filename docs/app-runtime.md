# Optional app runtime and story handoff

Assignment A owns shared routing and the bridge, based on main `c8d4dd1`.
The story-first `/` entry point stays the default. Open `/app` explicitly to
use the optional app home, `/app/story`, `/app/records`, or `/app/settings`.
Query strings are retained. Application records remain outside story saves.

File ownership for this task: A owns `runtime/sdk_bridge.py`,
`runtime/story_ui.py`, `runtime/app_ui.py`, `tests/test_sdk_bridge.py`,
`tests/test_app_runtime_flet.py`, `.github/workflows/check-runtime.yml`,
`README.md`, and this document. The mailbox
test worker owns `tests/test_story_mailbox.py` in a separate worktree. The
review worker is read-only. No SDK, Android host, or native story input changes
belong to this task.

## Native command contract

Flet calls `request_story(action, story_id="before-the-first-light",
return_route="/app")`. Actions are `start`, `resume`, and `return`. An accepted
call returns a positive, process-local request ID; a rejected call returns
`None`. The bridge allows one pending story command, including after it has
been taken. Save, reading, restart, and quit requests cannot overlap it.

Ren'Py's thread calls `take_story_command()` from its own timer/interaction.
It returns a plain dictionary exactly once:

```python
{
    "request_id": 1,
    "session_id": 1,
    "action": "start",
    "story_id": "before-the-first-light",
    "return_route": "/app",
}
```

The native owner performs the operation and calls
`confirm_story_command(request_id, success=True, message="...")`.
Failed operations use `success=False`. Confirmations for an untaken command,
an old request, or an already completed request return `False`. Only a matching
confirmation releases the pending command. Successful start/resume confirms
`active`; successful return confirms `suspended`. Failure keeps the preceding
confirmed state and reports the supplied message. Submission never invents a
successful native state.

`story_status()` returns a detached plain dictionary containing `story_id`,
`session_id`, `state`, `return_route`, `busy`, `request_id`, `action`,
`message`, and `result`. Results must be JSON data. Native story completion
uses `finish_story(session_id, outcome="completed", result=..., message="...")`;
`cancelled` is also supported. A session ID survives resume/return commands;
a new start or native recovery gives it a new ID. Terminal results are
accepted once for the current session and cannot complete a newer session.

After native save restoration/recovery, call
`restore_story_status(story_id, state="suspended", message="...",
return_route="/app")` with the native truth. This invalidates pending commands and old session results,
returns a fresh session ID, and refreshes status without navigating. Pass
`None` to clear the optional session. These runtime IDs and callbacks must
never be serialized into story saves. The existing `resume_story()` callback
still serves legacy quick-load recovery and respects explicit app links.

The native story worker supplies the consumer of these commands. Consume before
dispatching native flow, and keep the request ID through any jump/load that does
not return. Confirm from the corresponding native entry/after-load hook. Explicit
app-command loads confirm their pending ID; `restore_story_status()` is for
recovery outside that command, since it deliberately invalidates pending IDs. Add
`story_status()["busy"]` to native story-choice completion gating while commands
are pending, and publish recovery truth before processing another command.
A provides the mailbox and UI boundary; Flet callbacks never call Ren'Py
flow/save APIs. This A-only branch does not yet execute native Start/Resume/Return.

## Navigation and lifecycle

The app story screen offers Start or Resume from confirmed state. A successful
command may navigate only when its originating page, connection, route, and
navigation revision still match. Reading/theme refreshes on the same route
do not count as navigation. If the user has opened records or settings in the
meantime, the result updates status without replacing that screen. An old
callback cannot update or navigate a disconnected or replaced page. Reconnect
reads the current confirmed status and retains the selected route.

Back from an app child returns to app home; app home stays at app home. Back
from an active optional story requests native return to its saved app route.
The story menu also offers Return to app. Legacy story/diagnostics Back remains
available. Application data and pending story choices survive app navigation.

## Checks

Run the mailbox tests and routing/shared-refresh regressions, then the full
host suite, pinned Flet protocol/lifetime checks, and native story probe. APK
and device evidence belongs to the combined native/UI batch; unavailable
prerequisites must be reported as unverified.

Local validation on 2026-10-08:

- Complete host suite with pinned Flet: 320 passed, zero skips, including
  38 mailbox tests, 52 routing tests, and six new real Flet app scenarios.
- Real Flet lifetime/handshake/shutdown and socket stress: 20 lifetime cases,
  500 events over five backend cycles, zero idle messages; existing story,
  save/load, history, reading and restored-progress protocol scenarios passed.
- Native Ren'Py/Xvfb regression: 68 checks across 12 processes, including
  quick saves, restored choices, reading preferences, tactics and mobile recovery.
- Form/list: 45 checks passed. Capability lifetime: 20 visits retain the same
  14 page-owned services. Python compilation and whitespace checks passed.
- APK assembly, Flutter analysis/tests, and Android device execution were not
  run here: Android SDK/NDK, `javac`, `adb`, and an emulator are unavailable.
  New native Start/Resume/Return execution remains a native-worker integration
  dependency and has only been confirmed through fixture handlers so far.

Receipts are in `.android-build/full-host-tests.log`,
`.android-build/runtime-final.log`, `.android-build/native-story-check/results.json`,
`.android-build/form-list-final.log`, and `.android-build/service-lifetime-final.log`.
