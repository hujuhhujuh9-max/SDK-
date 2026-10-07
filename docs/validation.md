# Runner validation

The runner removes phone-camera access and player rollback, and verifies
real media and animation output. Earlier source commits and their original device scopes are
in [the validation history](validation-history.md); measurements are in
[performance.md](performance.md).

## Player rollback source removed — 2026-10-07

The modified Ren'Py component deletes the player rewind implementation,
rollback/roll-forward exports, actions, input mappings, preferences, screen
options and obsolete template/tutorial controls. The runner no longer sets
flags to disable them. The active load-point snapshots and mutable-object
restoration remain for save/load; earlier completed interactions are pruned.
Story history remains readable. The SDK archive includes these source changes
and omits stale compiled copies of modified/deleted sources.

Local verification passes 165 host Python cases (20 prepared-Flet cases are
skipped by that command), 55 native checks across seven processes at
1080×1920, and eight original-save compatibility checks across two additional
processes. The SDK source diff removes 2,323 lines overall: 3,313 removed and
990 added. Checks exercise actual native dialogue, menus, text input, timed pauses,
movie cutscenes, mutable state, the saved random sequence, quick/panel/scene
loads, worker/mobile saves and fresh-process recovery. Rewind APIs and actions
must be absent before and after loading. The original SDK also creates a
mobile save that the modified engine must recover in another process. Run
`scripts/check_native_story.py --legacy-renpy-sdk /path/to/original/sdk` to
produce those receipts. The launcher, tutorial and sample game also compile
from a fresh archive extraction.

| Check | Result | Evidence |
| --- | --- | --- |
| Python/Flet regressions | All 185 unique cases pass | [Input CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37641086374); [Runtime CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37641086435) |
| Modified engine | All 55 checks across seven processes pass in CI; eight additional original-save checks pass locally | [Native receipts](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37641029320/artifacts/11492213430) |
| Flutter/APKs | Strict analysis and all 11 tests pass; both APKs retain 541 Python resources and 367 common assets from the modified SDK; all 978 shared payload hashes match | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37641029320) |
| Android 36, 1080p | Device verification running | [Device run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37642486955) |

The APK source is `a2907bc38595d3a2357f7d1515832331608738ce`, pinning
Ren'Py component `0d58d1fc5b5fed87cb0f54eb717233d05643f506` and archive
SHA-256 `3da8a585d5af973230e5b1d3e5c38db3987c6e583062c84b3056c862fa8248b0`.
The common-asset count decreases by two because obsolete compiled copies are
removed. All resources in the modified SDK's packaging inventory are verified.

| APK | Bytes | SHA-256 |
| --- | --- | --- |
| Universal | 601261733 | 84cb4f89db18632f78e0da995c88ea601e94c125c4695720ad08799c8d45ec10 |
| x86_64 | 229868817 | 34957cb09e0669a0f03086e265187dd9c7f80ee35d5e4719ec02591cda86ef39 |

## Camera, media, animation and native rendering — 2026-10-07

Phone-camera permission and hardware declarations are removed at Android
manifest merging, so plugins cannot reintroduce them. APK assembly and the
installed-package check reject CAMERA permission. The permission button and
unused authentication/status probes are removed. The fixed SDK extension
catalog and component archives remain intact.

The audio fixture is a real 440 Hz tone at audible volume. Audio and video loop
until explicitly paused. Device CI enables
emulator audio output and captures fresh virtual sound-card PCM, requiring the tone
during play/resume and its absence during pause. The video fixture has changing
frames; the Lottie fixture has a moving light. Pixel samples must change during
playback, remain fixed during pause and change after background/resume.
Native Ren'Py ATL motion is checked in real framebuffer pixels, including
return from menus and Android backgrounding.

The native board caches one completed raster until positions, selection,
revision, view settings or viewport change. Native surfaces stay outside saves.
Color, alpha, movement, picking, view controls and recovery checks remain
required. The SDL construction probe compares forced repaint with reuse on
15 pairs of calls; see [the measured scope](performance.md#native-board-raster-reuse--2026-10-07).

| Check | Current result | Evidence |
| --- | --- | --- |
| Python regressions | 165 host cases and all 20 prepared-Flet cases pass, 185 unique cases overall | [Input CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37579449144); [Runtime CI](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37579449120) |
| Real Flet protocol | 500 events across five backend cycles; the same 14 services across 20 visits and collection | Runtime CI, runtime-inspection artifact |
| Actual Ren'Py | 47 checks across six processes pass locally and in CI, including native motion, raster reuse/resize, save exclusion and all existing board checks; 14 board framebuffer probes pass | [APK build](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37577177193), native-story-check artifact |
| Flutter and APKs | Strict analysis and all 11 Flutter cases pass; both APKs retain 541 Python resources and 369 common Ren'Py assets; 980 shared payload hashes match; CAMERA permission is absent | Same APK build |
| Android output and existing suite | Pass on Android 36 x86_64, 1080×1920, 420 dpi: actual audio/video/Lottie output, native ATL motion, 19 story flags, 24 board flags, 21 board pixel probes, 88 fresh capability passes and four exact picker files | [Device run](https://github.com/hujuhhujuh9-max/SDK-/actions/runs/37578024114) |

The saved output receipts record a 440 Hz RMS of 0.053016 during both play and
resume, with zero RMS while paused, using fresh 1.2-second PCM windows at
48 kHz. Video and Lottie frame samples change during play and after background
recovery; all three paused samples match for each fixture. Native ATL pixels
move before and after backgrounding. Output checks retain the same process,
and the final diagnostic error map is empty.

The device confirms the prepared image's audio buffer multiplier is 8. The
emulator profile records both original and prepared system-image hashes,
disabled cameras, software graphics and the QEMU WAV renderer. The same run
also passes shared-renderer input, keyboard handling, rotation, deep links,
predictive Back, native-service reuse and durable storage after clean relaunch
and force-stop. Receipts, screenshots and captured audio are in its
`runner-device-check-1080p` artifact.

The APK source is `f8592866968bbe2e6d23a1162d881915073677e6`; the device
harness source is `da847ea62c4c8c3a1af0835522d04bb9d3b63e46`. Their application
build inputs match. Both packages are available from the linked APK build.

| APK | Bytes | SHA-256 |
| --- | --- | --- |
| runner-debug-x86_64.apk | 229892288 | 574e4eb5142b317260e5366e04c7208d72854742e7a254602b548c93e9940a19 |
| runner-debug.apk | 601285204 | 31aeff1117b50a54e9c6f787a44f70f0af92d523059d99d9d75e108d868774fd |

## Scope and retained evidence

The single device profile is Android 36 at 1080p/420 dpi, using SwiftShader
software graphics. The Android app builds with SDK/target 36 and retains its
existing minimum API 24; this phase tests API 36 only. GPS, biometric
authentication and recording are excluded from this phase. Phone-camera
access is disabled.

Source commits, APK hashes, display settings, UI trees, screenshots, framebuffer
signatures, raw PCM, audio levels, playback positions, native-service identities
and diagnostic receipts are retained in workflow artifacts. Branch verification
accepts an explicit successful build run ID and checks APK source compatibility.

CPU board construction and debug software-emulator frame timings do not
establish physical GPU or ARM speed. Those devices are unavailable in this
workspace and CI pool. Arbitrary media codecs, Rive assets, ads, flashlight and
in-flight service recovery are outside the exercised fixtures. Release signing
remains unconfigured.

See [capability coverage](flet-flutter-capabilities.md) for the service scope and
[build environment](build-environment.md) for reproduction requirements.
