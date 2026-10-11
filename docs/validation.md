# Runner validation

The runner disables phone-camera access, GPS/location and recording, retains
their extension code, removes player rollback, and verifies
real media and animation output. Earlier source commits and their original device scopes are
in [the validation history](validation-history.md); measurements are in
[performance.md](performance.md).

## Named native save browser — 2026-10-11

**Saved games** is available from the story menu and app Home. It creates
multiple named native checkpoints, lists their dates/scenes, and confirms Load,
Overwrite and Delete. Quick save and native recovery keep their own slots;
application Records remain independent of the story snapshot. The reusable
Flet browser submits plain commands to the shared native save backend.

The [signed-release browser probe](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38108444139)
passes on Android 15 / API 35 x86_64 with zero skips. It creates two distinct
positions, checks overwrite/delete and cancellation against native file hashes,
force-stops process `4689`, reopens as `6077`, loads the unanswered choice and
the earlier native dialogue, then continues to the native ending and completion.
The quick-save hash is unchanged and newer Record `NewerRecord507011ed`
survives both native loads. Retained screenshots show the browser, restored
positions, completed Home and Record. This new browser has not yet had a
physical Redmi retest; the earlier manual phone acceptance above remains separate.
The existing API 36 probe also passes the same source-bound browser checks
with zero skips, retaining the newer Record across process `5518` → `7335`.

The tested APK uses application source
`494ed5b7f08a327e927cce76f7939a058da84141`; corrected browser harness
`832be693339718ac83e4d0acd8cc16077d77a4dc` changes no APK build inputs.
The first probes exposed driver assumptions about the scoped external save
directory, Android's omitted input label and the widthless viewport marker.
Those failures produced no success receipt. The corrected probe uses the exact
installed package/process, unique browser editor and painted framebuffer.

Prepared-Flet CI passes all **583 host tests with zero skips**. Actual Linux
Ren'Py checks pass **76 story checks across 16 processes** and **42 app checks
across 15 processes**, plus app-wide isolation checks. Native fixtures cover
independent clean compilation, original bookmarks, trust prompts and protected
quick/autosave files. The [full Android story regression](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38106366956)
also passes, with empty diagnostics and Records retained across process
`13859` → `15386`.

The [app-mode recipe probe](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38108521792)
passes all eight control checks with zero skips: exact native keyboard JSON,
invalid-input retention, sorting/selection, painted color output and async
loading/cancel/departure. The driver now confirms each bounded auto-pair
deletion. Its first full-app attempt subsequently loses ADB at `unroot` during
native save-file inspection and produces no full-app acceptance receipt. Only
that device job is being retried with the same source-compatible APK.

The [internal universal APK bundle](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38106366956/artifacts/11690018360)
contains **RenFletPy Example**, package `org.renfletpy.example`, version `0.1.0`
/ code `1`, signed with a disposable CI key. The universal APK is 244,160,446
bytes, SHA-256 `87ebae2876d3579191748208dcc5e860c9c55267c9980be0cf6ee4ca55c89320`;
the tested x86_64 APK is `e23435b7bbc65bd033945f836da958276c374941771dba9aa92412ee9ca919e3`.
All 979 shared payload hashes match; all 19 extensions, 541 Python resources,
367 common assets and selected native ABIs remain retained. Camera, location
and recording permissions remain absent. This is an internal test build.

## Clean release update and native save continuation — 2026-10-10

An independently compiled second APK changed unnamed Ren'Py statement IDs.
Loading a saved choice could restore Flet controls over a native exception:
the loader returned to the parameterized `renfletpy_panel` label after its
arguments had already been consumed. Shared interludes now retain state before
stable `.wait` labels, and the bundled stories have explicit `from` return
labels. The generated external project copies these authoring changes. Native
staging still removes old source and compiled files on every build.

The tightened update gate rejects the original broken pair in
[run 38079777287](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38079777287).
It requires choosing the restored branch, native ending dialogue, native
completion in the updated process, and the original Record after story loading;
native tracebacks prevent a success receipt. Visible choice buttons alone no
longer establish a pass.

The corrected [run 38080288568](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38080288568)
passes with zero skips on Android 15 / API 35 x86_64, 1080×1920 / 420 dpi.
Attempt 2 retries only the device job after ADB logcat/screencap returned exit
255 during the initial baseline Start/Return check. The successful build and
APKs are reused. Package `org.renfletpy.update35`, **RenFletPy Update Test**,
updates in place from `0.1.0` / code `1` to `0.1.1` / code `2`, retaining UID
`10209`. Baseline process `4663` finishes the **Share** branch; updated process
`5293` loads the unanswered choice and finishes the **Keep** branch.
Record `ReleaseRecordaccb68aa647e` remains after installation and after native
loading/completion. Screenshots show the restored choice, native ending,
completed home and retained Record, without a native exception overlay.

Both builds use source `dd31441024be3e7a2c2549d48fde21bc76a83bdc` and certificate
SHA-256 `1cda543135d8ebd72c3814a9b3e557b53fb5d817bc40721654f65b1c5cf71dc4`.
The universal APKs are independently inspected with all three ABIs, all 19
extensions, 541 Python resources and 367 Ren'Py common assets retained, correct
icons/identity/signatures, and camera/location/recording permissions disabled.

| Version | Universal bytes | Universal SHA-256 | Tested x86_64 SHA-256 |
| --- | --- | --- | --- |
| 1 | 244,158,486 | `bb2b4413c4a00ceb3ef5f596792dc522d03f1b10e6c391f3182e342e6aafe5ec` | `7644b75524dc1b559f74e9f4d7625a57cca0a2fe7bc2fb2ea80fa47b09204783` |
| 2 | 244,159,674 | `f335358245100bbdc7fb9860c780e62aa52074762155c6eec44ef4247d680465` | `fa3ce7252a83a1fa317b545313a4027849e72bcadbeb86e1b66f1d5a9c2b4b4b` |

The user confirms the [same-key phone update procedure](project-template.md#same-key-update-check)
passes on the physical **Redmi Note 14 Pro, Android 15 / API 35**, using this
run's version 1 and version 2 universal APKs. A Record created in version 1
remains after updating to version 2. Quick save at the unanswered **Keep a copy /
Share it with Mira** choice, followed by finishing the **Share** branch in version
1, survives the update: **Resume story** restores that unanswered choice in
version 2, and the **Keep** branch completes. The Record also remains after
story loading/completion and the final force-stop/reopen. This is manual phone
confirmation through direct APK installation; physical process IDs and save-file
hashes were not captured through ADB.

Runtime CI passes all 560 prepared-Flet host tests with zero skips and 500 real
protocol events across five cycles. Native Linux checks pass 72 named checks
across 14 default-story processes and 37 across 13 app processes, including
independent clean compilations for minigame, tactics and app-choice recovery.
Original-bookmark compatibility, background recovery, trust prompts and default
save isolation remain covered. These are host/emulator results, separate from
the manual phone update above.
Both APK versions contain the stable labels; migration from earlier releases
without them and arbitrary story rewrites require separate checks.

The normal [post-merge run 38082218614](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38082218614)
passes all six gates on merged source `cfc9c5d110bf6bf467ffa3af6ab059ba164c0629`. Both API 35 and
API 36 signed-release project probes pass five checks with zero skips. Records
survives force-stop and fresh process startup, `3232` → `4408` on API 35 and
`3388` → `5176` on API 36. The full API 36 default-story suite also passes:
native story continuation, warm/cold saves, tactics, reading settings, actual
audio/video/animation output, native services, file selection, deep links and
Records persistence. The source-bound control-recipe receipt has zero skips;
Records survives process `13959` → `15503`, and file/preferences/secure-storage
contents agree across initial startup, clean shutdown and force-stop recovery.
Retained screenshots show the restored minigame progress and completed ending.
The full API 36 app suite passes all 13 required scenarios, including native
Start/Return/Resume, saved choice continuation, cold Records recovery,
unsigned-save refusal/acceptance and default/app save isolation. App process
`5093` → `10315` retains current Records; reinstalling the default template in
process `11776` restores its original native recovery and shared Records.
App-mode control recipes also pass with zero skips. The generated release
project passes five checks with zero skips, retaining Records across process
`12137` → `12591`.

Attempt 2 retries only the app job after keyboard automation left an extra
auto-paired `]` in its recipe fixture. The first attempt stopped before
submitting that fixture and produced no app acceptance receipt. The retry
uses the same source and APKs; no source change or rebuild was made.

## Records release layout correction — 2026-10-10

The first phone report is a Redmi Note 14 Pro running Android 15 / API 35.
Opening Application records consistently produces a gray screen; Android Back
returns to the app. The Records heading puts an expanded Text inside a wrapping
Row. Pinned Flet advertises that parent as supporting expansion, but renders it
as Flutter Wrap, whose parent data is incompatible with Expanded. The heading
now uses a normal Row, retaining the title and Back button.

A real pinned-Flet protocol regression fails before this correction and passes
after it. The signed-release project probe now creates a Record through the
Android UI and verifies it after force-stop and a fresh process launch; empty
Records screens, stale UI snapshots and lost records cannot produce a success
receipt. The combined gate also runs this signed-release probe on an Android 15
/ API 35 x86_64 emulator. Emulator results and the manual phone retest are
recorded separately.

The `integration/api35-records` build supplies `api35-phone-retest-apk` with
package `org.renfletpy.api35`, label **RenFletPy API 35 Test**, version `0.1.1` /
code `2`. Install it alongside the original app: disposable CI keys differ
between builds, so this package avoids uninstalling the original app and
erasing its data. It has its own Records collection. On the phone, open Records,
add a titled record, close the app fully, reopen it, and check the saved record.
Then verify Start story and Return to app. No PC or ADB connection is required
for this manual retest.

The [focused signed-release run 38058731725](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38058731725)
passes all five project checks with zero skips on both API 35 and API 36 x86_64
emulators at 1080×1920 / 420 dpi. Home/asset output, native Start/Return, fresh
startup and saved Records all pass. Records survives process `3298` → `4725`
on API 35 and `3608` → `5292` on API 36; saved and reopened screenshots are
retained. APK source is `7c3270db3774bcf1417513aaa183872f24f16a7f`, and the
corrected harness is `ef5e65ada84fc9048487e7f7d2a134f927317818`. Source comparison
confirms that no APK build inputs changed while correcting emulator first-use
setup and selecting the unlabeled release Title input.

The [post-merge combined run 38059626357](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38059626357)
passes all six gates on source `ebfad667febc410dd7e1baf6a5d84fbb30a61846`:
build, runtime, API 35 and API 36 signed-release project checks, and the API 36
native story and app suites. Attempt 2 retries only the app job after its
initial emulator/ADB setup failure before app launch; no source change was
needed. This is automated emulator evidence, separate from the phone reports.

The verified universal phone APK is 244,159,386 bytes, SHA-256
`e8c46d730b63ff1082d4170da520d2fddaae541c6230db831fb3266a31fc3ce4`;
the tested x86_64 APK is SHA-256
`3d37c26e93a1146498fd8f3b839b4150c876a68e8e25e69fb8fee2afcd24d135`.
Both use CI certificate SHA-256
`b0079cd0d8abb6d79cd9c6d7bc06a828c38e449f4b0a765bfec13aa1050d4c5c`.
Universal inspection verifies all three ABIs, retained integrations, manifest,
signature, supplied icon and exact corrected Records source bytes. These are
emulator and APK results.

The user confirms the manual basic pass on a physical **Redmi Note 14 Pro,
Android 15 / API 35**, using **RenFletPy API 35 Test**: install/launch succeeds,
Application records opens, a saved record survives fully closing and reopening
the app, and Start story → Return to app works. This completes the first phone
acceptance pass through direct installation, without a PC/ADB connection.
Phone evidence is the user's manual confirmation; signed APK hashes and fresh
process IDs above belong to the automated emulator checks.

The user also confirms all three background/resume checks on the same phone
and installed test app: Records remains visible and usable after switching to
another app for 30 seconds; the story responds and Return to app works after
the same app switch; and story/return navigation works after locking the phone
for 30 seconds and unlocking. No blank screen, freeze, crash or missing saved
record is reported. This is manual phone evidence, separate from emulator
lifecycle results.

The user confirms the media checks on the same phone and installed test app:
Play audio produces sound, Pause stops it and Resume restores it; Play video
shows moving frames, Pause freezes them and Play starts them moving again;
and Play animation shows movement while Pause stops it. These are direct
manual observations of playback, separate from automated PCM/pixel probes.

The user reports **Device checks passed** after tapping **Run checks** on
Capabilities in the same installed phone app. That success status requires
the bundled extension imports, clipboard, preferences, secure storage,
app storage paths, local WebView/media checks and native Android service/worker
checks to complete. The user also confirms **Device checks passed** again after
using Android App info → Force stop, reopening the app and repeating Run checks.
The stored challenge must agree across its file, preferences and secure storage
for that second run to pass. This records manual confirmation of service storage
surviving a forced restart; physical process IDs and challenge hashes were not
captured through ADB.

The user confirms the Records edit/delete checks: a temporary Record's Title
and Details are edited and saved, both changes remain after force-stop and
reopening, and deletion remains effective after another force-stop/reopening.
This verifies application entry persistence, which is independent of native
story saves. The user also confirms the native story checkpoint test: Quick save
at the unanswered **Keep a copy / Share it with Mira** choice, continue through
completion, force-stop and reopen, then **Resume story** restores that unanswered
choice. This confirms a distinguishable story position and choice state after
restart in the same signed phone APK. Evidence is the user's manual observation;
no physical save-file hashes or process IDs were captured through ADB.

The user confirms the Application recipes controls in the same phone app:
the JSON editor applies Harbor's count change from 5 to 6, the table shows the
changed value and supports sorting and row selection, a color swatch updates
the preview, and loading animates before reporting **Loaded 3 rows**. Cancelling
a new load also works. These are manual observations; this page's sample edits
are temporary and are independent of persistent Records and native bookmarks.

The user confirms about five minutes of using Records, Application recipes,
story navigation and media on the same Redmi: the app stays responsive, with
no freezes or crashes. This is a manual responsiveness pass, without measured
frame rates, memory usage or ARM timing benchmarks.

## Reusable project and release workflow — 2026-10-09

The [external project template](project-template.md) supplies editable Flet app
code, native story, assets, package identity/version and an optional icon without
changing SDK sources. Staging is recreated for each build; deleted or renamed
project files do not survive. Project input hashes are distinct from the SDK
source revision and are checked against packaged bytes.

Release builds use `flutter_release`, native `assembleRelease` and an isolated
verified AAR cache. Inspection requires the AOT `libapp.so` for every selected
ABI and rejects the debug Dart kernel payload. Signing is optional and supplied
through environment values; unsigned artifacts are clearly identified. CI uses
a disposable test key and verifies signatures before installation.

The combined gate retains the full story/app suites and adds a generated,
edited release project. It checks custom home/asset output, native story and
return, a fresh process, actual package/version/label, non-debuggable status,
installed APK hash and the absence of camera/location/recording permissions and
the location service. Both build modes require verified cold/warm cache
behavior.

The [first combined main run 37931772567](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37931772567)
checks source `baa0a44a9a471e658d5985199723f5e727ceab79` from
[PR #20](https://github.com/hujuhhujuh9-max/SDK-/pull/20).
Prepared-Flet host checks pass all 546 tests without skips. The build host's
separate unprepared discovery run skips 102 Flet-dependent tests; the required
runtime gate runs the complete suite with pinned Flet and zero skips. Native checks pass
72 story assertions across 14 processes, 32 app assertions across 12 processes
and 48 authoring assertions across six scenarios. Runtime evidence confirms
500 protocol events across five cycles, zero idle messages and 14 retained
service identities across 20 visits.

Four debug APKs and two signed project release APKs retain all 19 extensions,
541 required Python package/resource files and 367 native common assets. Both
universal and x86_64 inventories and shared payload comparisons pass. Each
Flutter mode compiles one cold AAR; unchanged and Python-only warm phases
compile zero AARs, and published caches restore with identical verified
contents. All seven Flutter analysis/test phases pass.

The edited project has input SHA-256
`7c23639148073d4a412d3f70d70c7770a922768fd39bafb9c68a67f0c64da5e1`,
package `org.renfletpy.example`, version `0.1.0`/code `1`, and the supplied PNG
icon. Its signed universal APK is 244,159,178 bytes, SHA-256
`8244c7dd8d4b5a685376c8dbf4dc2526062bc1c300f3e094f533cead28275fe1`;
the x86_64 APK is 102,244,170 bytes, SHA-256
`6a31b333090ff46e94b1cac27f391bb37217500cdd19cc0b3c80044b8a14abd5`.

The actual story-mode Android suite passes all eight control-recipe operations
with zero skips, seven Records scenarios and durable storage recovery across
three distinct processes. Native ATL samples move before and after
background/resume. The downloaded evidence archive matches GitHub's digest,
and its inspected APK/source/profile match this build. The story harness
installs the inspected APK path; the release-project probe additionally hashes
the installed APK bytes.

The existing app-mode suite also passes all eight control-recipe operations
with zero skips and thirteen story/lifecycle/save scenarios. Native saved Resume
and Quick load each exercise unsigned-save refusal and acceptance; the signed
checkpoint is restored exactly without reverting newer Records. Default quick
and mobile save hashes remain unchanged, and reinstalling the story template
recovers its original scene and shared records. These completed results precede
the custom-project preflight failure below.

This run fails the generated-project preflight before installation: its icon
check assumes the original `runner_icon.png` filename. Android's release resource
optimizer changes that path to `res/NN.png`. A separate
[read-only inspection](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37942777304)
of the same signed APK confirms its compiled icon bytes exactly match the
supplied PNG, SHA-256
`2a9143a18d0a23d55898314064a3b92987cf5a508a7659de97364ab013d3f5c5`.
The corrected checker reads every manifest-resolved icon from the APK and
requires its SHA-256 to match the supplied icon, independent of its resource
filename. It saves the compiled manifest before validating it so failed preflight
diagnostics are retained. Corrected acceptance is recorded below; the first
failed run alone does not establish generated-project compatibility.

The [corrected main run 37943783718](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37943783718)
passes all four required gates for source
`49f50a39a7ba62b7c238ce4607f1e56314b61ce7` from
[PR #21](https://github.com/hujuhhujuh9-max/SDK-/pull/21). Its complete
prepared-Flet suite passes all 548 tests without skips. Its six APKs retain the
same verified extension/resource inventories and the edited project input hash
above. Native story/app/authoring checks pass 72/32/48 assertions. All seven
Flutter stages reuse the verified debug/release caches from the first run, with
zero AAR compilations and no duplicate cache publication; both receipts remain
unchanged. Signed release artifacts are:

| APK | Bytes | SHA-256 |
| --- | --- | --- |
| Universal release | 244158034 | `f95ba38abb3e7b2c53218c8dae9e667977a5eae5e5e36df9248e6d49cc3fb186` |
| x86_64 release | 102243026 | `0ecbb74fa472c40bc3f7289ed13a29685e7ad98671158c65433c1895282c423a` |

Both existing Android suites pass eight control-recipe operations with zero
skips. The story suite passes seven Records scenarios; the app suite passes
thirteen story/lifecycle/save scenarios, including native unsigned-save
refusal/acceptance and exact signed-checkpoint restoration while retaining newer
Records and unchanged default save hashes.

The generated signed release passes all four project checks with zero skips:
its edited home and local asset, the edited native dialogue, return to that home,
and recovery in a fresh process (`12093` to `12350`). The installed APK hash
matches the x86_64 release above. Its package/version/label, non-debuggable
status, signature and original icon bytes pass inspection; camera/location/
recording permissions and the location service are absent. Native dialogue fills
the scene without Flet or keyboard overlap. Receipts, compiled-manifest and
signature output, installed-package evidence, logcat and four actual screenshots
are retained in the app artifact. The screenshots confirm the custom home,
edited native dialogue, return and fresh startup.

These checks target the existing Android 36 x86_64 1080×1920/420 dpi emulator.
The first physical-device target is Android 15 / API 35 on ARM. Its initial
pass covers install, launch, story Start/Return and Records persistence after
restart. Media, background/resume, updates and performance follow that basic
pass; broader Android coverage can wait. Production
signing identities and Play Store AAB/asset delivery are separate from CI's
signed release examples. Release examples have no advertising flow and suppress
eager ads initialization without removing the plugin.

## Editor, table, color and loading recipes — 2026-10-09

Application recipes opens from app Home or Diagnostics, using the existing
CodeEditor, DataTable2, BlockPicker and ThreeBounce extensions. The page applies
bounded JSON rows, sorts/selects them, changes a color preview and supports
async loading with cancel/retry. Query echoes retain its mounted data; departure
and disconnect retire its callbacks and pending results. Sample values remain
independent of persistent Records and native saves.

Local verification passes 449 prepared-Flet host tests without skips or failures,
including 13 real extension-control/protocol cases and 13 device-helper evidence
regressions. Invalid Unicode names are rejected before Flet message encoding;
valid Unicode loader data stays within the editor's source limit. Workflow lint
and whitespace checks pass.

Both Android startup suites now require a matching `app-recipes.json` with actual
software-keyboard input, changed table order/selection, picker/preview pixels,
painted pending loading output, completion, cancellation/retry and protected
reentry after pending work. Missing, deferred, skipped or wrong-source/mode/hash
receipts fail the gate. The default sample loader waits eight seconds; it is a
bounded demonstration, not evidence of external data-service I/O. Spinner
animation timing is outside these checks.

Fresh native, APK and actual device results for finished main revisions are
recorded by the [combined main workflow](https://github.com/hujuhhujuh9-max/SDK-/actions/workflows/integration-abc.yml?query=branch%3Amain).
Its artifact receipts identify source, startup mode, APK hash/ABI and actual
Android profile. Other ABIs retain packaging checks; this fixture targets the
existing Android 36 x86_64 1080×1920/420 dpi emulator.

## Optional app starter — 2026-10-08

The explicitly selected `app` template opens app home and persistent records,
then starts, returns from and resumes **The Lighthouse Note** through native
acknowledgements. Completion displays a plain result while retaining explicit
bookmarks. Its native save namespace is isolated from the default observatory;
application records remain shared and independent of story loads.

The audited source passes 405 prepared-Flet host tests with zero skips and the
96-case app gate. Real protocol stress passes 500 events across five cycles
with no idle messages; service inspection retains 14 identities over 20 visits.
Default native checks pass 72 assertions in 14 processes, including original
bookmark compatibility. App native checks pass 28 assertions in ten processes,
including genuine unsigned-save refusal/acceptance and enforced save isolation.
Independent wire regressions cover delayed native Menu/Resume requests, both
reply orders, newer Records intents, route repair, reconnect and ordinary Back.

The [fresh combined build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37800002372)
packages both startup modes as universal and x86_64 APKs from source
`ae8697b43c23db5559415ac854874db8831b9953`, retaining 19 extensions and the
verified resources. Flutter analysis and all 11 tests pass in four phases.
The build compiles one current AAR after rejecting the restored candidate;
both warm phases compile zero AARs. Both serial Android gates pass on the
API 36 x86_64 1080p emulator. The app gate passes eleven scenarios, including
the corrected in-flight Resume/newer-Records case and actual native unsigned-save
No/Yes touches. The confirmation occupies the native scene without Flet or
keyboard overlap; refusal releases busy state and acceptance restores the real
bookmark without reverting current records. Default save hashes remain
unchanged, and the final default reinstall recovers its original scene and
retains shared records. See [the acceptance record](app-starter-acceptance.md)
for source identities, APK digests, native proof and separate device outcomes.

## Application recipes and promotion review — 2026-10-08

The application batch adds verified Flutter AAR reuse, optional native
dialogue/choice/input/ATL examples, and persistent application records under
Device diagnostics or `sdk-runner:///records`. Records remain independent of
story bookmarks and Replay. The opening checkpoint restores quick-load and
mobile recovery at the first interaction. Default story startup, SDK pins,
the Android host, all 19 extensions, camera exclusion and rollback removal
are preserved.

Promotion review fixes initial records loading after disconnect/close and
requires Reload after rejected native writes, whose cached result may already
contain the attempted record. New host and pinned-Flet regressions reproduce
both defects and verify their recovery paths. The native example path is also
included in main's build triggers.

Local verification passes all 253 prepared-Flet tests without skips, real
story/protocol checks, 500 protocol stress events and stable identities for
14 services across 20 visits. Workflow lint, Python compilation and whitespace
checks pass. The [fresh combined build and Android run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37705147109)
records validation of source `ed48d3116593cf7c85c8073395637a4e3948cde6`.
See [the acceptance record](abc-acceptance.md#promotion-review--2026-10-08) for
reviewed source heads, the preceding APK/device receipts and the promotion.

Android device evidence covers API 36 on the x86_64 1080p emulator. Other ABIs
are verified through packaging; physical ARM performance and release signing
remain outside the completed validation.

## Player rollback source removed — 2026-10-07

The modified Ren'Py component deletes the player rewind implementation,
rollback/roll-forward exports, actions, input mappings, preferences, screen
options and obsolete template/tutorial controls. The runner no longer sets
flags to disable them. The active load-point snapshots and mutable-object
restoration remain for save/load; earlier completed interactions are pruned.
Story history remains readable. The SDK archive includes these source changes
and omits stale compiled copies of modified/deleted sources.

Local verification passes 165 host Python cases (20 prepared-Flet cases are
skipped by that command), 55 native checks across seven processes at
1080×1920, and eight original-save compatibility checks across two additional
processes. The SDK source diff removes 2,323 lines overall: 3,313 removed and
990 added. Checks exercise actual native dialogue, menus, text input, timed pauses,
movie cutscenes, mutable state, the saved random sequence, quick/panel/scene
loads, worker/mobile saves and fresh-process recovery. Rewind APIs and actions
must be absent before and after loading. The original SDK also creates a
mobile save that the modified engine must recover in another process. Run
`scripts/check_native_story.py --legacy-renpy-sdk /path/to/original/sdk` to
produce those receipts. The launcher, tutorial and sample game also compile
from a fresh archive extraction.

| Check | Result | Evidence |
| --- | --- | --- |
| Python/Flet regressions | All 185 unique cases pass | [Input CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37641086374); [Runtime CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37641086435) |
| Modified engine | All 55 checks across seven processes pass in CI; eight additional original-save checks pass locally | [Native receipts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37641029320/artifacts/11492213430) |
| Flutter/APKs | Strict analysis and all 11 tests pass; both APKs retain 541 Python resources and 367 common assets from the modified SDK; all 978 shared payload hashes match | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37641029320) |
| Android 36, 1080p | Pass: save/load and recovery, actual audio/video/Lottie/ATL output, 19 story flags, 24 board flags, 21 board pixel probes and four exact picker files | [Device run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37642486955) |

The APK source is `a2907bc38595d3a2357f7d1515832331608738ce`, pinning
Ren'Py component `0d58d1fc5b5fed87cb0f54eb717233d05643f506` and archive
SHA-256 `3da8a585d5af973230e5b1d3e5c38db3987c6e583062c84b3056c862fa8248b0`.
The device confirms Android API 36, x86_64, 1080×1920 and 420 dpi. Its
final diagnostics are empty. Quick save/load, native-scene loading and
background recovery restore progress correctly after the rewind removal.
Audio plays and resumes at 440 Hz (RMS about 0.053016), with zero RMS while
paused; video, Lottie and native ATL motion pass their pixel checks.
The common-asset count decreases by two because obsolete compiled copies are
removed. All resources in the modified SDK's packaging inventory are verified.

| APK | Bytes | SHA-256 |
| --- | --- | --- |
| Universal | 601261733 | 84cb4f89db18632f78e0da995c88ea601e94c125c4695720ad08799c8d45ec10 |
| x86_64 | 229868817 | 34957cb09e0669a0f03086e265187dd9c7f80ee35d5e4719ec02591cda86ef39 |

## Camera, media, animation and native rendering — 2026-10-07

Phone-camera permission and hardware declarations are removed at Android
manifest merging, so plugins cannot reintroduce them. APK assembly and the
installed-package check reject CAMERA permission. The permission button and
unused authentication/status probes are removed. The fixed SDK extension
catalog and component archives remain intact.

The audio fixture is a real 440 Hz tone at audible volume. Audio and video loop
until explicitly paused. Device CI enables
emulator audio output and captures fresh virtual sound-card PCM, requiring the tone
during play/resume and its absence during pause. The video fixture has changing
frames; the Lottie fixture has a moving light. Pixel samples must change during
playback, remain fixed during pause and change after background/resume.
Native Ren'Py ATL motion is checked in real framebuffer pixels, including
return from menus and Android backgrounding.

The native board caches one completed raster until positions, selection,
revision, view settings or viewport change. Native surfaces stay outside saves.
Color, alpha, movement, picking, view controls and recovery checks remain
required. The SDL construction probe compares forced repaint with reuse on
15 pairs of calls; see [the measured scope](performance.md#native-board-raster-reuse--2026-10-07).

| Check | Current result | Evidence |
| --- | --- | --- |
| Python regressions | 165 host cases and all 20 prepared-Flet cases pass, 185 unique cases overall | [Input CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37579449144); [Runtime CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37579449120) |
| Real Flet protocol | 500 events across five backend cycles; the same 14 services across 20 visits and collection | Runtime CI, runtime-inspection artifact |
| Actual Ren'Py | 47 checks across six processes pass locally and in CI, including native motion, raster reuse/resize, save exclusion and all existing board checks; 14 board framebuffer probes pass | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37577177193), native-story-check artifact |
| Flutter and APKs | Strict analysis and all 11 Flutter cases pass; both APKs retain 541 Python resources and 369 common Ren'Py assets; 980 shared payload hashes match; CAMERA permission is absent | Same APK build |
| Android output and existing suite | Pass on Android 36 x86_64, 1080×1920, 420 dpi: actual audio/video/Lottie output, native ATL motion, 19 story flags, 24 board flags, 21 board pixel probes, 88 fresh capability passes and four exact picker files | [Device run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37578024114) |

The saved output receipts record a 440 Hz RMS of 0.053016 during both play and
resume, with zero RMS while paused, using fresh 1.2-second PCM windows at
48 kHz. Video and Lottie frame samples change during play and after background
recovery; all three paused samples match for each fixture. Native ATL pixels
move before and after backgrounding. Output checks retain the same process,
and the final diagnostic error map is empty.

The device confirms the prepared image's audio buffer multiplier is 8. The
emulator profile records both original and prepared system-image hashes,
disabled cameras, software graphics and the QEMU WAV renderer. The same run
also passes shared-renderer input, keyboard handling, rotation, deep links,
predictive Back, native-service reuse and durable storage after clean relaunch
and force-stop. Receipts, screenshots and captured audio are in its
`runner-device-check-1080p` artifact.

The APK source is `f8592866968bbe2e6d23a1162d881915073677e6`; the device
harness source is `da847ea62c4c8c3a1af0835522d04bb9d3b63e46`. Their application
build inputs match. Both packages are available from the linked APK build.

| APK | Bytes | SHA-256 |
| --- | --- | --- |
| runner-debug-x86_64.apk | 229892288 | 574e4eb5142b317260e5366e04c7208d72854742e7a254602b548c93e9940a19 |
| runner-debug.apk | 601285204 | 31aeff1117b50a54e9c6f787a44f70f0af92d523059d99d9d75e108d868774fd |

## Scope and retained evidence

The historical full media/service measurements above use Android 36 at
1080p/420 dpi with SwiftShader software graphics. Current signed-release
checks also cover Android 15 / API 35, with the owner's manual Redmi checks
recorded separately above. The app builds with SDK/target 36 and retains its
minimum API 24. Camera, GPS/location and recording remain disabled; maps,
biometrics and ads are deferred by the owner.

Source commits, APK hashes, display settings, UI trees, screenshots, framebuffer
signatures, raw PCM, audio levels, playback positions, native-service identities
and diagnostic receipts are retained in workflow artifacts. Branch verification
accepts an explicit successful build run ID and checks APK source compatibility.

CPU board construction and debug software-emulator frame timings do not
establish physical GPU or ARM speed. The manual Redmi checks establish the
exercised flows, without GPU/performance measurements. Arbitrary media codecs,
Rive assets, flashlight and in-flight service recovery are outside the exercised
fixtures. Builds support externally supplied release signing; validation APKs
use disposable CI test keys. Distribution signing has not been established.

See [capability coverage](flet-flutter-capabilities.md) for the service scope and
[build environment](build-environment.md) for reproduction requirements.
