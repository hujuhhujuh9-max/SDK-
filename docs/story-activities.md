# Project story activities

A project registers an activity's renderer, initial model, command reducer,
state/result validation and save migrations through `ProjectAPI.register_activity`.
It calls the stable native `renfletpy_activity` label and receives an explicit
`ActivityResult`. Normal SDK story, menu and save navigation render the activity
without changing the SDK's route table or built-in kind list. Panels, star map
and native tactics keep their existing APIs and results.

## Registration and native call

Keep a top-level project Python module, for example `app/survey_activity.py`.
Set `"project_setup": "survey_activity:register"` in `renfletpy.json`. The
native host invokes this synchronous hook during initialization, before any
after-load restoration; Flet shares that same registration in the interpreter.
The hook runs once. A failed hook rolls back its activity registrations, and
registration errors are reported instead of silently selecting a built-in.

```python
from story_activities import ActivityResult, ActivityTransition

def register(api):
    api.register_activity(
        "field_survey", version=2,
        create_state=create_state, renderer=render, reduce=reduce,
        validate_state=validate_state,
        migrations={1: migrate_v1}, validate_result=validate_result,
        title="Field survey", description="Record the instruments before sunrise.",
    )
```

Names use letters, digits, `.`, `_` and `-`, start with a letter, and cannot
reuse `panel`, `star_map` or `tactics`. Repeated registration is an error.
Factories/functions remain in the runtime registry; they are never saved.
Native `init python` registration with `story_activities.register_activity`
is also supported. Register before loading a save that contains that kind.

```renpy
label survey_scene:
    "Before the sunrise, survey the instruments."
    call renfletpy_activity("field_survey") from survey_scene_activity_return
    if _return.status == "completed":
        $ instruments = _return.value["samples"]
        "The observations are ready."
    else:
        "We can come back another morning."
    return
```

Pass an initial plain model as the optional second label argument when needed.
The initial model uses the current schema version. Native saves restore the
existing activity inside `renfletpy_activity.wait`; they do not run its initial
factory again. Retain explicit `from` call labels when editing a project so
native story call/return bookmarks remain stable across compilation.

## Model and commands

`create_state()` returns a dictionary. `reduce(state, name, payload)` receives
detached plain data and returns either a new dictionary or
`ActivityTransition(state, ActivityResult("completed", value))`. Mutating the
private input copy and returning it is allowed. `ActivityResult("cancelled",
value)` is also valid; terminal results cannot be replaced by later taps.

`validate_state(state)` and `validate_result(result)` may return `True`/`None`
for success, `False` for failure, or raise a useful validation error. Validation
receives private copies. Invalid inputs, reducer errors and invalid results keep
the last valid game model; `context.error` exposes a retry message. The native
log records the original exception.

Models/results/payloads contain only finite JSON values: dictionaries with
string keys, lists, strings, integers, finite floats, booleans and null. Tuples,
controls, callbacks, service objects, controllers, locks, cycles and non-finite
numbers are rejected. One payload/model is limited to 1 MiB, 100,000 values and
32 nested levels. This is a gameplay model interface; large media belongs in
assets or files referred to by model values.

The renderer receives `ActivityContext`:

| Member | Ownership and effect |
| --- | --- |
| `state`, `kind`, `result`, `error` | Detached current model and outcome; editing the copy does not edit the saved model. |
| `revision` | Activity lifetime token; new activities and restores issue fresh revisions. |
| `navigate`, `large_text` | Existing SDK navigation callback and reading preference. |
| `command(name, payload=None)` | Queue a plain command for the native reducer; returns whether the mailbox accepted it. |
| `complete(value=None)` | Queue an explicit completed result; native validation decides whether it is valid. |
| `cancel(value=None)` | Queue an explicit cancelled result. |

`renderer(context)` returns a list of Flet controls, synchronously on Flet's
event loop. A successful submission means queued, not yet committed. The native
timer drains commands in order, applies reducers and publishes model updates;
Flet rebuilds from those updates on its own loop. The mailbox has 256 pending
messages and drains at most 256 per native tick. Overflow or a stale/completed
revision returns `False`. Terminal submissions block later input while awaiting
validation. Failed terminal validation releases that block so the user can retry.
The complete activity envelope (schema version, model and optional result) must
fit within 1 MiB of JSON. A model and result cannot each consume that allowance.
Oversized transitions keep the last valid model and let the user retry; an
oversized initial or restored envelope fails before replacing the story.

`Story.start_activity`, `process_activity_commands`, custom `consume` and native
flow run on the same owning thread. Restore checks an established owner before
calling project migrations or validators. Flet only submits plain commands/results.
Reducers are synchronous and should do bounded model work; they must not block
on network services. A Flet task may await a service, then submit a result using
its captured context. Its old revision is rejected if the story was loaded,
replayed or replaced while the work was running.

Completion remains pending while a menu, diagnostics, save/preference request
or app Return owns presentation. The native story consumes the result once after
resuming, adds one native history entry and releases the waiting interaction.
Cancellation follows the same gate. Saving after cancellation records that
outcome; continue an unfinished activity from a save made before cancelling.

## Saves, migrations and reconstruction

The existing story envelope remains version 1 and still accepts old panel,
star-map and tactics saves. A registered activity adds only this plain entry:

```json
{
  "version": 2,
  "state": {"samples": ["telescope"], "draft": "Unfinished note",
            "selected": "spectrograph", "notes": {"telescope": "Mirror checked"}},
  "result": null
}
```

Its `version` is local to the activity. `migrations={1: migrate_v1, 2: migrate_v2}`
maps each old version to one function returning the next version's model. The
SDK copies data before migration, validates the final model/result and validates
the entire story snapshot before replacing live state. Missing registrations,
missing migration steps, future versions and malformed results fail explicitly;
none reset or partially overwrite the live activity. Keep result value schemas
backward compatible or accept older results in `validate_result`.

Manual, named, mobile-background and native autosaves use the existing
`SaveState` adapter. Serialization on the native owner drains queued inputs
before capture; an autosave worker captures the last committed model without
executing reducers off-thread. Pending service work and transient trigger queues
are not part of saves. Autosave completeness therefore means the last
acknowledged model, rather than in-flight work.

On load, the registry supplies a fresh renderer and controls from saved values.
Use stable Flet control keys where useful, but keep drafts, selections and game
progress in the model. A control may own an ephemeral animation controller or
service; stop/dispose it when removed and recreate it when mounted. Background
and resume handling belongs to that control's declared lifecycle. Do not place
live objects in `state` or rely on a running task surviving process loss. Inputs
from controls or tasks that captured an old save revision cannot edit the new
timeline.

## Acceptance evidence

The [field survey](../examples/activities/README.md) exercises draft editing,
selection, halfway save, clean process reopening, completion and cancellation.
`tests/test_story_activities.py` passes all 19 cases with pinned Flet, including
genuine Flet callbacks, detached data, threaded submissions, owner enforcement,
atomic malformed-save rejection and version migration. The existing story,
tactics, bridge and app-story regression suites remain applicable.

`examples/activities/verify_native.py` passed five separately compiled native
Ren'Py processes: normal SDK quick save/load (6 checks), mobile half-save seed
(2), reopen (4), version 1 mobile seed (2), and version 1 → 2 migration (5).
It verifies restored drafts/selections, the real `.save` adapter, menu completion
gating, stale controls, one meaningful completed result and one cancelled result
in the native story/history. Receipts include process IDs and input hashes in
`.android-build/story-activities-check/results.json`.

The native Linux and real Flet checks establish the exercised protocol, model
and save behavior. A fresh integrated APK, Android lifecycle and physical API 35
phone checks are separate integration gates.
