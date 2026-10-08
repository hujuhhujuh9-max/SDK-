# Native consumer for the shared app bridge

This alternative host connects **The Last Lantern** to A's actual confirmed
Start/Resume/Return mailbox. Its native launcher submits the same plain commands
as an app UI. The Ren'Py timer consumes them and the ordinary top-level caller
publishes the resulting native truth. Use this host in a separate optional
project, in place of the [standalone host](../game/host.rpy).

The host requires A's `sdk_bridge` mailbox API, reviewed at
`7bdef8cb6bfb966a7fe00758e2e2cd5e57a58e44` in
[PR #9](https://github.com/hujuhhujuh9-max/SDK-/pull/9).
It keeps the selected app presentation and destination under that bridge's
ownership. The default story package and shared bridge have no B edits.

## Project layout

Copy the following into a dedicated project:

```text
optional-project/
  native_story_mailbox.py       # this directory's module
  sdk_bridge.py                # A's shared bridge
  ...                         # the other top-level shared runtime/*.py
  game/
    story.rpy                  # ../game/story.rpy
    profile.rpy                # ../game/profile.rpy, selected early
    host.rpy                   # this directory's alternative host
```

Include all shared runtime Python files from the same A revision. Copy only one
host; each supplies its own `label start`. The ordinary project must also supply
the pinned Flet Python dependencies when running its Flet backend on Android.
Its selected save directory remains the isolated native-story profile described
in [the main recipe](../README.md#saves-and-android-recovery).

The native launcher can exercise the mailbox on Linux without starting Flet.
On Android the supplied host starts the existing shared Flet backend. The
integration owner selects the initial Flet route and connects C's screen adapter.

## Native command contract

An app control submits a command with the explicit story identity:

```python
request_id = sdk_bridge.request_story("start", "lantern", return_route="/app")
# Use "resume" to continue live state, or "return" to yield to the app.
# None means the bridge rejected the request; no native success is implied.
```

A's current screen defaults to `before-the-first-light`; bind it to `lantern`
in the app integration. A command for another story receives a failed native
confirmation. C's revision/confirmation adapter and its cancel policy remain
integration-owned; this native consumer implements B's three requested commands.

| Command | Native execution and confirmation |
| --- | --- |
| Start | The home interaction yields `"start"`; the caller enters the native label. Confirm only after the running scene exists. |
| Resume after Return | The home yields `"resume"`; the native label continues its live phase/path. Confirm when its scene exists. |
| Resume while active | Confirm the already-running interaction without another label call or save reads. A owns restoring its presentation. |
| Return | End the current native interaction, then confirm after the label has returned its `status="returned"` result to its caller. |
| Completion | Publish `finish_story` once for the matching process session, carrying the plain native result and stable `run_id`. |

The native Return button stages the same mailbox before yielding. A Return
initiated by a Flet page retains that page's guarded navigation origin. Native
Return/Escape has no Flet origin; the app host owns its destination policy. The
adapter never forces a route or presentation after a reply, completion or load.

The library's init-time `sdk_native_story_input_allowed` hook guards native
Continue, choices, Finish, Save and Return. Actions check eligibility again when
dispatched, so an older enabled control cannot bypass a pending command or an
app page. The command consumer can still execute its accepted Return while the
bridge is busy. The host refreshes the native interaction when eligibility
changes, without refreshing it on every timer tick.

## Saves, loads and recovery

Shared-menu Save/Load uses the separate `request_save` queue. The native Save
button also publishes checkpoint availability to that menu. Successful explicit
Load transfers control to the saved native interaction, and the after-load hook
publishes its status with fresh process IDs. Live Resume uses neither that queue
nor any native save-reading API.

The adapter instance, pending request IDs, session IDs, thread ownership and
bridge references live in the `native_story_mailbox` Python module. Only the
story's plain continuation and caller result enter native snapshots. A load
invalidates pending requests and old completions, preserves the current bridge
return route/presentation, and leaves external app records/preferences current.
Cold recovery creates fresh process IDs from the restored native truth.

Completed recovery publishes completed status without replaying `finish_story`
or external effects. A's recovery API has no result argument; the saved plain
`sdk_native_story_last_result` remains the caller's completed result. The app
integration can display that plain result without replaying completion. External
effects still need `run_id` idempotence when an older checkpoint completes again.

## Verification

With the prepared Ren'Py SDK, Xvfb and a directory containing A's runtime files:

```sh
python3 scripts/check_native_story_mailbox.py --bridge-runtime /path/to/a/runtime
```

The gate uses the actual bridge and native engine, records the bridge hash,
and rejects missing mailbox APIs. It stages isolated projects, writable SDK
copies and saves. Its receipts separate command execution and fresh-process
mobile recovery from Android APK/device execution. The B workflow tests the
reviewed A revision until that API is present in the integrated runtime.
