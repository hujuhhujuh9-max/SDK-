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
Table **Filter / sort** scans the entire model off the Flet loop. The newest
request supersedes older work, and disposal ignores late worker results.

Workload sizes, phone limits and evidence decisions are defined in
[workloads.json](workloads.json) and [2D acceptance](../../docs/2d-acceptance.md).
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
