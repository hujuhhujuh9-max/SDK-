# Optional application session and routing

The app starter keeps one native story in the existing interpreter. Its mailbox
is `runtime/app_session.py`; `runtime/sdk_bridge.py` supplies Flet routing and the
shared save/reading operation boundary. Neither module calls Ren'Py flow or save
APIs on Flet's loop. The native recipe executes those operations on its own thread.

`project_config.STARTUP_TEMPLATE == "app"` enables `/app` and `/app/records`.
The default `story` selection preserves the existing sample and routes. A missing
configuration module also defaults to story mode during independent development.
App startup opens home; an explicit records link opens records. Raw root links
cannot resume a returned story before native acknowledgement.

## Mailbox contract

Import `session` from `app_session` in a packaged runtime, or from
`runtime.app_session` in repository code.

| Method | Behavior |
| --- | --- |
| `status()` | A detached plain snapshot: `app_mode`, fixed `story_id`, fresh `revision`, `phase`, `busy`, `resume_available`, `resume_kind`, `showing_story`, `message`, `result`, and event metadata |
| `request(action, revision, replace=False)` | Accept Start, Resume or Return against the current revision once; reject stale or competing work. `replace` is a keyword and must be true to replace known recoverable progress |
| `take_request()` | Native-thread consumption of one command; returns `story_id`, `revision`, `action`, `command_id`, `replace`. Consumption keeps the mailbox busy until acknowledgement |
| `finish(command_id, success=True, message=None)` | Acknowledge only that taken command. Failure releases its controls and preserves the previous native session. Successful Start advances the story revision; live Resume/Return retain it |
| `initialize_saved(available)` | Discover native saved progress without cancelling a command submitted before the first native timer |
| `complete(revision, value, saved_available=False)` | Publish one JSON-compatible terminal result for the current native generation, when no save/reading/session operation competes. A plain true bool retains Resume only when native code confirms an active manual checkpoint |
| `restore(phase="active", resume_kind="live", showing_story=True, result=None, message=None, command_id=None)` | Publish actual native restoration with a fresh revision and invalidate old commands. An explicit saved Resume supplies its taken `command_id`; an invalid id returns `None` without changing the session |
| `subscribe(callback)` | Observe detached status snapshots. Returns an idempotent detach function |

All optional method arguments shown above are keywords. Status phases are
`ready`, `active`, `completed`; resume kinds are `unavailable`, `live`, `saved`.
Active state means a retained live native interaction. Ready or completed state
can advertise a verified saved checkpoint. Completion wraps the plain value as
`{story_id: "app-recipe", outcome: "completed", value: ...}`.

Flet submits through `sdk_bridge.request_app_story(action, revision, replace=...)`.
The bridge and mailbox share one reentrant operation lock, so an app command and
a save or reading write cannot both win a concurrent request. Quit and replay
also wait for current work. Native code must discover the checkpoint before
consuming the first command. If discovery finds an existing checkpoint after an
unconfirmed early Start, `take_request()` rejects the destructive operation and
publishes a confirmation message; the checkpoint remains available.

Return keeps an interaction alive and marks it hidden. It never claims that a
checkpoint was written to disk. Resume can reveal that live interaction, or
request a real native load of verified saved progress. A successful native load
does not return: its after-load handler calls `restore(command_id=...)` for an
explicit Resume. Automatic recovery omits the command id and respects explicit
app and records routes. Revisions, commands, listeners and callbacks live outside
the native snapshot. Existing replay invalidates the discarded app generation
before the native full restart.

## Navigation and lifetime

`app_home_view` receives a synchronous submission callback. The bridge records
the accepted command's id, page lifecycle and navigation revision. A matching
successful native acknowledgement routes Start/Resume to the story and Return
to app home. A newer route, disconnected page, replacement page or restored
generation invalidates that navigation. Status and reading-theme refreshes do
not count as navigation and cannot invalidate their own pending command.

Completion returns an active story route home. It updates status without
hijacking a records or diagnostics route. Native result revisions are separate
from page navigation revisions; loading or starting another story invalidates
old native completions even when the page route stays the same.

Both records entry points reuse `create_form_list_view` and the page's existing
preferences service/store. Query-only links retain the current view/draft;
leaving or switching entry contexts creates a fresh view. Back from
`/app/records` returns to `/app`; the diagnostics records route retains its
original Back behavior. App home Back submits the normal quit request, subject
to the shared operation gate.

Mounting records is guarded against newer routes and disconnects. Reconnect
refreshes current native status and subscribes once; disconnect/shutdown removes
the app and story subscriptions and invalidates queued navigation. A delayed
initial records read cannot resurrect those callbacks. Application records and
the current app route are never stored in a story bookmark.

## Focused checks

Run mailbox, routing and existing native timer regression tests while iterating:

```sh
python3 -m unittest discover -s tests -p test_app_session.py -v
python3 -m unittest discover -s tests -p test_sdk_bridge.py -v
python3 -m unittest discover -s tests -p test_shared_refresh.py -v
```

The finished batch also requires prepared-Flet protocol/lifetime checks, real
native recipe probes, and coordinator-owned source/mode-identified APK/device
validation. Host mailbox tests alone do not establish native save durability,
Android recovery or visual behavior.
