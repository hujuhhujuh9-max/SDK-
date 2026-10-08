# C: optional application screens

C owns the screen layer on `feature/application-screens`, based on main
`c8d4dd1f2be678756d96bac228070b50b0539d14`.

Owned files: `runtime/application_screens.py`, the optional Return-to-app controls
in `runtime/story_ui.py`, the configurable Back label in `runtime/form_list.py`,
`tests/test_application_screens*.py`, `scripts/check_application_screens.py`,
`.github/workflows/check-application-screens.yml`, and this guide. Shared routing,
native story sessions, host, SDK pins and integration acceptance remain with their
assigned owners.

The follow-up also owns `tests/application_screen_mailbox_cases.py` and the
optional `--with-mailbox` gate in the C checker. It aligns the screen adapter with
A's published mailbox at `7bdef8cb6bfb966a7fe00758e2e2cd5e57a58e44` and B's native
recipe at `df11def9d77cd9a7cb6587cea75828d9a1306fbf`. A's shared bridge/routing
implementation and B's native recipe remain read-only inputs to this work.

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
| `revision` | Opaque native status generation; change it when a session, continuation, eligibility or outcome changes |
| `loading` | Native status discovery is pending |
| `busy` | A native command is pending or another operation prevents story commands |
| `active` | A live optional story session requires native return/cancel handling |
| `resume_available` | Native resume is currently permitted for this story |

Optional fields are `message`, `error`, `resume_reason`, `story_title` and `result`.
`start_available` and `cancel_available` can prohibit unsupported operations;
their corresponding `start_reason`/`cancel_reason` explain unavailable controls.
Generic callers retain the original capabilities when these flags are omitted.
Unsupported cancellation is hidden in the controls and blocked on a directly
opened confirmation view. Strings are
user-facing text. An unavailable resume button is disabled and displays
`resume_reason`, or **No story is available to resume.** Initial loading and busy
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
`values` maps display labels to plain JSON results. Zero and false values are
displayed; nested lists and dictionaries use Unicode JSON. A missing result
has its own empty state. Result views offer Return
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
workflow runs it on C branch pushes and relevant main pull requests. The 26
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

## Published mailbox compatibility

`StoryMailboxAdapter(read_mailbox_status, submit_story, *, read_busy=...,
story_title=...)` supplies C's `read_status` and `request_story` callbacks from
A's published bridge. It converts a positive integer request ID into queue
acceptance; `None`, booleans, zero and negative replies are rejected. Its plain
generation fingerprint includes the detached confirmed status and other busy
state, so native recovery, terminal outcomes and pending request changes retire
previously displayed controls.

Inside the integration route owner's scope, use:

```python
origin_revision = navigation_revision
adapter = StoryMailboxAdapter(
    story_status,
    lambda action: submit_story(action, origin_revision=origin_revision),
    read_busy=lambda: (
        save_status()["busy"] or reading_status()["busy"]
        or quitting() or story.restarting()
    ),
    story_title="The Last Lantern",
)

async def refresh_status():
    await render_route(page.route)  # Rebuild even when the route has not changed.

view = app_home_view(
    page, navigate, adapter.read_status, adapter.request_story,
    refresh_status=refresh_status, title="Application home",
)
```

The adapter combines story/save/reading/lifecycle busy state. `active` and
`suspended` permit Resume; completed/cancelled states permit a new Start. A
rejects Start during an unfinished session and has no Cancel command, so its
adapter disables replacement and hides cancellation. Generic screen callbacks
can still support confirmed replacement/cancellation when their native contract
actually provides those commands. The adapter never simulates cancellation by
calling `finish_story` from a Flet event.

Create the adapter for each rebuilt view so its submit callback captures that
view's navigation revision. The title is display text, not a story selector:
when selecting B's recipe, the route owner must submit `story_id="lantern"` for
an idle Start instead of A's current demo fallback. Native submission still
owns the atomic generation/eligibility check. A's published queue checks current
eligibility; the integration owner must add an expected-generation comparison
at submission if native updates can occur between reading status and enqueueing.
The adapter rejects stale displayed events but cannot lock another owner's
native mailbox.

B's Resume continues the current live phase and does not load a checkpoint.
The screen copy therefore does not imply that a saved bookmark makes Resume
available. Explicit native **Load checkpoint** remains B's separate operation.
Completion can pass B's entire plain handoff or its `result` value: C displays
the result and keeps engine identity/run/phase fields out of the product screen.
Other plain dictionaries, scalar values, lists, zero and false are retained;
nested results are displayed as Unicode JSON.

The existing menu accepts A's `on_return` argument as well as C's
`on_return_to_app` keyword, with the Return button before Quit. Supply one
handler. For the shared-file merge, C's `story_ui.py` contains both contracts
and its busy interlude guards; the combined validation checkout uses that
version while retaining A's unmodified bridge and app routing.

The integration owner still replaces A's placeholder view calls in route,
story-status and save/reading refresh paths, adds the C confirmation/result
routes to the app route category, and passes the optional interlude Return
callback. Retain A's origin-tracking submit callback and connection/navigation
guards. Native command consumption, B's early isolated profile and app startup
packaging remain with their existing owners.

In an A/C checkout, the real mailbox gate is:

```sh
python scripts/check_application_screens.py --flet-root /path/to/patched/flet \
  --with-mailbox
```

It requires A's actual APIs and runs eight extra cases in
`tests/application_screen_mailbox_cases.py`; missing bridge support is an error,
never a skip. That file is excluded from ordinary test discovery until the
bridge is present. CI creates an isolated checkout of the exact A commit above,
overlays only C's owned screen/check files, and runs this gate using the verified
patched Flet source. It checks real command consumption, native-thread
confirmation, return/resume identity, failed operations, recovery, records/draft
independence and A's actual runner menu using C's callback signature. Native
execution is still supplied by confirmations; this gate makes no APK/device or
combined native-consumer claim.

Local follow-up validation on 2026-10-08, using Python 3.12.14 and pinned,
patched Flet 1.0.3. The combined checkout retains A's exact bridge/routing
commit above and overlays C's owned files:

| Check | Actual result |
| --- | --- |
| C prepared-Flet full unittest suite | 279 passed, zero skips |
| Combined A/C prepared-Flet full unittest suite | 346 passed, zero skips |
| C `check_application_screens.py --flet-root ...` | 26 passed, zero skips; includes four Unix-socket cases |
| Combined A/C `check_application_screens.py --flet-root ... --with-mailbox` | 34 passed, zero skips; includes eight actual mailbox cases |
| Combined A/C `check_flet_bridge.py` | 19 extension imports; 20 lifetime tests; real handshake/UI patch; clean startup/shutdown |
| Combined A/C `check_runtime.benchmark` and `check_story_protocol` with the same prepared Flet | 500 events over five backend cycles; existing story/result/save/load/reading protocol passed |
| Combined A/C `check_service_lifetime.py` | Same 14 services retained through 20 navigation visits and collection |
| actionlint 1.7.11 on the new workflow | Passed |
| Python compilation and `git diff --check` | Passed |

The full suite used
`PYTHONPATH=.android-build/runtime-inspection/flet/sdk/python/packages/flet/src`.
Local logs are in each checkout's ignored `.android-build/application-screens-*.log`.
The combined protocol receipt is
`.android-build/application-screens-combined-protocol.json`. No new native probe,
APK build or Android device run was performed for the C handoff.
