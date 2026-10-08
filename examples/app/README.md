# App host with an optional native story

This separate project connects the shared Flet application routes to **The Last
Lantern**. Home offers Start or live Resume; story controls offer replacement
confirmation and Cancel; Return and completion update confirmed status before
navigation. Records and drafts stay independent of story saves. The default
**Before the First Light** project keeps its entry point.

| Source | Purpose |
| --- | --- |
| [game/host.rpy](game/host.rpy) | Ordinary native caller, command timer and idle interaction |
| [game/profile.rpy](game/profile.rpy) | Early isolated app save-directory selection |
| [../renpy/lifecycle/game/story.rpy](../renpy/lifecycle/game/story.rpy) | Callable native story and explicit checkpoint operations |
| [../../runtime/native_app_bridge.py](../../runtime/native_app_bridge.py) | Native-thread mailbox consumer and restoration |

## Assemble a separate project

Copy only these selected native inputs into a fresh project's `game/`, plus the
shared top-level runtime modules into its root:

```sh
mkdir -p .android-build/app-project/game
cp examples/app/game/*.rpy .android-build/app-project/game/
cp examples/renpy/lifecycle/game/story.rpy .android-build/app-project/game/
cp runtime/*.py .android-build/app-project/
```

Use a fresh destination when changing sources. Do not add the standalone native
recipe's `host.rpy` or `profile.rpy`, or the default demo's `game/`, to this project:
there must be one entry point and one early save profile. Android's embedded
runner supplies Flet and initializes its app route to `/app`; the existing builder
needs the packaging changes below before this project produces a runnable app.
Desktop assembly alone starts the native host, without an embedded Flutter UI.
The native verifier supplies a real Flet session for acceptance on Linux.

The save profile is `sdk-app-lantern-v1`, including Android's explicit
`ANDROID_PRIVATE/saves/sdk-app-lantern-v1` directory before persistent-data reads.
The manual slot is `sdk-native-lantern-checkpoint`. Caller metadata adds exact
integer `sdk_app_host=1` to the native recipe's profile/story/schema checks, so
archives from a different caller cannot restore into this host. Keep all writable
save directories separate from the standalone recipe and default demo.

Resume reads the current live continuation. **Load checkpoint** deliberately
restores an older native timeline and never restores records, Flet services or
the selected app route. Runtime request/session IDs remain outside native saves;
fresh-process recovery publishes new identities before accepting commands.

## Verify without an Android build

With Python 3.12, Xvfb and the repository build virtual environment installed:

```sh
.android-build/venv/bin/python scripts/check_native_app_bridge.py
```

The command prepares the pinned Ren'Py/Flet inputs if needed. It compiles/lints
an isolated project, uses separate native and Flet threads in one interpreter,
and exercises Start, Return, Resume, replacement, completion, Cancel, explicit
Load and fresh-process recovery. It also checks rejected foreign caller saves.
JSON receipts and logs are in `.android-build/native-app-bridge-check/`.
Preference service replies are simulated; actual Android/Flutter rendering and
packaging require the combined device check.

## Android packaging handoff

D owns the builder and Android host changes. For app startup:

1. Recreate the selected project's staged `game/` directory; copy the app
   `host.rpy` and `profile.rpy` plus the callable native `story.rpy`. Switching back
   to story mode must recreate it from the default `game/` inputs.
2. Copy the shared top-level `runtime/*.py`, and set the embedded runner's initial
   route to `/app`. App mode must select this native project as well as a route.
3. Include the selected example sources and startup mode in APK source identity;
   invalidate staged/output app inputs when either changes.
4. Build fresh combined APKs, preserve all 19 extensions/notices and retained
   camera/rollback choices, and run app-specific Android acceptance: initial
   home, Start, contextual Back/Return, live Resume, completion/result, Cancel,
   reconnect/background recovery, explicit app/records links and records/draft
   retention across checkpoint Load.
5. Validate the default story-mode package and source hashes separately when
   switching modes. Default story-demo expectations cannot establish app-host
   acceptance.

No Android startup/packaging or SDK pin files are changed by this recipe.
See [the shared runtime contract](../../docs/app-runtime.md) for routes,
revision guards, mailbox APIs and evidence.
