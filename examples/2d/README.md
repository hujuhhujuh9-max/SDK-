# 2D Lab

This opt-in project registers its app screens and saveable Canvas activity with
`project_setup`. Its native story adds ATL animation, compositing and original
shaders, then starts Canvas and interactive Rive activities before returning to
the application. The default SDK story remains available in normal projects.

Create it from the integrated SDK checkout:

```sh
python examples/2d/create.py /tmp/2d-lab
```

The generated project retains the normal SDK story controls, Records and Saved
games. Open **2D Lab**, enter a Journey draft, visit Canvas or Tables and start
the story. In Story Canvas, pan, zoom and select a node; save halfway, close,
reopen and load. **Return selection** returns camera, selected node and input
count; **Cancel Canvas** returns an explicit user cancellation. Complete the
Rive console by adjusting its saved values and firing its event. Return to the
app to inspect the retained Journey draft and screen state. App drafts belong
to the running application session; story saves contain activity game values.

Screen routes are `/app/2d`, `/app/2d/canvas`, `/app/2d/table`,
`/app/2d/canvas/stress` and `/app/2d/table/stress`. Native stress is selected by
`call sdk_scale_animation("stress")`. The normal journey uses nominal sizes.
Canvas **Run 35s** supplies five warm-up seconds and 30 seconds of motion;
**Stop motion**, route removal and Start story cancel that transient task.
The Canvas holds the entire drawing world inside a clipped 320 × 240 viewport;
its top-left camera transform lets pan and zoom reveal distant nodes.
Story Canvas uses `ActivityView` to retain its controls and cumulative gesture
tracking across ordinary native updates. An earlier acknowledgement cannot
overwrite a newer queued camera change. Removal and loading dispose the old
presentation; a new activity revision reconstructs it from saved game values.
Table **Filter / sort** scans the entire model off the Flet loop. The newest
request supersedes older work, and disposal ignores late worker results.

Rive uses three controllers: the controlled forest, the event signal and a
rover playing `bouncing`. The rover supplies sustained motion after the forest
settles. **Play the forest and looping rover** stores the `downloading` game
boolean; off freezes playback and on starts the loop. Reconstruction derives
playback from that saved value. Readiness comes from the native controllers,
and the raw functionality gate checks rover pixels while playing, paused,
resumed, restored frozen and restored playing, plus all three disposals.

Workload sizes, phone limits and evidence decisions are defined in
[workloads.json](workloads.json) and [2D acceptance](../../docs/2d-acceptance.md).
Profile `physical-api35-60hz-v2` adds the rover before phone measurements; its
performance limits retain the original values.
Controls, Paints, native displayables and query workers are reconstructed rather
than saved. Rive assets and their original license notices come from the
[Rive example](../rive/README.md).

Fast host verification uses the real pinned Flet protocol:

```sh
python scripts/check_2d_protocol.py --flet-root /path/to/prepared/flet
python scripts/bench_2d_host.py --flet-root /path/to/prepared/flet --output /tmp/2d-host
python scripts/check_2d_native.py --renpy-sdk /path/to/renpy-8.5.3-sdk --xvfb /path/to/Xvfb --output /tmp/2d-native
```

These commands produce functional native screenshots and host construction,
serialization, callback and worker costs. They do not measure Android layout,
GPU frame timing or physical phone responsiveness. Physical API 35 performance
is unverified until the raw-device collection gates pass.

## Recorded Linux evidence

The retained [protocol samples](evidence/host-protocol.json) used real Flet
1.0.3 with five repetitions and 20 inputs per repetition on an Intel Xeon
8573C cloud host with a two-CPU cgroup quota. Costs include Python model
traversal, patch generation and MessagePack; concurrent cloud load varies.

| Workload | Construction p50 | Initial patch p50 | Input protocol p50 / p95 |
| --- | ---: | ---: | ---: |
| Canvas nominal | 10.94 ms | 57.09 ms | 17.37 / 25.06 ms |
| Canvas stress | 52.91 ms | 312.33 ms | 99.92 / 183.63 ms |
| Table nominal | 61.36 ms | 166.61 ms | 42.49 / 77.07 ms |
| Table stress | 190.95 ms | 646.58 ms | 104.11 / 211.53 ms |

Peak benchmark process RSS was 74.29 MiB. These samples include the Canvas
world-bounds and retained-view corrections and retain the exact source fingerprints. They show expensive
stress cases and do not establish 60 FPS or phone responsiveness at either
tier. Full samples, environment and exact source-file fingerprints are retained.

[Native evidence](evidence/native/results.json) records five successful checks
in two distinct Ren'Py processes using Mesa llvmpipe, with retained screenshots.
Motion changed 10,470 of 10,725 sampled drawing pixels; static shader on/off
changed 10,351. The second process loaded the halfway bookmark and reconstructed
the live scene. Native elapsed time is the probe duration, not app startup time.
The [combined capabilities example](../capabilities/README.md) adds the reusable
project Flutter component to this app/story/activity journey.

## Physical collection

The user collects physical-phone measurements manually. The AI coordinator
operates emulator functionality checks. Select a nominal workload before
recording; use the same release APK, SDK/project inputs and physical phone for
all performance bundles. Enable **Play the forest and looping rover** for Rive
frame windows; a frozen bookmark cannot satisfy continuous motion. Fix the
display to the declared 60 Hz profile. Each
output directory must be new. Actual pixel/tap coordinates come from the visible
control, and a layer expression must uniquely match an inspected SDL or Flutter
surface in the retained trace. Inspect `layers.csv` after the first recording;
ambiguous or missing surfaces cannot establish a frame result.

```sh
python scripts/collect_2d_device.py --apk /path/2d-release.apk --package com.example.lab2d --serial PHONE --output /tmp/canvas-1 frames --workload canvas --engine flutter --repetition 1 --layer-regex 'EXACT_INSPECTED_LAYER' --trace-processor /path/trace_processor_shell --trigger X Y
python scripts/collect_2d_device.py --apk /path/2d-release.apk --package com.example.lab2d --serial PHONE --output /tmp/canvas-input input --workload canvas --tap X Y --pixel PX PY
python scripts/collect_2d_device.py --apk /path/2d-release.apk --package com.example.lab2d --serial PHONE --output /tmp/startup startup --control '2D Lab'
python scripts/collect_2d_device.py --apk /path/2d-release.apk --package com.example.lab2d --serial PHONE --output /tmp/memory memory --cycles-plan /path/cycle-actions.json
```

Replace coordinates and the layer expression with actual observations. The
combined project's home control is **Capabilities lab**. Repeat frame collection
for windows 1–3 of Ren'Py, Canvas, table and Rive, plus table input collection.
Table windows accept `--swipe X1 Y1 X2 Y2` to alternate actual list scrolling.
Ren'Py ATL and Rive playback supply their own motion. Rive frame collection
belongs in its actual story activity with all three ready callbacks observed.

After collecting all 16 nominal bundles, pass every directory to the verifier:

```sh
python scripts/check_2d_evidence.py \
  /tmp/renpy-1 /tmp/renpy-2 /tmp/renpy-3 \
  /tmp/canvas-1 /tmp/canvas-2 /tmp/canvas-3 \
  /tmp/table-1 /tmp/table-2 /tmp/table-3 \
  /tmp/rive-1 /tmp/rive-2 /tmp/rive-3 \
  /tmp/canvas-input /tmp/table-input /tmp/startup /tmp/memory \
  --trace-processor /path/trace_processor_shell \
  --functionality /path/capabilities-device.json --output /tmp/2d-results.json
```

Cycle plans are JSON arrays of bounded `{"kind":"tap","args":[x,y]}`,
`swipe`, numeric `keyevent`, and `{"kind":"wait","args":[seconds]}` actions
with waits at most five seconds. A plan describes one complete journey; the
collector runs it ten times. Ten distinct native story completion revisions
must appear after the baseline, independently of the planned tap count.

The verifier checks raw device/build/process/workload identity, installed APK
bytes, artifact hashes, thermal observations, distinct surface-frame tokens,
visible input pixels, enabled cold-launch controls and whole-process PSS. It
re-extracts frame CSV from the binary Perfetto trace with fixed SQL. It also
revalidates the combined driver's save archives, owner-thread logs, gesture
values, Rive playback pixels, typed event, lifecycle and actual disposal.
Emulator functionality may accompany physical release measurements from the
same SDK/project inputs; their APKs and hardware scopes remain explicit.
Missing artifacts or tools remain `unverified`, and an eligible limit breach
is `fail`; either returns a nonzero exit code.
