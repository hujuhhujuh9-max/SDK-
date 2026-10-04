# Runtime measurements and lifecycle fixes

The integration keeps Ren'Py/SDL as the startup and Python owner. These
measurements describe the fixed sample. A before/after FPS comparison has not
been recorded.

## Work removed

The 200 ms Ren'Py polling timer now restarts screen interaction only when the
shared counter changes. Its Function action disables the default screen
update. Regression checks run 100 unchanged polls without an extra restart,
then require a restart for a changed counter and give shutdown priority.

The fullscreen host now keeps the SDL and Flutter panels inside the window area
above the keyboard. On the former 720p layout, a 600-pixel IME covered the entire
512-pixel Flutter panel and made focused text entry disappear from the visible
UI. The host computes occlusion from current insets/window coordinates, preserves
the panel ratio in the remaining area, and restores the full split when the IME
closes. It translates Flutter's keyboard insets to avoid applying the same
occlusion twice. Layout parameters change only when their values differ. The
native input check verifies visible focused bounds and a fresh text callback;
this is a usability fix, without a keyboard-animation timing measurement.

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
`ce1a18b26dda28febb69f50e24214ae910c95318`. Original host code,
tests, and probes live on `main`; component archives and upstream notices
remain intact.

## Service reuse and file workers

The capability page originally constructed nine services on every visit.
A [prepared-Flet inspection](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37153605168)
recorded 180 service references after 20 visits with cyclic collection disabled;
forced collection then removed them. This was delayed cleanup, rather than a
demonstration of permanent retention.

The page owns nine services, including one audio player. The seven core-check
services are also cached per page. The previous [1080p run 37198912979](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37198912979)
logged two native initializations of each core service across two invocations.
The current native checks require one initialization of each across reentry,
with IDs matching the cached Python objects.

The expanded [prepared-Flet inspection](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37202567148)
at source `24ca4fdf84a7ea086074f458342ba0a9ca600237` retains the same
16 IDs across 20 open/pop cycles and forced collection. Before the SDK cleanup
fix, a page-owned dictionary alone lost its seven core services from the
registry after collection. The cutoff now accounts for protocol snapshots;
20 prepared-Flet regressions include retaining one owned reference and releasing
unowned services before and after native mounting. The probe uses real Flet
session/model/registry code with native route acknowledgements stubbed.
Caching keeps seven additional services for the page lifetime to avoid repeated
registration; these counts do not measure native memory savings.

Native verification also changed from three audio-player initializations over
three visits in [run 37153138450](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37153138450)
to one in [run 37155109602](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37155109602).
The latter repeats all 24 capability checks after reentry in the same process.
The latest [device run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264666)
repeats that assertion against the current APK in both display profiles. These are service-reference
and initialization counts; native memory and FPS gains have not been measured.

Picker files are hashed on the worker pool in 64 KiB chunks, without requesting
file bytes in the Flet protocol. A cooperative cancellation signal stops the
chunk loop and closes the stream. Regression checks cancel an active worker,
require it to exit, and verify guard restoration. Four native selections verify
exact fixture bytes before and after force-stop; this is correctness evidence,
rather than a large-file throughput benchmark.

## APK packaging measurement

Both packages come from [build 37205024407](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37205024407)
at source `24ca4fdf84a7ea086074f458342ba0a9ca600237`. APK sizes below are bytes before the
Actions artifact ZIP wrapper.

| APK | Bytes | Native ABIs | SHA-256 |
| --- | --- | --- | --- |
| runner-debug.apk | 600902912 | arm64-v8a, armeabi-v7a, x86_64 | 95c443a4346be78315e0c7e8c198b118069adcdff4c4bede288b180d02e1e0eb |
| runner-debug-x86_64.apk | 229509996 | x86_64 | 8e45f1d5a84b440934f8c3a4d4d7297ccda251fc064242b26020f2b6fb83e481 |

The x86_64 APK is 61.8% smaller and retains all 19 extensions, 541 prepared
Python package/resource files and 369 Ren'Py common assets. The build compares
979 shared payload entries, including retained native libraries, code, resources
and notices. `apk-builds.json` is included in both artifact downloads.

The second host assembly took 20 seconds in this build;
shared-payload hashing took about 5 seconds. Producing and uploading an additional artifact adds
build work. The measurement demonstrates fewer bytes for repeated emulator
download/installation, rather than an overall CI latency or runtime FPS gain.

## Linux protocol stress

[Runtime check](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37202567148)
used main source `24ca4fdf84a7ea086074f458342ba0a9ca600237`,
Python 3.12.3, four reported CPUs, and
`Linux-6.17.0-1022-azure-x86_64-with-glibc2.39`.

Each cycle starts the real pinned Flet socket server, registers a page,
sends 100 Increment events, and requires a fresh matching UI patch after each
event. It verifies the exact shared counter, observes no protocol messages
during a 250 ms idle window, and joins the backend thread at shutdown.
All 500 events and five start/stop cycles passed. The same run executed all
20 prepared-Flet lifetime tests with zero skips, imported all 19 Python
extensions, and checked shutdown during startup.

Times are milliseconds and percentiles use the nearest-rank method.

| Cycle | Events | Startup | Shutdown | Event p50 | Event p95 | Event max |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | 100 | 118.671 | 1.782 | 0.767 | 0.795 | 1.029 |
| 2 | 100 | 12.943 | 1.690 | 0.784 | 0.838 | 1.169 |
| 3 | 100 | 12.916 | 1.645 | 0.771 | 0.793 | 0.885 |
| 4 | 100 | 12.686 | 1.602 | 0.806 | 0.825 | 0.892 |
| 5 | 100 | 13.024 | 1.639 | 0.776 | 0.870 | 1.185 |

Event latency measures Linux UDS event submission through the resulting UI
patch. It excludes Android input, Flutter rendering, SDL rendering, and
network delivery. Startup includes connection and initial controls; the first
cycle also includes first imports. CI worker variation affects these numbers.

[Measurement JSON and source receipt](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37202567148/artifacts/11303567123)
are retained as workflow artifacts.

## Android debug frame baseline

The first two Android 35 x86_64 CI emulator runs below used the same debug APK.
Later rows repeat the window with service-reuse and file-worker fixes.
Historical rows use the 1080p display. The latest pair uses the same current
x86_64 APK and harness at 720p/280 dpi and 1080p/420 dpi, with the same
411.429 × 731.429 dp logical display. All use Flutter Impeller OpenGLES and SwiftShader software graphics. Each profiling
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
| [37206264666 720p](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264666) | 77 | 7.911 | 4.380 / 25.952 | 14.803 / 52.667 | 48.002 / 92.890 | 65 |
| [37206264666 1080p](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264666) | 57 | 9.501 | 7.095 / 74.497 | 43.133 / 125.373 | 110.654 / 201.677 | 55 |

The 720p display has 921,600 pixels, 55.6% fewer than the 2,073,600 pixels in
1080p. Both profiles use two guest CPU cores, 2 GiB configured memory and
SwiftShader; actual display/API/ABI/density and host CPU count are recorded.
The 1080p run retains coverage of the original display. The 720p run has lower
observed median and p95 raster/total-span times in this pair. Separate CI workers,
different sample counts and short windows limit this comparison; it is not a
controlled release or physical-device benchmark.

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
and current [720p artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264666/artifacts/11305330709)
and [1080p artifacts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37206264666/artifacts/11304985804)
include `flutter-frame-profile.json`, `profile-memory.txt`, framebuffer
samples, SVG/chart visual receipts, native-service IDs, logcat, UI trees,
SystemUI gesture state, display/environment records and source receipts.
