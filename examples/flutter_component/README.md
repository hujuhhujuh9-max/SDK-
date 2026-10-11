# Project pulse component

This example adds a new Flutter component through project metadata. It uses the
existing Flet factory and wire APIs, a custom painter, a local animation ticker,
a package-owned palette asset, typed selection/lifecycle/error events, and
explicit controller/listener cleanup.

Install the normal build dependencies, including the pinned YAML parser, then
create a separate project and build it:

```sh
python3 -m pip install -r requirements-build.txt -r runtime/requirements.txt
python3 examples/flutter_component/prepare_example.py /tmp/project-pulse
python3 build_android.py --project /tmp/project-pulse/renfletpy.json
```

The materializer uses the normal SDK scaffold, retains its native story and
assets, supplies `app/my_app.py`, adds the paired package, and selects
`project_setup="my_app:register"`. The project registers `/app/pulse` without an
SDK routing edit. `extensions` selects the Dart constructor and Python package;
the builder generates registry imports in its private Flutter staging tree.

Open **Open pulse dial**, enter a working note, tap the ring, change intensity,
and pause/resume. Start or resume a story, then use the native story menu's
**Return to app** action. The note and selection remain in the navigation
session model. **Remove component** disposes the Flutter ticker/listeners;
**Recreate component** builds a fresh controller from those same plain values.
Backgrounding pauses its ticker, and foreground resume obeys the current
Python playback property.

The supported manifest and dependency/asset limits are in
[project extensions](../../docs/project-extensions.md). The Flutter tests run
inside the generated SDK module; `registration_test.dart` deliberately imports
that runner's generated registry. Package tests verify changed raster pixels,
property/event flow, package asset loading, errors, background/resume and that
unmounting leaves no tickers or late callbacks. Real pinned-Flet host tests verify
typed wire events and model reconstruction.

The dial's local animation phase is temporary presentation state. Saveable
values are numeric selection/intensity and a playback boolean. Put those in a
registered activity's state when using the component inside a story; controls,
tickers and listeners are rebuilt on restore. This example's screen note is app
state independent of story bookmarks. An APK rebuild is required when adding or
changing the Flutter/native component.
