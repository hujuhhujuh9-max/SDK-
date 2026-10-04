# Flet and Flutter capabilities

The first shared runner included the complete core Flet Python/Dart packages
and Flutter engine, but it omitted the full Flet client's extension registry
and extension Python packages. It also passed an empty assets directory and
did not forward plugin restoration or newer surface-resume callbacks.

The fixed build now includes the same 19 extension packages as the pinned
[Flet 1.0.3 full client](https://github.com/flet-dev/flet/blob/a87ca7fc8a813b9d821858083c7539e8e79ab3ba/client/lib/main.dart).
`runtime/flet_extensions.json` names the fixed Python
packages; `flutter/pubspec.yaml` and `flutter/lib/extensions.dart` include and
initialize their Dart counterparts. Assembly checks the catalog against the
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
| Camera, audio recording, flashlight | `flet-camera`, `flet-audio-recorder`, `flet-flashlight` |
| Charts, maps, data tables, code editor, color pickers, loading indicators | `flet-charts`, `flet-map`, `flet-datatable2`, `flet-code-editor`, `flet-color-pickers`, `flet-spinkit` |
| Lottie and Rive animation | `flet-lottie`, `flet-rive`, including initialization |
| WebView | `flet-webview`, Android platform-view attachment/resume |
| Location and permission requests | `flet-geolocator`, `flet-permission-handler`, Android permission declarations |
| Biometric authentication and secure storage | `flet-local-auth`, `flet-secure-storage`; fragment-compatible SDL Activity and AppCompat theme |
| Ads | `flet-ads`; the debug build uses Google's public test application ID |
| Local images, fonts, media and WebView content | Main's `assets/` is extracted to `flet-assets` and supplied to both Flet sides |

Ren'Py still owns startup and the single Python interpreter. The SDL base-class
patch and the null-safe Android activity-result fix live only on
`sdk/renpy-rapt-8.5.3`, with their original SDL and Ren'Py notices. Main pins
and consumes those patches during assembly, supplies AndroidX dependencies,
and owns the integration. Existing component archives remain unchanged.
Main's original work remains all rights reserved; all extension notices are
retained.

The sample's **Run checks** uses local assets, native service calls, and hardware
support/status queries. **Open file picker** uses Android's system picker and reads the selected native
file in bounded chunks on a worker, reporting its name and byte count.
**Request camera permission** exercises the runtime permission callback.
Application code must request camera, microphone and location permissions when
it uses the respective features; declaration does not grant permission.

The tested Android 35 APK initializes all 19 Dart extensions and imports all
19 Python modules. All 24 capability checks pass, including clipboard, preferences,
secure storage, cross-process storage persistence, native storage paths, authentication support and permission
status, local WebView and audio/video, Python native modules, JNI providers and
worker callbacks through explicit wrappers, Page.run_thread, pubsub, and
asyncio.to_thread, battery, connectivity, wakelock, brightness, accessibility,
haptics, and URL-launch support. Device checks also verify text entry,
picker cancellation and exact binary file selection before and after forced restart,
sharing, camera permission callbacks, rotation,
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

The capability page reuses nine services, including one audio player. Core checks
also keep one page-owned set of seven services: battery, connectivity, wakelock,
brightness, semantics, haptics and URL launching. Guards prevent overlapping
checks/pickers across views, and the audio-loaded event survives reentry.
The prepared-Flet probe requires the same 16 IDs across 20 visits and collection.
Native reentry checks require the same seven core IDs and exactly one native
initialization of each, alongside one audio initialization across three visits.
These are service/player creation counts; native memory and FPS gains are unmeasured.

Flet's cleanup accounts for actual protocol snapshot references instead of
assuming every service has been mounted. A service with one application-held
reference remains registered after collection; unowned services still leave
the registry and weak session index. Early cleanup skips native updates before
attachment. The component patch remains on `sdk/flet-1.0.3` and is pinned by
main; prepared-Flet tests cover early and mounted ownership and release.

Device CI runs the full suite at 720p/280 dpi and 1080p/420 dpi, with the same
logical display size. Each invocation scrolls to the local SVG and bar chart,
requires full fixture heights and checks their expected colors within semantic
bounds, saving screenshots.
The bar fixture verifies two colored bars, rather than every chart operation.

The WebView check verifies local content loading and its title. Audio and video
checks use muted local media and verify loading, positive duration, and
play/pause calls. Audible output and decoded video-frame fidelity are outside
this evidence. Authentication and URL launching use support queries; haptics
checks completion of the native channel call.

The main-owned fullscreen host lays out both renderers above the software
keyboard and translates the already-handled inset for embedded Flutter. Native
checks require a fully visible input field before tapping and visible focused
bounds above the keyboard afterward, then require a fresh Python text callback.
The normal renderer split returns when the keyboard closes. Android 35 is the
tested IME path.

Predictive Back remains enabled. The test verifies fresh started, progressed,
and committed callbacks from a real swipe after SDL's immersive navigation
bars are revealed. Incoming links claim Flutter input, and a gesture's screen
position selects the active renderer. Clean Ren'Py-owned shutdown and fresh
Android relaunch pass; the native-service suite runs again after clean and forced cold launches
to verify plugin reattachment. Four invocations across three processes produce
96 fresh capability passes per profile (192 total), and four picker files per
profile match their supplied bytes. Both renderers and the shared counter continue
working after navigation and relaunch. All three tested launches reported Flutter's
Impeller OpenGLES backend.

Extension inclusion is broader than device validation. Actual biometric
authentication, camera capture, recording, GPS, flashlight, ads, and animation
assets need suitable-device tests. Physical ARM execution, arbitrary
in-flight process-death recovery, game-state restoration, and advanced GPU paths remain unverified. The split
view is an integration sample. Desktop/web-only operations retain upstream's
Android limitations, and optional Python/native libraries such as Matplotlib,
NumPy, and Plotly/Kaleido are not added by enabling Flet charts.
No second Serious Python interpreter is introduced.

Release signing remains unconfigured. Before building production ads, supply
the product owner's AdMob application ID in the release manifest; the test ID
is in `src/debug` only. The debug build is the supported build target here.
See [validation.md](validation.md) for recorded build and device results and
[performance.md](performance.md) for lifecycle fixes and measured protocol/frame scopes.
