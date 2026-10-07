# Optional Ren'Py example verification

Verified on 2026-10-07 on Linux, against `main` at
`b17a816` and the repository's pinned, modified Ren'Py 8.5.3 SDK
(`8.5.3.26051504`). Only new files under `examples/renpy/` are part of this change.

| Check | Result |
| --- | --- |
| Standalone gallery `compile` | Passed |
| Standalone gallery `lint` | Passed, no script errors or lint findings |
| Isolated native example probe under Xvfb | 11 checks passed |
| `python3 -m unittest discover -s tests -v` | 185 tests run: 165 passed, 20 Flet-dependent cases skipped |
| `python3 scripts/check_native_story.py` | 55 checks passed across all 7 native modes |
| Existing tracked files compared with base | Unchanged |

The isolated example probe copied the gallery into the ignored build cache and
added temporary verification code there. It exercised the real native screens,
input widget events, screen button actions, framebuffer, and save system:

- Character dialogue and narrator dialogue entered native history.
- Default and custom choice IDs returned to their corresponding story branches.
- Choice screens closed after selection.
- Native text events and Enter returned trimmed input.
- The initial value, four-character limit, and **Confirm** button worked.
- Empty and whitespace-only submissions returned custom fallbacks.
- The input screen closed after submission.
- ATL moved actual framebuffer pixels and changed their opacity. The measured
  square center moved from x=119.5 to x=142; its average green channel changed
  from 126 to 149 between captures.
- **Continue** returned `"finished"` and removed the animation screen.
- Saving, advancing, and loading restored the example's name, choice, script
  position, and chronological history.

Rendered choice, input, and animation captures were inspected for readable text
and reachable controls. Probe receipts, screenshots, and logs from this workspace
are in `.android-build/renpy-examples-check/`; gallery compile/lint output is in
`.android-build/renpy-examples/`. These generated artifacts are not committed.

The existing native suite verified the current demo's dialogue and animation,
quick saves and loads, worker autosaves, fresh-process background recovery,
history, reading preferences, interlude results, replay, tactics rendering and
state, and absence of player rollback. Its receipts are in
`.android-build/native-story-check/`.

`game/`, `runtime/`, `android/`, `flutter/`, `assets/`, `scripts/`, `tests/`,
the build scripts, SDK lock, existing documentation, and save configuration were
not edited. The Android packaging input remains the existing root `game/`;
examples are outside that input. The optional gallery uses its own save directory
and the verification processes used isolated save paths.

Scope: Linux native rendering and host regression checks. An Android APK was
not rebuilt, and the optional examples were not exercised on an Android device.
The 20 Flet-dependent host skips remain unverified in this environment; no bridge
or Flet code changed. See [README.md](README.md) for repeatable gallery and
existing-regression commands.
