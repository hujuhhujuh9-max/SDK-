# Project capabilities example

This project composes five independently documented interfaces. Its registration
hook adds a notebook and detail page, a project Python/Dart pulse component,
Canvas and editable table pages, and saveable Canvas/Rive story activities.
It requires no SDK route or extension registry edits.

```sh
.android-build/venv/bin/python examples/capabilities/create.py .android-build/project-capabilities
.android-build/venv/bin/python build_android.py --project .android-build/project-capabilities/renfletpy.json
```

Open **Capabilities lab**. In **Project notebook**, enter a draft, select Rowan
and open the lighthouse entry. Back keeps the draft and selection. Start the
notebook story, open Menu and Return; the same notebook remains. An existing
story prompts before replacement. Records and Saved games use the same screen
registration/state interface.

In **Project pulse dial**, tap the ring, change intensity, pause/resume, remove
and recreate the component. The plain selection and working note belong to the
navigation session. Flutter owns and disposes its painter, ticker and asset
load. The package is selected by this project's manifest; adding it requires
an APK rebuild. Its typed event/lifecycle callbacks produce bounded diagnostic
records for the device fixture.

The story uses Ren'Py's ordinary project `config.label_overrides` to select its
own recipe. It renders ATL animation, compositing and custom shader passes,
then waits for a Canvas activity and a Rive console. Pan/zoom and saved Rive
number/boolean values are game data. Quick save, named saves and Android
background recovery retain these models; controls and services are rebuilt.
At 100% transmission progress, **Send signal** fires a real Rive trigger. Its
typed event returns a completed result to native code and then the app.

The project-only native observer records actual committed/restored activity
models and owning-thread results. It is acceptance instrumentation outside the
saved Ren'Py store, not an alternate command or save path.

The opt-in **Verify integrated app recipes** workflow input
`verify_project_capabilities: true` builds this project and runs
`scripts/check_project_capabilities.py` on an API 35 emulator. APKs, screenshots,
logs and a successful nonempty receipt are separate artifacts. A failed or
unavailable device run does not count as Android proof.

See the [batch receipt](../../docs/project-capabilities-batch.md) for integrated
source/build/check identities and [2D acceptance](../../docs/2d-acceptance.md)
for predefined sizes and the physical phone gate. Emulator and Linux checks
establish only the operations they exercise; physical API 35 performance
requires the release build and raw device measurements.
