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
support/status queries. **Open file picker** uses Android's system picker.
**Request camera permission** exercises the runtime permission callback.
Application code must request camera, microphone and location permissions when
it uses the respective features; declaration does not grant permission.

The tested Android 35 APK initializes all 19 Dart extensions and imports all
19 Python modules. All 20 capability checks pass, including clipboard, preferences,
secure storage, native storage paths, authentication support and permission
status, local WebView and audio/video, Python native modules, JNI providers and
worker callbacks, battery, connectivity, wakelock, brightness, accessibility,
haptics, and URL-launch support. Device checks also verify text entry,
picker cancellation, sharing, camera permission callbacks, rotation,
background/resume, ordinary Back, and implicit cold/warm deep links.

The WebView check verifies local content loading and its title. Audio and video
checks use muted local media and verify loading, positive duration, and
play/pause calls. Audible output and decoded video-frame fidelity are outside
this evidence. Authentication and URL launching use support queries; haptics
checks completion of the native channel call.

Predictive Back remains enabled. The test verifies fresh started, progressed,
and committed callbacks from a real swipe after SDL's immersive navigation
bars are revealed. Incoming links claim Flutter input, and a gesture's screen
position selects the active renderer. Clean Ren'Py-owned shutdown and fresh
Android relaunch pass; the native-service suite runs again in the new process
to verify plugin reattachment. Both renderers and the shared counter continue
working after navigation and relaunch. Both tested launches reported Flutter's
Impeller OpenGLES backend.

Extension inclusion is broader than device validation. Actual biometric
authentication, camera capture, recording, GPS, flashlight, ads, and animation
assets need suitable-device tests. Physical ARM execution, arbitrary
process-death recovery, and advanced GPU paths remain unverified. The split
view is an integration sample. Desktop/web-only operations retain upstream's
Android limitations, and optional Python/native libraries such as Matplotlib,
NumPy, and Plotly/Kaleido are not added by enabling Flet charts.
No second Serious Python interpreter is introduced.

Release signing remains unconfigured. Before building production ads, supply
the product owner's AdMob application ID in the release manifest; the test ID
is in `src/debug` only. The debug build is the supported build target here.
See [validation.md](validation.md) for recorded build and device results.
