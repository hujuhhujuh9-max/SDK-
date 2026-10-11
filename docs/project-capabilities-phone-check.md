# Manual phone measurement handoff

Physical phone operation belongs to the user. AI validation uses the API 35
emulator. Emulator checks establish functionality; the physical performance
status remains unverified until the raw measurements satisfy
[2D acceptance](2d-acceptance.md).

Use the build and successful emulator receipt recorded in the
[batch receipt](project-capabilities-batch.md). A harness correction may rerun
the emulator separately while retaining exactly the same source-compatible APK.
Both inventories must record the same SDK source and project input hash.

- `project-capabilities-release-apks`: use
  `runner-org-renfletpy-capabilities-release.apk` on the ARM64 phone and retain
  `apk-builds-org-renfletpy-capabilities-release.json`.
- `api35-project-capabilities-check`: retain the successful
  `capabilities-device.json` and its complete directory of referenced raw files.

The [successful API 35 artifact](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38142196387/artifacts/11702514282)
contains that receipt and all 100 sealed app files. Its untouched download
passes raw-file revalidation and records zero skipped checks. Keep the files
together; the verifier resolves paths relative to `capabilities-device.json`.

The current signed release is available in
[build 38135327048](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/38135327048/artifacts/11701074306).
Its universal APK SHA-256 is
`cddf35af12800e31240df394887c24f601826f78434d3d1b723b89a0fb3de765`.
The recorded SDK source is `14eb81c8eae439357b8d1f5449a51106e82038b9`;
the project input SHA-256 is
`195e081e6997f6a4379c0f9a9840018804d25f011bbacfcee66e0583ba8aad3e`.

The release APK uses a disposable CI test signing key. It is a measurement
fixture. Updates from a different CI run may require uninstalling the earlier
fixture because the test key changes. Retain any desired fixture saves first.

Use Python 3.12+ on the collection host, a physical ARM64 Android API 35 phone,
a 1080 × 1920 display fixed to 60 Hz, ADB and Perfetto's
`trace_processor_shell`. Check out the source commit recorded
in the APK inventory. Install the release APK and open **Capabilities lab**.
The package is `org.renfletpy.capabilities`.

Run the commands in the [2D example](../examples/2d/README.md#physical-collection)
with that APK and package. Each output directory must be new. Choose observed
tap/pixel coordinates and uniquely matched SDL or Flutter layer names from the
actual phone; placeholders are not measurements.

For this combined project, replace the generic example's package with
`--package org.renfletpy.capabilities` and its startup target with
`--control 'Capabilities lab'` in every applicable collector command.

1. Collect three separate 30-second frame windows after five seconds of warm-up
   for nominal Ren'Py, Canvas, table and Rive. Canvas **Run 35s** and alternating
   table swipes provide motion. Native ATL runs continuously. In the Rive story
   activity, keep **Play the forest and looping rover** enabled; all three
   native readiness callbacks must have appeared. Inspect each trace's
   `layers.csv` and use a uniquely matched surface for the relevant renderer.
2. Collect at least 20 visible-input samples for both Canvas and table, using
   their **Probe input** control's solid acknowledgement pixel.
3. Collect five force-stopped launches using the enabled **Capabilities lab**
   control as the visible startup target.
4. Record baseline and final PSS samples around ten complete app → story →
   native animation → Canvas → Rive → app cycles. Create a bounded cycle plan
   from the phone's observed controls. The verifier also requires ten distinct
   native completion revisions; planned taps alone do not count as cycles.
5. Pass all 16 raw bundle directories (12 frame windows, Canvas and table input,
   startup and memory) and the retained emulator functionality
   receipt to `scripts/check_2d_evidence.py`. Preserve its output together with
   the traces, screenshots, logs and hashes.

The fixed limits are p95/p99 presentation intervals of 20/50 ms, jank ≤ 5%,
visible-input p95 ≤ 150 ms, cold-start p95 ≤ 4 seconds, process PSS ≤ 350 MiB,
ten-cycle retained growth ≤ 20 MiB and thermal severity ≤ 2. Every required
window must pass. Stress sizes have a separate evidence status and cannot be
inferred from nominal measurements. Missing or mismatched raw evidence remains
unverified; an eligible measurement exceeding a limit fails.
