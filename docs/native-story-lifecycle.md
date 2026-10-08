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
| B coordinator | `examples/renpy/lifecycle/`, this guide, README links, dedicated lifecycle workflow | Callable native story, isolated profile, authoring and handoff |
| Native verification worker | `scripts/check_native_lifecycle.py`, `scripts/native_lifecycle_driver.py`, `scripts/native_lifecycle_probe.rpy`, dedicated harness tests | Native behavior, profile guard and save-isolation receipts |

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

Final local verification on native implementation `a69f78b`, 2026-10-08:

| Check | Result |
| --- | --- |
| Complete prepared-Flet host suite | 259 tests passed, zero skips, including six verifier failure/evidence tests |
| Optional native lifecycle | 55 checks passed in 20 distinct engine processes; standalone/library compile and standalone lint passed |
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

Process-loss recovery used `2896 → 2917` (active), `2938 → 2959` (returned),
and `2980 → 3001` (completed). The demo used `2850 → 3210`; it still recovered
its newer two-star interlude after the optional scenarios. Every optional mode
verified both default demo archive hashes stayed unchanged; the final demo
recovery then consumed its own background archive while retaining its bookmark.

Receipts/logs/screenshots are under `.android-build/native-lifecycle-check/`;
the existing demo receipts are under `.android-build/native-story-check/`.
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
