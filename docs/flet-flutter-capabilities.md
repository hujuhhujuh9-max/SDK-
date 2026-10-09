# Flet and Flutter capabilities

The first shared runner included the complete core Flet Python/Dart packages
and Flutter engine, but it omitted the full Flet client's extension registry
and extension Python packages. It also passed an empty assets directory and
did not forward plugin restoration or newer surface-resume callbacks.

The fixed build now includes the same 19 extension packages as the pinned
[Flet 1.0.3 full client](https://github.com/flet-dev/flet/blob/a87ca7fc8a813b9d821858083c7539e8e79ab3ba/client/lib/main.dart).
`runtime/flet_extensions.json` names the fixed Python
packages; `flutter/pubspec.yaml` and `flutter/lib/extensions.dart` include and
register their Dart counterparts. Release builds skip automatic ads
initialization because the example has no advertising identity or flow.
Assembly checks the catalog against the
original client's imports and fails if a paired package is missing.

Both the universal and emulator APKs retain this full catalog and the same
Python packages, assets and notices. APK inspection requires exactly the
19-extension catalog; missing metadata fails before device checks. The build
verifies identical hashes for shared payloads, including the retained native
libraries. The emulator APK omits native libraries for unused ABIs. The latest
Android check ran the x86_64 APK; physical ARM execution remains unverified.

| Capability | Integration |
| --- | --- |
| Core controls, layout, themes, events, navigation, keyboard, clipboard, files, preferences, sensors and storage services | Original Flet packages and Flutter plugins retained |
| Audio and video | `flet-audio`, `flet-video`; their native Android libraries are included |
| Phone camera | Package retained in the fixed SDK catalog; CAMERA permission and camera hardware features removed during manifest merging, emulator cameras disabled |
| Audio recording | `flet-audio-recorder` retained; microphone permission and recording foreground-service permission removed during manifest merging |
| Flashlight | `flet-flashlight` retained; hardware behavior unverified |
| Charts, maps, data tables, code editor, color pickers, loading indicators | `flet-charts`, `flet-map`, `flet-datatable2`, `flet-code-editor`, `flet-color-pickers`, `flet-spinkit` |
| Lottie and Rive animation | `flet-lottie`, `flet-rive`, including initialization |
| WebView | `flet-webview`, Android platform-view attachment/resume |
| GPS/location | `flet-geolocator` retained; location permissions, hardware declarations and its location service removed during manifest merging |
| Permission requests | `flet-permission-handler`; camera, location and recording permissions remain blocked |
| Biometric authentication and secure storage | `flet-local-auth`, `flet-secure-storage`; fragment-compatible SDL Activity and AppCompat theme |
| Ads | `flet-ads`; debug uses Google's public test application ID, release does not initialize ads |
| Local images, fonts, media and WebView content | Main's `assets/` is extracted to `flet-assets` and supplied to both Flet sides |

## Extension status and next jobs

In this table, **Yes** means the paired Python package and Dart extension are
packaged and registered. All 19 Python imports and debug Dart initializations
are required by the Android suite; release omits eager ads initialization.
That evidence establishes availability, not
every operation of an extension. The tested scopes below refer to the existing
fixtures and the recorded Android 36 x86_64 profile; the detailed evidence
later in this document and [validation.md](validation.md) remains authoritative.

| Package | Packaged / registered | Current sample use | Tested scope | Exclusion or next prerequisite |
| --- | --- | --- | --- | --- |
| `flet-ads` | Yes | Debug test application ID; no ad screen | Import / debug initialization | Release ads disabled; an opt-in flow needs owner ID, initialization and output checks |
| `flet-audio` | Yes | Local audio player | Duration, audible tone, play/pause/resume, service reuse | Other sources/codecs and physical audio output unverified |
| `flet-audio-recorder` | Yes | Recording disabled | Package retained; APK permission absence checked | Intentionally disabled by the owner; no recording work planned |
| `flet-camera` | Yes | No camera flow | CAMERA permission absent in APK and installed package | Intentionally blocked; preserve the camera restriction |
| `flet-charts` | Yes | Local two-bar chart | Fixture height and two bar colors | Other charts and interactions need their own fixtures |
| `flet-code-editor` | Yes | JSON editor applies bounded sample rows | Real pinned-Flet events, validation and encoded results | Android keyboard/output evidence required by the recipe device gate |
| `flet-color-pickers` | Yes | BlockPicker with live color preview | Real opaque ARGB events and selected-color output | Other picker types and arbitrary color operations need their own fixtures |
| `flet-datatable2` | Yes | Bounded table with sorting and single selection | Real typed sort events, bool selection and changed row output | Android interaction evidence required by the recipe device gate |
| `flet-flashlight` | Yes | No torch flow | Import / initialization | Torch hardware and compatibility with the camera-permission restriction |
| `flet-geolocator` | Yes | GPS/location disabled | Package retained; APK permission/service absence checked | Intentionally disabled by the owner; no GPS work planned |
| `flet-lottie` | Yes | Local animation | Play/pause/resume pixels, including background/resume | Other assets and operations unverified |
| `flet-local-auth` | Yes | Compatible host and permissions; no authentication flow | Import / initialization | Enrolled authentication fixture, cancel/unavailable paths and physical device |
| `flet-map` | Yes | No map screen | Import / initialization | Tile source or licensed offline fixture; provider requirements and attribution |
| `flet-permission-handler` | Yes | No permission-request UI | Import / initialization | Named non-camera permission flow with grant/deny checks |
| `flet-rive` | Yes | No Rive fixture | Import / initialization | Redistributable asset and known state-machine/input fixture |
| `flet-secure-storage` | Yes | Storage checks | Set/get and cross-process persistence before writes | Other operations and arbitrary in-flight recovery unverified |
| `flet-spinkit` | Yes | ThreeBounce during cancellable sample loading | Pending/completed/failure/cancel states and retired-result guards | Android gate requires painted pending output; animation timing is not measured |
| `flet-video` | Yes | Local MediaCodec video | Duration, changing/paused pixels and background/resume | Other codecs/sources and physical output unverified |
| `flet-webview` | Yes | Local HTML asset | Loading/title and platform-view lifecycle | External web applications and other WebView operations unverified |

Core Flet controls and services are separate from this extension catalog.
The existing checks cover clipboard, preferences, storage paths, picker,
sharing, text input, navigation and the core-service calls described below.
A completed haptics channel call does not establish physical vibration;
a URL support query does not establish every external application launch.
Physical ARM execution and GPU performance require separate device evidence.

The reusable control page below uses the already packaged editor, table, color
picker and loading indicator, with observable callback results. Reusable modules
remain at the top level of `runtime/`, which the current build copies into the APK,
and use the pinned Flet API.
Follow-on service jobs should add one named operation, its denial/cancel or
unavailable behavior, and the relevant fixture. Authentication, ads and Rive
have prerequisites in the table; they are separate optional jobs. Recording
and GPS are deliberately disabled and are not part of the remaining roadmap.
Flet callbacks must keep story progression and save/load on Ren'Py's thread.
Phone-camera access, GPS/location and recording stay blocked; player rollback
stays removed.

## Reusable control recipes

Open **Application recipes** from app Home or Diagnostics. App mode uses
`/app/recipes` and Back returns home; `/recipes` returns to Diagnostics. Both
support query links and full-page keyboard input. The story-first startup remains
the default. These sample values are independent of persistent Records and native
bookmarks; leaving the page or reconnecting starts a new sample visit.

`runtime/app_recipes.py` exposes `create_app_recipes_view(page, route=...,
on_back=..., is_current=..., load_sample=...)`, returning an unmounted Flet View
and an idempotent synchronous disposer. The caller mounts the View, supplies a
current-view/lifecycle guard, and calls the disposer on departure or disconnect.
Same-path query changes retain the mounted View and its editor/table state.
The optional async loader returns plain rows; disposal and operation generations
prevent stale callbacks or results from publishing to a newer visit.

- **Editor** uses CodeEditor with JSON highlighting. Apply validates a list of
  one to eight unique name/count objects and replaces table rows. Names are
  valid Unicode, at most 80 characters; counts are integers from 0 to 999;
  source is bounded to 4096 characters. Errors retain the source and prior data.
- **Table** uses a finite-height DataTable2. Name/Count headings reorder actual
  rows; selecting a row reports its name. Replaced rows reject stale callbacks.
- **Color** uses BlockPicker with three opaque choices. Its native ARGB event
  updates the displayed hex value and a bounded preview rectangle.
- **Loading** uses ThreeBounce while an async request is pending. The sample
  waits eight seconds to make the loading state observable, then returns three
  rows. Replace `load_sample` for actual data work. Cancel, retry and failures
  release controls; a cancelled loader cannot overwrite a later request.

`scripts/check_app_recipes.py --flet-root <prepared-flet>` runs the actual pinned
extension controls and encoded Flet events without skips. The existing Android
suite also calls `scripts/app_recipes_device_checks.py` in each startup mode.
It requires native keyboard input, changed table order/selection, picker and
preview pixels, a painted pending indicator, completion, cancel/retry and
departure during pending work. The `app-recipes.json` receipt must match the
inspected APK's source, mode, hash and ABI. This covers the sample operations;
other editor languages, picker types and loading animation timing are separate
scopes. Fresh source, APK and device receipts are published by the
[combined main workflow](https://github.com/hujuhhujuh9-max/SDK-/actions/workflows/integration-abc.yml?query=branch%3Amain).

Flutter's Dart API and plugin ecosystem are broader than the Python API exposed
by Flet. If a required Android-supported operation is absent from pinned Flet,
a small Dart/Flet extension may be needed. Adding it requires coordinated
Python/Dart packaging, registry and APK-inventory work: the current checks
enforce the fixed 19-extension catalog. An existing Flet API that lacks a sample
screen needs application code. SDK source changes need a demonstrated component
or embedding defect. See [parallel development](parallel-development.md) for
agent ownership and integration order.

Ren'Py still owns startup and the single Python interpreter. The SDL base-class
patch and the null-safe Android activity-result fix live only on
`sdk/renpy-rapt-8.5.3`, with their original SDL and Ren'Py notices. Main pins
and consumes those patches during assembly, supplies AndroidX dependencies,
and owns the integration. Existing component archives remain unchanged.
Main's original work remains all rights reserved; all extension notices are
retained.

The sample's **Run checks** uses local assets and native service calls.
**Open file picker** uses Android's system picker and reads the selected native
file in bounded chunks on a worker, reporting its name and byte count.
There is no camera permission button. Both APK builds and installed-package
checks reject CAMERA permission. GPS, biometric authentication and recording
are outside this phase's tests.

The Android suite requires initialization of all 19 Dart extensions and imports all
19 Python modules. The current suite requires 22 fresh capability receipts,
including clipboard, preferences, secure storage, cross-process storage
persistence, native storage paths, local WebView and audio/video, Python native modules, JNI providers and
worker callbacks through explicit wrappers, Page.run_thread, pubsub, and
asyncio.to_thread, battery, connectivity, wakelock, brightness, accessibility,
haptics, and URL-launch support. Device checks also verify text entry,
picker cancellation and exact binary file selection before and after forced restart,
sharing, rotation,
background/resume, ordinary Back, implicit cold/warm deep links with query
strings, root-link navigation, and exactly one delivery of an unhandled
hardware key's down/up events.

The host supplies an APK-class-loader-aware executor to Flet's socket transport,
Page.run_thread, synchronous pubsub handlers, and the asyncio default worker
pool. The device suite performs distinct first class lookups, verifies worker
context loaders, and invokes an AndroidX Consumer callback on each path.
Python and native storage paths agree for data, cache, and temporary files.
A unique synthetic challenge is read from files, preferences and secure storage
before any write on later visits. Clean exit and force-stop both preserve it.
Receipts must come from the fresh process and match the original digest;
missing/mismatched evidence fails rather than being repaired.

The capability page reuses seven services, including one audio player. Core checks
also keep one page-owned set of seven services: battery, connectivity, wakelock,
brightness, semantics, haptics and URL launching. Guards prevent overlapping
checks/pickers across views, and the audio-loaded event survives reentry.
The prepared-Flet probe requires the same 14 IDs across 20 visits and collection.
Native reentry checks require the same seven core IDs and exactly one native
initialization of each, alongside one audio initialization across three visits.
These are service/player creation counts; native memory and FPS gains are unmeasured.

Flet's cleanup accounts for actual protocol snapshot references instead of
assuming every service has been mounted. A service with one application-held
reference remains registered after collection; unowned services still leave
the registry and weak session index. Early cleanup skips native updates before
attachment. The component patch remains on `sdk/flet-1.0.3` and is pinned by
main; prepared-Flet tests cover early and mounted ownership and release.

Device CI runs the full suite at 1080p/420 dpi. Each invocation scrolls to the
local SVG and bar chart,
requires full fixture heights and checks their expected colors within semantic
bounds, saving screenshots.
The bar fixture verifies two colored bars, rather than every chart operation.

The WebView check verifies local content loading and its title. Media loading
checks require positive duration and release playback on failure or cancellation.
The output probe separately plays a 30-second, 440 Hz WAV at audible volume,
captures fresh PCM from the emulator's QEMU WAV output, and requires the tone during
play/resume and its absence during pause. This captures host audio output and
does not use Android's microphone or recording APIs.
Audio and video fixtures loop until paused, so slow emulator checks do not
release the player or reach a blank final frame midway through a capture.

On Android the video fixture uses MediaCodec's direct surface output, avoiding
an additional mpv EGL renderer in the shared SDL/Flutter process. Native playback
errors are reported through the Python handler and fail output verification.
The video fixture has changing frames. Pixel samples within its semantic bounds
must change during playback, stay fixed during pause and change after returning
from Android backgrounding. The Lottie fixture has the same play/pause/resume
pixel checks. Native Ren'Py ATL animation is checked in the actual framebuffer
on Linux and Android, including return from a menu or backgrounding. These
small fixtures establish the exercised output paths; arbitrary codecs, Rive
assets and every game animation are outside their scope. URL launching uses a
support query; haptics checks completion of the native channel call.

The main-owned fullscreen host lays out both renderers above the software
keyboard and translates the already-handled inset for embedded Flutter. Native
checks require a fully visible input field before tapping and visible focused
bounds above the keyboard afterward, then require a fresh Python text callback.
The normal renderer split returns when the keyboard closes. Android 36 is the
tested IME path.

Predictive Back remains enabled. The test verifies fresh started, progressed,
and committed callbacks from a real swipe after SDL's immersive navigation
bars are revealed. Incoming links claim Flutter input, and a gesture's screen
position selects the active renderer. Clean Ren'Py-owned shutdown and fresh
Android relaunch pass; the native-service suite runs again after clean and forced cold launches
to verify plugin reattachment. Four invocations across three processes require
88 fresh capability passes in the single 1080p profile, and four picker files
must match their supplied bytes. Both renderers and the shared counter continue
working after navigation and relaunch. All three tested launches reported Flutter's
Impeller OpenGLES backend.

Extension inclusion is broader than device validation. The phone camera,
recording and GPS are disabled by product choice. Biometric authentication,
flashlight, ads and Rive need separate tests if a project chooses to use them. Physical ARM execution,
arbitrary in-flight service recovery and advanced GPU paths remain unverified. The split
view is an integration sample. Desktop/web-only operations retain upstream's
Android limitations, and optional Python/native libraries such as Matplotlib,
NumPy, and Plotly/Kaleido are not added by enabling Flet charts.
No second Serious Python interpreter is introduced.

The [project template](project-template.md) supports debug and release APKs,
with optional signing supplied through environment values. Release examples
omit the ads initialization provider and automatic Dart ads initialization.
Production ads require a deliberate opt-in implementation with an owner AdMob
identity; the debug test ID remains in `src/debug` only.
See [validation.md](validation.md) for recorded build and device results and
[performance.md](performance.md) for lifecycle fixes and measured protocol/frame scopes.
