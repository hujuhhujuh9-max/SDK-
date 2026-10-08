# C: optional application screens

C owns the screen layer on `feature/application-screens`, based on main
`c8d4dd1f2be678756d96bac228070b50b0539d14`.

Owned files: `runtime/application_screens.py`, the optional Return-to-app controls
in `runtime/story_ui.py`, the configurable Back label in `runtime/form_list.py`,
`tests/test_application_screens*.py`, `scripts/check_application_screens.py`,
`.github/workflows/check-application-screens.yml`, and this guide. Shared routing,
native story sessions, host, SDK pins and integration acceptance remain with their
assigned owners.

The screens return unmounted Flet views. The caller supplies navigation,
a current plain status snapshot, a synchronous command submission callback and
an explicit refresh callback.
Commands carry the displayed revision; both the UI and native command owner
must reject stale or busy requests. Application records retain the existing
preferences store and stay outside story bookmarks.

This is a C screen handoff. The integration owner connects the optional routes
and status/command adapter to the native story-session contract before combined
APK/device validation. The current story-first entry point stays the default.

## Screen entry points

Import `application_screens` from a packaged Android runtime, or
`runtime.application_screens` in host code. Every new runtime module is top-level
and is copied by the existing assembly.

| Optional route | Builder | Behavior |
| --- | --- | --- |
| `/app` | `app_home_view` | Records, Start, Resume, story controls and the latest result |
| `/app/records` | `await create_app_records_view` | Existing form/list storage and Return to app |
| `/app/story` | `app_story_view` | Resume, start again, native return and cancel |
| `/app/story/start` | `app_confirmation_view(action="start")` | Confirm replacing current or resumable progress |
| `/app/story/cancel` | `app_confirmation_view(action="cancel")` | Confirm cancelling the active session |
| `/app/story/result` | `app_result_view` | Completed, cancelled, failed or absent result |

The first, third and confirmation builders take
`(page, navigate, read_status, request_story, *, refresh_status, ...)`.
`app_result_view(navigate, result, ...)` reads only its supplied result.
`create_app_records_view(page, navigate, ...)` delegates to
`create_form_list_view`, using the same fields and storage key by default.
Its Return button uses the new optional `back_label` argument; existing records
callers still get **Back**. Records load/save recovery remains in the existing
recipe and does not create a second preferences service or collection.

Views use the existing story colors, scroll on small screens, wrap button rows
and accept `large_text=True`. The home accepts application and story titles.
The optional `route` argument preserves an incoming route including its query;
internal links use the route constants above. The integration caller maps those
links if it chooses another route namespace.

## Status and callback adapter

This is the screen adapter contract, not a newly implemented native-session API.
The integration owner maps the native worker's state and commands to it.
`read_status()` synchronously returns a current in-memory mapping with these
required fields:

| Field | Meaning |
| --- | --- |
| `revision` | Opaque native status generation; change it when a session, bookmark, eligibility or outcome changes |
| `loading` | Native status/bookmark discovery is pending |
| `busy` | A native command is pending or another operation prevents story commands |
| `active` | A live optional story session requires native return/cancel handling |
| `resume_available` | Native resume is currently permitted for this story |

Optional fields are `message`, `error`, `resume_reason` and `result`. Strings are
user-facing text. An unavailable resume button is disabled and displays
`resume_reason`, or **No story bookmark is available.** Initial loading and busy
states display a progress ring and block all story mutations. Records remain
accessible from the home.

`request_story(action, revision)` is a synchronous queue submission returning
exactly `True` when accepted. Actions are `start`, `resume`, `return` and `cancel`.
The native owner must atomically compare the revision, check current eligibility
and busy/lifecycle guards, and execute commands on Ren'Py's story thread. Keep
generations distinct across story loads/restarts so an old view cannot authorize
a replacement session. No Flet callback executes Ren'Py flow or saves directly.

Buttons reread the snapshot before submission, reject outdated generations, and
lock their view after one accepted request. Start requests require confirmation
when active or resumable progress exists. Cancel always requires confirmation.
**Keep current story** only navigates back to the controls. Acceptance displays
pending feedback and does not navigate, report completion or consume a result.
The native owner publishes the actual outcome; the integration owner then
refreshes the view and changes presentation/routes when appropriate. Preserve
explicit app/records navigation when native recovery or an older result arrives.

Rejected submissions, thrown queue errors and outdated events keep commands
locked and offer **Reload story status**. A published native failure can provide
an `error` plus current eligibility for a safe retry. The UI does not expose raw
exception text. `refresh_status()` may be synchronous or asynchronous; it must
refresh native status as necessary and explicitly rebuild the current view on
Flet's loop. Flet suppresses a repeated `route_change` to the same route, so
`page.push_route(page.route)` alone cannot implement Reload. Duplicate Reload
events are guarded; a thrown refresh error leaves Reload available.

The builders and records wrapper do not install page route/lifecycle handlers,
mount views, change native presentation, subscribe to story events or store
their controls in story bookmarks. The integration owner retains those jobs,
including route/task revision guards during awaited records loading and page
disconnect/close.

## Return controls and results

Existing story builders take opt-in keyword callbacks:

```python
story_ui.menu_view(
    navigate, quit_runner, save_status, request_save,
    on_return_to_app=return_handler,
)
story_ui.dialogue_controls(
    navigate, dialogue,
    on_return_to_app=return_handler,
    return_to_app_busy=story_status["busy"],
)
```

`return_handler(event)` can be synchronous or asynchronous. It submits the native
return request, with current busy/revision guards, through the integration
adapter. Busy interludes disable star/choice input as well as Return to app and
guard even events dispatched against disabled controls. Menu controls also
respect `save_status["busy"]`; the caller combines
story/save/preference busy states there. Native scenes and the tactics board use
the shared menu; their SDL controls remain native-worker work. With no callback,
existing menu/interlude controls are unchanged.

An example plain result is:

```json
{
  "status": "completed",
  "story_title": "Before the First Light",
  "summary": "The morning is yours.",
  "values": {"Memory": "Stars", "Score": 0}
}
```

`status` is `completed`, `cancelled` or `failed`; the other fields are optional.
`values` maps display labels to plain scalar results. Zero and false values are
displayed. A missing result has its own empty state. Result views offer Return
to app and records navigation and perform no persistence or acknowledgement.
Application records keep the existing `sdk.runner.application.records` key,
independent of these results and native story bookmarks.

## Verification and remaining integration

Run C's prepared-source gate with Python 3.12 and the repository requirements:

```sh
.android-build/venv/bin/python scripts/check_application_screens.py
```

An existing patched Flet directory can be reused:

```sh
.android-build/venv/bin/python scripts/check_application_screens.py \
  --flet-root .android-build/runtime-inspection/flet
```

The gate fails on skipped tests or missing Flet/dependencies. The dedicated
workflow runs it on C branch pushes and relevant main pull requests. The 21
tests use real pinned controls, event dispatch, encoded patches, preferences
method calls, navigation method replies and Unix-socket client events. They
exercise all screen states, confirmations, duplicate/stale events, rejected
requests, refresh recovery, Return-to-app/resume/completion, Unicode records,
read-only results and records reentry. They also cover the optional menu/interlude
buttons while preserving their default behavior.

Native story outcomes and preferences replies are supplied by test fixtures.
These checks establish the C screen contract and Flet transport behavior; they
do not establish native-session implementation, Android rendering or save/load
on a device. The integration owner still needs to connect the native status and
command adapter, mount the optional routes, apply native/Flet presentation and
Back policy, and run one fresh combined APK/device validation. C does not modify
`sdk_bridge.py`, native story labels, host ownership, SDK pins, the 19-extension
catalog, camera removal or rollback removal.

Local C validation on 2026-10-08, using Python 3.12.14 and pinned, patched
Flet 1.0.3:

| Check | Actual result |
| --- | --- |
| Prepared-Flet full unittest suite | 274 passed, zero skips |
| `check_application_screens.py --flet-root .android-build/runtime-inspection/flet` | 21 passed, zero skips; includes four Unix-socket cases |
| `check_runtime.py` | 19 extension imports; 20 lifetime tests; clean startup/shutdown; 500 events over five backend cycles; existing story/result/save/load protocol passed |
| `check_service_lifetime.py .android-build/runtime-inspection/flet` | Same 14 services retained through 20 navigation visits and collection |
| actionlint 1.7.11 on the new workflow | Passed |
| Python compilation and `git diff --check` | Passed |

The full suite used
`PYTHONPATH=.android-build/runtime-inspection/flet/sdk/python/packages/flet/src`.
Local logs are in ignored `.android-build/application-screens-*-check.log` and
`.android-build/application-screens-host-tests.log`; the existing protocol
receipt is `.android-build/runtime-check/protocol.json`. No new native probe,
APK build or Android device run was performed for the C handoff.
