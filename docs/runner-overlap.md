# Android runner overlap: decision pending

The product contains the fixed modified Flet/Flutter/Ren'Py stack. This page
records the first actual collision; startup ownership remains undecided until
discussion with the project owner.

## What overlaps

The supplied RAPT 8.5.3 launcher is `PythonSDLActivity`, extending SDL's
`SDLActivity`. SDL installs its rendering surface, handles lifecycle/input,
and starts the native Ren'Py runtime. `librenpython.so` exports both `SDL_main`
and CPython initialization symbols. The launcher is selected in the RAPT
Android manifest template.

Flet's Android client uses a `FlutterFragmentActivity`. Flutter has its own
engine, view, and lifecycle attachment. The standard Flet Python packaging
path also bootstraps CPython through Serious Python; starting that alongside
Ren'Py would create two independent Python startup owners.

Flet's Dart widget package supports an embedder-supplied transport and does
not itself depend on Serious Python. Its Python package supports a local
socket server. Those are possible integration seams, not evidence that
embedding already works on Android.

Sources inspected:

- RAPT: `prototype/renpyandroid/src/main/java/org/renpy/android/PythonSDLActivity.java`,
  `prototype/renpyandroid/src/main/java/org/libsdl/app/SDLActivity.java`,
  `templates/app-AndroidManifest.xml`, and bundled JNI libraries.
- [Flet Android client Activity](https://github.com/flet-dev/flet/blob/a87ca7fc8a813b9d821858083c7539e8e79ab3ba/client/android/app/src/main/kotlin/com/appveyor/flet_client/MainActivity.kt).
- [Flet widget and transport hooks](https://github.com/flet-dev/flet/blob/a87ca7fc8a813b9d821858083c7539e8e79ab3ba/packages/flet/lib/src/flet_app.dart).
- [Flet Python startup](https://github.com/flet-dev/flet/blob/a87ca7fc8a813b9d821858083c7539e8e79ab3ba/sdk/python/packages/flet/src/flet/app.py).
- [Serious Python Android implementation](https://github.com/flet-dev/serious-python/tree/v5.0.0/src/serious_python_android).
- [Flutter Android embedding guidance](https://docs.flutter.dev/add-to-app/android).

## Options to discuss

| Startup owner | Integration approach | Work to validate |
| --- | --- | --- |
| Ren'Py/SDL | Keep its Python runtime and lifecycle; embed a Flutter view and run Flet Python in the same interpreter | Flutter plugin Activity attachment, overlapping surfaces/input, socket transport, pause/resume and shutdown |
| Flutter | Let Flutter own startup; adapt Ren'Py/SDL into an embedded runtime and rendering view | Refactor SDL Activity assumptions, native runtime/Python ownership, rendering/input, pause/resume and shutdown |

The first option is the current recommendation because it preserves the
supplied Ren'Py native startup and uses Flet's existing embedding seams.
This is an engineering inference, not a completed compatibility test.
Changing Python versions alone does not resolve Activity, rendering, or
interpreter ownership.

After the decision, the shared host and build assembly belong on `main`.
Changes/removals inside RAPT, Ren'Py, Flutter, or Flet stay on their respective
branches. First device checks must cover both renderers, input focus,
background/resume, orientation, and clean shutdown inside the same APK.
