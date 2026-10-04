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

## Service reuse and file workers

The capability page originally constructed nine services on every visit.
A [prepared-Flet inspection](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37153605168)
recorded 180 service references after 20 visits with cyclic collection disabled;
forced collection then removed them. This was delayed cleanup, rather than a
demonstration of permanent retention.

The page now owns one set of nine services, including one audio player.
A [repeat inspection](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37198120966)
at source `d8e9175e860422015628c1d9707d848e73169e85` requires
the same nine IDs across all 20 open/pop cycles, both before and after collection.
It uses real prepared Flet session, model and service-registry code, with native
route acknowledgements stubbed. Counts remain nine throughout.

Native verification also changed from three audio-player initializations over
three visits in [run 37153138450](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37153138450)
to one in [run 37155109602](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155109602).
The latter repeats all 24 capability checks after reentry in the same process.
The latest [device run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37198912979)
repeats that assertion against the current APK. These are service-reference
and initialization counts; native memory and FPS gains have not been measured.

Picker files are hashed on the worker pool in 64 KiB chunks, without requesting
file bytes in the Flet protocol. A cooperative cancellation signal stops the
chunk loop and closes the stream. Regression checks cancel an active worker,
require it to exit, and verify guard restoration. Four native selections verify
exact fixture bytes before and after force-stop; this is correctness evidence,
rather than a large-file throughput benchmark.

## APK packaging measurement

Both packages come from [build 37198120980](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37198120980)
at source `d8e9175e860422015628c1d9707d848e73169e85`. APK sizes below are bytes before the
Actions artifact ZIP wrapper.

| APK | Bytes | Native ABIs | SHA-256 |
| --- | --- | --- | --- |
| runner-debug.apk | 600,899,260 | arm64-v8a, armeabi-v7a, x86_64 | 4d38cbcfb645ba70167bc250bf04eda1dedbdaa481d8da03c96bec64f13646fb |
| runner-debug-x86_64.apk | 229,506,344 | x86_64 | 7a3d27f900969f1d140fbeeadc7f51b6384c18083e9c9e817f4442978fc9855c |

The x86_64 APK is 61.8% smaller and retains all 19 extensions, 541 prepared
Python package/resource files and 369 Ren'Py common assets. The build compares
979 shared payload entries, including retained native libraries, code, resources
and notices. `apk-builds.json` is included in both artifact downloads.

The second host assembly took 24 seconds in this build; shared-payload hashing
took about five seconds. Producing and uploading an additional artifact adds
build work. The measurement demonstrates fewer bytes for repeated emulator
download/installation, rather than an overall CI latency or runtime FPS gain.

## Linux protocol stress

[Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37198120966)
used main source `d8e9175e860422015628c1d9707d848e73169e85`,
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
| 1 | 100 | 65.341 | 0.847 | 0.376 | 0.399 | 0.600 |
| 2 | 100 | 11.680 | 0.741 | 0.365 | 0.399 | 0.495 |
| 3 | 100 | 11.626 | 0.709 | 0.390 | 0.421 | 0.514 |
| 4 | 100 | 11.573 | 0.810 | 0.385 | 0.420 | 0.549 |
| 5 | 100 | 11.620 | 0.755 | 0.377 | 0.396 | 0.518 |

Event latency measures Linux UDS event submission through the resulting UI
patch. It excludes Android input, Flutter rendering, SDL rendering, and
network delivery. Startup includes connection and initial controls; the first
cycle also includes first imports. CI worker variation affects these numbers.

[Measurement JSON and source receipt](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37198120966/artifacts/11302370156)
are retained as workflow artifacts.

## Android debug frame baseline

The first two Android 35 x86_64 CI emulator runs below used the same debug APK.
Later rows repeat the window with the service-reuse and file-worker fixes.
The latest row uses the x86_64 APK whose shared payload hashes match its
universal counterpart. All use Flutter Impeller OpenGLES and SwiftShader software graphics. Each profiling
window contains 20 additional Increment clicks, ending with Count 21 in the Flet UI,
the same process's Ren'Py counter marker, and a valid SDL framebuffer. The
unhandled F1 probe reports one down, one up, zero repeats, and no synthesized
events.

| Run | Recorded frames | Window seconds | Build p50 / p95 ms | Raster p50 / p95 ms | Total span p50 / p95 ms | Samples above 16.667 ms |
| --- | --- | --- | --- | --- | --- | --- |
| [37128748428](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128748428) | 50 | 9.510 | 8.061 / 50.892 | 47.524 / 131.047 | 123.342 / 227.870 | 47 |
| [37128819256](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128819256) | 52 | 9.235 | 7.736 / 42.438 | 42.635 / 118.860 | 102.792 / 216.943 | 50 |
| [37155109602](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155109602) | 45 | 9.094 | 9.236 / 58.556 | 56.383 / 151.173 | 142.125 / 282.155 | 42 |
| [37157449019](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37157449019/attempts/2) | 54 | 8.688 | 5.487 / 37.033 | 41.789 / 118.769 | 107.393 / 227.247 | 51 |
| [37198912979](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37198912979) | 45 | 8.938 | 10.140 / 54.598 | 51.030 / 120.346 | 134.004 / 239.493 | 43 |

The debug collector retains at most 600 timing samples; none of these runs dropped
samples. It collects Flutter timing callbacks received between start and stop
and uses nearest-rank percentiles. Total span and build/raster durations are
different measurements. The nominal 16.667 ms reference is a 60 Hz budget,
not a measured display rate.

These frame times are high, especially raster time, in the debug software
emulator. They provide a reproducible baseline to investigate further.
They do not characterize release speed or physical GPU performance, and
none of the series contains SDL frame timings. Variation between software
emulator workers and app revisions prevents attributing a frame-rate change
to the lifecycle fixes.
The single dumpsys memory snapshot records process state, rather than a
memory-leak trend.

The host's profiling intent commands require an Android debuggable app;
Dart installs timing and F1 callbacks only in debug mode. No timing collection
runs in a release build.

[First device artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128748428/artifacts/11274899839),
[repeat artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37128819256/artifacts/11275922512),
and [latest device artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37198912979/artifacts/11301702236)
include `flutter-frame-profile.json`, `profile-memory.txt`, framebuffer
samples, logcat, UI trees, SystemUI gesture state, and source receipts.
