# Flet and Flutter capabilities

The first shared runner included the complete core Flet Python/Dart packages
and Flutter engine, but it omitted the full Flet client's extension registry
and extension Python packages. It also passed an empty assets directory and
did not forward plugin restoration or newer surface-resume callbacks.

The fixed build now includes the same 19 extension packages as the pinned
Flet 1.0.3 full client. `runtime/flet_extensions.json` names the fixed Python
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
patch and its zlib notice live only on `sdk/renpy-rapt-8.5.3`. Main pins and
consumes that patch during assembly, supplies AndroidX dependencies, and owns
the integration. Existing component archives remain unchanged. Main's original
work remains all rights reserved; all extension notices are retained.

The sample's **Capabilities** page exercises services and local assets without
requesting access to hardware. **Open file picker** uses Android's system picker.
Camera, microphone and location permissions are requested by application code
when it uses the respective features; declaration does not grant permission.

Extension inclusion is broader than device validation. Actual biometric
authentication, camera capture, recording, GPS, flashlight, ads, and animation
assets still need suitable-device tests. Android predictive-back gestures are
currently disabled so the shared host uses its existing back callback. The
split-view layout remains an integration sample. Desktop/web-only operations
retain upstream's Android limitations, and optional Python/native libraries
such as Matplotlib, NumPy, Plotly/Kaleido are not added by enabling Flet charts.
No second Serious Python interpreter is introduced.

Release signing remains unconfigured. Before building production ads, supply
the product owner's AdMob application ID in the release manifest; the test ID
is in `src/debug` only. The debug build is the supported build target here.
See [validation.md](validation.md) for recorded build and device results.
