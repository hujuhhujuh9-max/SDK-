# Native lifecycle verification — 2026-10-08

Native implementation checked: `a69f78b`, based on main
`c8d4dd1f2be678756d96bac228070b50b0539d14`. Subsequent handoff documentation
does not change the tested story or verifier inputs.

`scripts/check_native_lifecycle.py` passed 55 native checks in 20 separate
processes using the pinned modified Ren'Py 8.5.3 SDK on Linux/Xvfb. Three source
gates passed: callable-library compile, unchanged standalone-host compile and
standalone-host lint. Screenshots were inspected at 720×1280.

The checks cover Start, Return/Resume at all three phases, Resume with native
save-reading APIs trapped, older checkpoint loads, first-interaction save/load,
native I/O errors and declined loads, completion delivered once, completed
Resume rejection, new Start, worker autosaves, and recovery of active, returned
and completed state in fresh processes. Own stale recovery is consumed on
Return, completion and new Start. Foreign recovery survives Start/Return.
Manual and automatic loads reject foreign, corrupt and unsupported metadata,
including a Boolean schema masquerading as integer version 1.

Every optional scenario preserved these default demo archives byte for byte:

| Archive | SHA-256 |
| --- | --- |
| `renfletpy-quick-LT1.save` | `9033ecef56ece4c56cc03850d5b6c45eb67d611cc342a37dd525ab4ecba4250b` |
| `_reload-1-LT1.save` | `101246fd672266d8f4234797d5f3aab041ba8d5a0836d6987d4480d0c0f9fe67` |

The unchanged demo then recovered its newer interlude in a fresh process and
consumed its own temporary recovery save. Its existing native suite also passed
all 72 checks in 14 processes, including original-bookmark compatibility. The
complete prepared-Flet host suite passed all 259 tests with zero skips.

Generated evidence: `.android-build/native-lifecycle-check/results.json`, its
per-process JSON/log/screenshot files, and the three compile/lint logs.
The dedicated workflow uploads these files with the source SHA.

Android save-path selection and the real native `mobile_save`/auto-load pipeline
are exercised by the Linux verifier. No new APK or Android device run was made:
this opt-in recipe is outside the unchanged default package inputs. The app-shell
owner must include it in a fresh combined APK, connect its optional Back/Return
route and run device acceptance. Camera exclusion, removed player rollback,
SDK pins, shared routing and the Android host remain unchanged.
