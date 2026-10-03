# Runtime measurements and lifecycle fixes

The integration keeps Ren'Py/SDL as the startup and Python owner. These
measurements describe the fixed sample. A before/after FPS comparison has not
been recorded.

## Work removed

The 200 ms Ren'Py polling timer now restarts screen interaction only when the
shared counter changes. Its Function action disables the default screen
update. Regression checks run 100 unchanged polls without an extra restart,
then require a restart for a changed counter and give shutdown priority.

The Android host sends ordinary hardware keys through its normal view
dispatch once. Android Back keeps the host's existing routing and predictive
gesture callbacks. Dart memory-pressure messages wait until Flutter has
displayed its first frame; native renderer and platform-view trim callbacks
still run.

Flet reconnect timers are cancelled at disposal, late connections are closed,
and late packets/errors leave disposed state alone. Python method waiters are
released after success, errors, timeout, and cancellation; late replies are
ignored. Remounted RawImage producers close their previous channels, and
socket shutdown releases registered channels. These paths have automated
regression coverage. Capability checks also ignore repeated clicks while active
and pause media on failure or cancellation before allowing a retry.

RawImage and Matplotlib canvas patches also skip work after unmount and
dispose native images decoded after disposal. These image guards are
source-inspected and compiled. No deterministic decoder-race reproduction or
image-memory benchmark has been recorded.

The component patches live on `sdk/flet-1.0.3`, pinned at
`3f23214e37e2f443cdeb8abe5da255b0f311b9e3`. Original host code,
tests, and probes live on `main`; component archives and upstream notices
remain intact.

## Linux protocol stress

[Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37127007128)
used main source `46cf41161cf75050737ed763862f272b37f236a9`,
Python 3.12.3, four reported CPUs, and
`Linux-6.17.0-1022-azure-x86_64-with-glibc2.39`.

Each cycle starts the real pinned Flet socket server, registers a page,
sends 100 Increment events, and requires a fresh matching UI patch after each
event. It verifies the exact shared counter, observes no protocol messages
during a 250 ms idle window, and joins the backend thread at shutdown.
All 500 events and five start/stop cycles passed. The same run executed all
15 prepared-Flet lifetime tests with zero skips, imported all 19 Python
extensions, and checked shutdown during startup.

Times are milliseconds and percentiles use the nearest-rank method.

| Cycle | Events | Startup | Shutdown | Event p50 | Event p95 | Event max |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 100 | 98.673 | 1.556 | 0.576 | 0.623 | 0.815 |
| 2 | 100 | 12.414 | 1.551 | 0.534 | 0.585 | 0.702 |
| 3 | 100 | 12.266 | 1.540 | 0.540 | 0.573 | 0.711 |
| 4 | 100 | 12.452 | 1.550 | 0.534 | 0.572 | 0.713 |
| 5 | 100 | 12.647 | 1.490 | 0.574 | 0.678 | 1.004 |

Event latency measures Linux UDS event submission through the resulting UI
patch. It excludes Android input, Flutter rendering, SDL rendering, and
network delivery. Startup includes connection and initial controls; the first
cycle also includes first imports. CI worker variation affects these numbers.

[Measurement JSON and source receipt](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37127007128/artifacts/11274692659)
are retained as workflow artifacts.

## Android debug frame baseline

Two fresh Android 35 x86_64 CI emulator runs used the same debug APK, Flutter
Impeller OpenGLES, and SwiftShader software graphics. Each profiling window
contains 20 additional Increment clicks, ending with Count 21 in the Flet UI,
the same process's Ren'Py counter marker, and a valid SDL framebuffer. The
unhandled F1 probe reports one down, one up, zero repeats, and no synthesized
events.

| Run | Recorded frames | Window seconds | Build p50 / p95 ms | Raster p50 / p95 ms | Total span p50 / p95 ms | Samples above 16.667 ms |
| --- | --- | --- | --- | --- | --- | --- |
| [37128748428](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128748428) | 50 | 9.510 | 8.061 / 50.892 | 47.524 / 131.047 | 123.342 / 227.870 | 47 |
| [37128819256](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128819256) | 52 | 9.235 | 7.736 / 42.438 | 42.635 / 118.860 | 102.792 / 216.943 | 50 |

The debug collector retains at most 600 timing samples; neither run dropped
samples. It collects Flutter timing callbacks received between start and stop
and uses nearest-rank percentiles. Total span and build/raster durations are
different measurements. The nominal 16.667 ms reference is a 60 Hz budget,
not a measured display rate.

These frame times are high, especially raster time, in the debug software
emulator. They provide a reproducible baseline to investigate further.
They do not characterize release speed or physical GPU performance, and
neither series contains SDL frame timings. Both runs use the same APK.
The single dumpsys memory snapshot records process state, rather than a
memory-leak trend.

The host's profiling intent commands require an Android debuggable app;
Dart installs timing and F1 callbacks only in debug mode. No timing collection
runs in a release build.

[First device artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128748428/artifacts/11274899839)
and [repeat artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128819256/artifacts/11275922512)
include `flutter-frame-profile.json`, `profile-memory.txt`, framebuffer
samples, logcat, UI trees, SystemUI gesture state, and source receipts.
