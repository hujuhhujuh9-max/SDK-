# Native lifecycle verification — 2026-10-08

Native implementation checked: `17c0137`, based on main
`c8d4dd1f2be678756d96bac228070b50b0539d14`. The library check ran the same
story source on `30511eb`; the combined actual-A check ran on `17c0137`.
Following documentation/workflow changes do not change the tested native inputs.

`scripts/check_native_lifecycle.py` passed 55 native checks in 20 separate
processes using the pinned modified Ren'Py 8.5.3 SDK on Linux/Xvfb. Three source
gates passed: callable-library compile, unchanged standalone-host compile and
standalone-host lint. The actual-A consumer verifier passed another 53 checks in
nine processes, plus alternative-host compile and lint. Screenshots were
inspected at 720×1280.

The checks cover Start, Return/Resume at all three phases, Resume with native
save-reading APIs trapped, older checkpoint loads, first-interaction save/load,
native I/O errors and declined loads, completion delivered once, completed
Resume rejection, new Start, worker autosaves, and recovery of active, returned
and completed state in fresh processes. Own stale recovery is consumed on
Return, completion and new Start. Foreign recovery survives Start/Return.
Manual and automatic loads reject foreign, corrupt and unsupported metadata,
including a Boolean schema masquerading as integer version 1.

The actual-A gate covers worker submissions and native-thread confirmation,
active Resume without reentry, returned Resume without disk reads, stale
scene/phase/busy guards, explicit older checkpoint loading with current records
and reading preferences, fresh runtime IDs and rejected stale results, and a
completion/late-Return race. A real lock and pending request in the runtime module
are excluded from saves; all three cold recovery states discard that pending
command and completed recovery retains its plain caller result without replay.

Every optional actual-A scenario preserved these demo archives byte for byte:

| Archive | SHA-256 |
| --- | --- |
| `renfletpy-quick-LT1.save` | `3b672e509ab03445701d0b0dd47437c25b54cc86bb35701085d9ef057c3c5b72` |
| `_reload-1-LT1.save` | `172d7fc5fdb887927b827e93ca98da95d2313915e6df1d0f8590245c5b4089a6` |

The unchanged demo then recovered its newer interlude in a fresh process and
consumed its own temporary recovery save. Its existing native suite also passed
all 72 checks in 14 processes, including original-bookmark compatibility. The
complete prepared-Flet host suite passed all 278 tests with zero skips.

Actual A revision: `7bdef8cb6bfb966a7fe00758e2e2cd5e57a58e44`;
`sdk_bridge.py` SHA-256:
`f75aa8e91572bdcc887b6233d9dc0dbf2cb9620d0e335e93a75d7c2c6616e084`.
Each mailbox receipt also records hashes for the compiled story, early profile,
alternative host and module adapter.

Generated evidence: `.android-build/native-lifecycle-check/results.json`, its
per-process JSON/log/screenshot files, and the three compile/lint logs;
`.android-build/native-story-mailbox-check/` contains the actual-A receipts and
two additional source gates.
The dedicated workflow uploads these files with the source SHA.

Android save-path selection and the real native `mobile_save`/auto-load pipeline
are exercised by the Linux verifier. No new APK or Android device run was made:
this opt-in recipe is outside the unchanged default package inputs. The app-shell
owner must include it in a fresh combined APK, connect its optional Back/Return
route and run device acceptance. Camera exclusion, removed player rollback,
SDK pins, shared routing and the Android host remain unchanged.
