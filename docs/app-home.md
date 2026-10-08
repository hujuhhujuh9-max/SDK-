# Optional app home UI

The app-startup recipe uses a Flet home for **The Lighthouse Note**, one short
native Ren'Py story, and the existing application records screen. It is selected
explicitly by the startup template; the ordinary story-first menu stays intact.
Ren'Py owns story execution, native save/load and the Python interpreter.

`runtime/app_home.py` supplies:

```python
app_home_view(page, navigate, status, request_story,
              *, route="/app", large_text=False)
```

The factory returns a Flet `View`. Construction does not mount it, change a route,
install page/lifecycle callbacks, submit a command or create a service. Call it
on the Flet loop. The routing integration owns `page.views`, native presentation,
Back, asynchronous loading, disconnect/reconnect and status subscriptions.

`navigate(route)` is an asynchronous route callback. The Application records
button requests `/app/records`; the caller mounts `create_form_list_view` there
with Back to `/app`.
Reuse its default storage key and page-owned preferences service/store. This UI
adds no record or bookmark persistence. Query-only links keep the mounted records
draft; leaving and reopening reads current records. See [the form/list recipe](form-list.md)
for validation, cancellation and Reload after unconfirmed writes.

## Native status and commands

Pass the current plain snapshot, or `None` until native status is discovered:

```python
status = {
    "story_id": "app-recipe", "revision": 7, "phase": "ready",
    "busy": False, "resume_available": False, "resume_kind": "unavailable",
    "message": "Ready for a story.", "result": None,
}
```

`phase` is `ready`, `active` or `completed`. `resume_kind` is `live`, `saved` or
`unavailable`. Native code establishes availability; the UI never infers a saved
checkpoint from a previous Flet visit or an application record. Busy status must
include conflicting session, save/load, reading-preference and shutdown operations.

`request_story(action, revision, *, replace=False)` is a synchronous, bounded
mailbox callback returning boolean acceptance. The UI submits `start` or `resume`
using the revision captured when its controls were built. It never calls Ren'Py.
An accepted command disables the home actions and shows **Starting story…** or
**Resuming story…**. Repeated control events are ignored. The UI does not navigate
on submission: the routing/native integration owns acknowledged transitions and
rejects stale commands and late results.

Rebuild the home with each fresh native status to display a native error and
release controls after acknowledgement. A rejected submission releases its local
latch and asks for the latest status. A submission exception leaves home open,
reports the failure and permits retry through the mailbox's revision guards.
Reconnect displays current native status without submitting Start or Resume.

**Resume story** identifies a retained live session or a confirmed native saved
checkpoint through its accompanying explanation. For a live session, the
explanation directs the user to Quick save for a saved place. For a saved
checkpoint, it says **Resume from your saved place.** Start story with live or
saved progress asks for confirmation with **Start new story** and **Cancel**.
Cancel sends no command; confirmation submits `start` with `replace=True`.
A refreshed native snapshot discards the UI confirmation. The mailbox must
reject old controls' captured revisions before replacing newer progress.

Completion displays **Story complete** and the matching native result sentence:

```python
{"story_id": "app-recipe", "outcome": "completed",
 "value": "You shared the lighthouse note."}
```

Only the completed phase and matching story/result identity show this result.
Flet displays the sentence as plain text. Receiving or rendering it does not
start another story, write records or quit the application.

## Conditional story-menu control

The existing `story_ui.menu_view` accepts the optional keyword
`on_return_to_app`. With no callback, its controls and ordinary Resume route are
unchanged. In app mode, supply an asynchronous Flet handler that submits Return
and returns boolean acceptance:

```python
async def return_to_app(event):
    return request_story("return", current_status["revision"])
```

The conditional **Return to app** button uses the combined menu busy guard and
latches an accepted submission until the routing integration refreshes the menu.
It preserves the live interaction; its explanation says to use Quick save for a
saved place. Existing native save confirmation stays visible separately. A rejected
or failed return releases the button. Native acknowledgement determines navigation.

The integration maps native-story Back to the existing menu, records Back to
app home, and app-home Back to the existing quit flow. Return and records loading
must not erase pending native choices or let a late acknowledgement hijack a
new route. These cross-boundary behaviors belong to routing/native acceptance.

## Focused validation

Prepare pinned Flet in this checkout, including the embedding/lifecycle patches,
then run the real UI tests:

```sh
PYTHONPATH=.android-build/runtime-inspection/flet/sdk/python/packages/flet/src \
  .android-build/venv/bin/python -m unittest discover -s tests -p 'test_app_home_flet.py' -v
```

Use the actual prepared source path if it differs. The tests encode real Flet
messages and dispatch client events. They verify route/service neutrality,
loading/busy states, repeated and stale events, replacement cancellation,
live/saved Resume labels, error recovery, plain completion and conditional-menu
behavior. They do not emulate native saves or establish Android rendering.
Missing prepared Flet skips these cases; the integrated gate must run them without
skips before the combined native/APK/device checks.
