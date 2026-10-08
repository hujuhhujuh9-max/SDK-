# B: native story lifecycle and saves

Base revision: `c8d4dd1f2be678756d96bac228070b50b0539d14` (the reviewed main
after PR #6; use the verification receipt's source SHA for builds).
Implementation branch: `work/native-story-lifecycle`.

The deliverable is one optional callable native story, **The Last Lantern**,
with Start, live Resume, Return and completion. A standalone native host and
copyable authoring instructions demonstrate the contract. It uses the existing
Ren'Py save engine and one active story, with a separate manual Load operation.
The default demo and existing integration remain at their current entry point.

## Ownership and contract

| Owner | Files | Contract |
| --- | --- | --- |
| B coordinator | `examples/renpy/lifecycle/`, `tests/test_native_story_mailbox.py`, existing lifecycle verifier files, this guide, README links, dedicated workflow | Callable native story, isolated profile, native command adapter and authoring |
| Native verification worker | `scripts/check_native_story_mailbox.py`, `scripts/native_story_mailbox_driver.py`, `scripts/native_story_mailbox_probe.rpy`, `tests/test_native_story_mailbox_checks.py` | Actual A mailbox, native recovery and save-isolation receipts |

The verification worker uses a separate main-derived worktree and mutable SDK
installation/cache. SDK pins, component branches, the Android host, registry,
default game, shared bridge and Flet UI have no implementation edits in B.
Native operations execute on the story thread. App controls may queue plain
commands, then consume confirmed native results; app routing belongs to the host.

| Operation | Native entry | Outcome |
| --- | --- | --- |
| Start | `call sdk_native_story("start")` | Fresh run and phase; manual checkpoint retained |
| Resume | `call sdk_native_story("resume")` | Continue returned live phase/data without reading a checkpoint |
| Return | `sdk_native_story_return()` or native **Return** action | Caller receives `status="returned"`; live phase/path retained |
| Complete | Native **Finish story** action | Caller receives `status="completed"` and garden/tower result once |
| Save | `sdk_native_story_save_checkpoint()` | Native archive in the dedicated manual slot |
| Load | `sdk_native_story_load_checkpoint()` | Explicitly restore the saved native timeline; successful load transfers control |

Payload fields are `story_id`, `run_id`, `status`, `phase`, `result`. A missing or
completed continuation yields `unavailable`; a reentrant call yields `busy`.
An earlier loaded timeline may complete again with the same run ID; the app host
owns idempotence for external effects. App records and preferences remain outside
story defaults and snapshots.

The [optional mailbox host](../examples/renpy/lifecycle/app/README.md) supplies
the native consumer for A's reviewed bridge (`7bdef8cb`). Start and returned
Resume confirm only after the actual native scene exists. Active Resume retains
the existing interaction without another label call or save reads. Return
confirms after the caller receives returned native truth; completion is published
once for its matching runtime session. Native actions check pending command,
save/preference and presentation guards again when dispatched.

Runtime IDs, pending commands and the adapter instance live outside native save
data in a Python module. After-load/recovery hooks publish fresh session IDs,
retire stale replies/results and retain the current bridge destination and
presentation. The adapter never forces navigation after a native reply.
The app integration must bind `lantern` explicitly: A's current UI defaults to
the existing demo's identity. Native Return/Escape has no Flet page origin, so
the app owner connects that destination policy and C's screen/result adapter.

## Isolation decision

The engine's Android save path ignores `config.save_directory`, and its mobile
recovery slot is `_reload-1`. The opt-in `profile.rpy` sets an explicit
app-private child directory in `python early`. Regular init Python runs after
the first persistent-data read, so selecting a profile in a regular init helper
would already expose the wrong persistent data. The callback installer validates
the early selection and registers identity metadata, startup load gating and
after-load cleanup only for the optional host.

The profile is `sdk-native-lantern-v1`; the story is `lantern`; the manual slot
is `sdk-native-lantern-checkpoint`; metadata schema is `1`. Automatic/manual
loads reject incompatible identity and malformed metadata. Cleanup unlinks only
an owned recovery slot. Desktop projects must also be separate because the
engine writes `game/saves` in addition to the selected user directory.

This is an opt-in project recipe, not a switch between save locations in a live
demo session. D/app-shell integration should adopt the optional profile before
startup and call the ordinary top-level labels. Sharing the demo's writable save
directories or copying this host's `start` over the demo is unsupported.
The existing Android host maps Back to the shared Flet menu; the app-shell owner
must map that optional menu's Return action to the native story contract while
preserving the default demo's Back behavior.

## Acceptance evidence

Run the [native recipe verifier](../scripts/check_native_lifecycle.py) and the
existing [demo verifier](../scripts/check_native_story.py). Receipts report
checks actually executed and separate PIDs for process-loss recovery. The
dedicated CI workflow runs both, including the original-bookmark compatibility
case.

Final local verification on native implementation `17c0137`, 2026-10-08:

| Check | Result |
| --- | --- |
| Complete prepared-Flet host suite | 278 tests passed, zero skips, including 15 adapter behavior and 10 verifier failure/staging tests |
| Optional native lifecycle | 55 checks passed in 20 distinct engine processes; standalone/library compile and standalone lint passed |
| Actual A bridge/native consumer | 53 checks passed in nine distinct engine processes; alternative-host compile and lint passed |
| Existing demo native suite | 72 checks passed in 14 processes, including original-bookmark compatibility |
| Existing real Flet protocol | 500 events in five cycles; zero idle messages; story/menu/save/reading checks passed |
| Existing application records | 45 prepared-Flet checks passed |
| Existing service ownership | 20 visits retained the same 14 service instances |
| Workflow review | actionlint 1.7.11 passed |
| Default package identity | APK build-input paths are unchanged from the base revision |

The lifecycle tests directly exercise the public Return helper, trap all native
save-reading APIs during four actual Resume calls, restore first-interaction and
older checkpoints, and keep current external application data after loads. They
also exercise save/load errors and declined loads, one completion handoff, a new
Start with the manual bookmark retained, a real worker autosave, ownership-aware
stale-recovery cleanup, and foreign/corrupt/unsupported metadata and environment
auto-load rejection. The real early Android profile branch and directory
validation run without changing Linux SDL ownership.

The actual-A gate verifies confirmation against the native scene/caller truth,
both active and returned Resume with save APIs trapped, disposed/phase/busy
action guards, and completion winning a late Return race. Explicit Load restores
the older native choice with current external records and real native reading
preferences. Old replies/results cannot change the restored session or selected
presentation. A real unpickleable runtime lock and pending mailbox request stay
outside both manual and mobile snapshots.

Library recovery used `4413 → 4434` (active), `4455 → 4476` (returned),
and `4497 → 4518` (completed). Actual-A recovery used `5497 → 5520`,
`5542 → 5565` and `5587 → 5610`, respectively. Each gate's demo still
recovered its newer two-star interlude after the optional scenarios. Every
optional mode verified both default demo archive hashes stayed unchanged; final
demo recovery consumed its own background archive while retaining its bookmark.

Receipts/logs/screenshots are under `.android-build/native-lifecycle-check/`
and `.android-build/native-story-mailbox-check/`; the existing demo receipts
are under `.android-build/native-story-check/`. Mailbox receipts identify the
unchanged A bridge and each compiled recipe file by SHA-256.
The concise [verification record](../examples/renpy/lifecycle/VERIFICATION.md)
includes the protected demo hashes. CI uploads the same source gates and native
receipts through `check-native-lifecycle.yml`.

The recipe lives outside packaged app inputs. No existing Android artifact can
demonstrate its UI; adding it to an app host requires a fresh combined APK and
device run. Native Linux checks can prove the actual save/recovery engine and
Android save-path selection, but do not prove Android surface/input/process
lifecycle behavior on a device. The existing camera exclusion and removed player
rollback remain in place.

Copyable calls, setup and save semantics are in the
[authoring example](../examples/renpy/lifecycle/README.md).
