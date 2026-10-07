# Optional Ren'Py example verification

Verified on 2026-10-07 on Linux, against `main` at
`b17a816` and the repository's pinned, modified Ren'Py 8.5.3 SDK
(`8.5.3.26051504`). All changes are confined to `examples/renpy/`.

| Check | Result |
| --- | --- |
| Independent compilation of each reusable file | All 4 passed |
| Standalone gallery `compile` | Passed |
| Standalone gallery `lint --error-code` | Passed, no script errors or lint findings |
| `python3 examples/renpy/verify.py` under Xvfb | 48 native checks passed: 15 interaction checks, 20 gallery checks, 13 isolated first-interaction checks |
| `python3 -m unittest discover -s tests -v` | 185 tests run: 165 passed, 20 Flet-dependent cases skipped |
| `python3 scripts/check_native_story.py` | 55 checks passed across all 7 native modes |
| Existing native suite with the four optional library files loaded | 55 checks passed across all 7 modes |
| Existing product files compared with base | Unchanged |

The committed [verifier](verify.py) uses fresh temporary projects and isolated
saves, compiling each reusable file independently before exercising the real
native screens, input widget events, screen button actions, framebuffer, and
save system:

- Character dialogue and narrator dialogue entered native history.
- Loading active dialogue restored its speaker, text, and history without
  duplicate history entries.
- Default and custom choice IDs returned to their corresponding story branches.
- Loading an active choice restored its options and discarded future results.
- Choice screens closed after selection.
- Native text events and Enter returned trimmed input.
- The initial value, four-character limit, and **Confirm** button worked.
- Empty and whitespace-only submissions returned custom fallbacks.
- Loading an open input prompt restarted it with its initial value; unsubmitted
  edits did not become saved story data.
- The input screen closed after submission.
- ATL moved actual framebuffer pixels and changed their opacity. The measured
  square center moved from x=118 to x=130; its average green channel changed
  from 124 to 137 between captures. Loading the active animation restored its
  screen and visible movement.
- **Continue** returned `"finished"` and removed the animation screen.
- Saving, advancing, and loading restored the example's name, choice, script
  position, and chronological history.
- The gallery's real `start` ran through all menu routes, both choice branches,
  input editing and revisiting, animation, returning to the menu, and normal exit.
- Each of the four examples ran with only its own reusable file and a minimal
  host in a fresh project and process. Its receipt records the loaded `.rpy`
  files, establishing independence at runtime as well as compilation.
- Each isolated example saved and loaded as the first interaction, then returned
  its expected result through queued native keyboard events. Choice navigation
  used arrow keys; dialogue, input, and animation completed with Enter.
- The isolated dialogue used the host's Character and say screen, with native
  text interpolation and a single history entry after loading.
- Input returned its trimmed submission while preserving the host's separate
  story variable named `answer`.

The first-interaction check exposed a load failure in the original example:
loading its opening line replayed startup defaults. Each reusable label now
calls the existing `renpy.checkpoint()` API before its interaction, establishing
the intended load point. The fix is confined to the example labels; SDK source,
the demo's entry point, and save callbacks were not changed.

The isolated input check also exposed an unprefixed assignment that overwrote
the host's `answer` variable. The label now returns the `renpy.input()` result
directly, keeping edits in screen scope. The native check reproduced the
collision before this change and passes with the host value intact afterward.

Rendered choice, input, and animation captures were inspected for readable text
and reachable controls. Repeatable receipts, screenshots, compile/lint output,
and logs are in `.android-build/renpy-examples-check/`, with one subdirectory per
native mode. These generated artifacts are not committed. The verification
driver and probe under [checks/](checks/) are loaded only into temporary projects.

The existing native suite verified the current demo's dialogue and animation,
quick saves and loads, worker autosaves, fresh-process background recovery,
history, reading preferences, interlude results, replay, tactics rendering and
state, and absence of player rollback. Its original receipts are in
`.android-build/native-story-check/`. The compatibility run used the unchanged
native suite with a temporary copy hook to add `dialogue.rpy`, `choice.rpy`,
`input.rpy`, and `animation.rpy` to the suite's isolated game. Its receipts are
in `.android-build/native-story-with-examples/`; it did not copy `gallery.rpy` or
the example verification hooks into the demo.

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
