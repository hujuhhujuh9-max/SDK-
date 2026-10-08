# D: startup, packaging and CI

Base: `c8d4dd1f2be678756d96bac228070b50b0539d14` on `main`.
Implementation branch: `feature/startup-packaging-ci`.
This is the bounded D lane; no SDK component branches or pins change.

## Startup contract

`build_android.py --startup-mode story|app` is the selection point. Omitting it
selects `story`, preserving the existing native opening. `app` selects the
existing Application records recipe at `/records`. An app-shell lane can update
that route in `scripts/startup_config.py` and the host's configuration validator
when its shared route contract is integrated.

The builder writes `assets/runner-startup.json` with schema 1, mode and initial
route. `RunnerActivity` validates it and supplies the default Flutter route only
when the launch intent has no deep link. Warm links keep their existing handling.
Ren'Py/SDL retains startup, the native story and the single Python interpreter.
Its story can remain prepared behind the application page; existing presentation
and recovery guards preserve that route. There is no new saved startup variable
or change to the story's save format.

The host logs `SDK_RUNNER_STARTUP mode=... route=... pid=...`. Device acceptance
requires the selected default route and visible screen. App acceptance then
opens the story through an explicit link without restarting the interpreter and
continues the full existing suite.

## Artifact contract

Both the universal and x86_64 APKs contain the same startup configuration.
`runner-capabilities.json` records `startup_mode` and `startup_config_sha256`.
`inspect_apk` validates the configuration, hash and requested mode before the
existing 19-extension, package/resource and ABI checks. The shared-payload check
includes the startup asset and inventory.

`apk-builds.json` identifies the source SHA, dirty-checkout status, selected mode,
each inspected APK and shared-payload verification. CI requires a clean source
checkout. `host-tests.json` records the same source, actual test count, zero skips,
zero failures and zero errors. Device selection requires a successful approved
build run, source compatibility and an exact match between the downloaded APK
and its report. An in-progress parent integration run is allowed only for its
own dependent device job after the build dependencies pass. GitHub's temporary
`pending` parent status during reusable-job scheduling is handled by the same
current-run identity check; it cannot approve an unrelated pending build.

Story artifact names retain `runner-apk` and `runner-emulator-apk`; app artifacts
use `runner-app-apk` and `runner-app-emulator-apk`. Filenames within the artifacts
stay the same. No older APK without explicit mode metadata can satisfy the new
gate. Unsupported modes fail argument parsing before SDK preparation.

## Reuse and acceptance

Mode selection changes only Android packaging inputs. It is excluded from the
Flutter AAR identity, which still verifies the real SDK, Dart/plugin, toolchain,
recipe and output inventory inputs. Analysis and Flutter tests still run when
the AAR is reused; `--force-flutter-build` remains available.

Build and device workflows expose `startup_mode`. The new
`integration-startup.yml` runs on application PRs and `integration/app-story`,
building and checking both modes. The existing A/B/C integration gate also
triggers on artifact, device and acceptance harness changes. Explicit artifact
selection must match the requested mode; automatic checks of a direct completed
build follow that build's mode.

Device concurrency groups include the calling workflow, ref and startup mode.
The mode matrix runs on separate hosted runners and emulators, so one queued
mode cannot cancel the other through GitHub's single-pending-run limit.
The story save suite uses explicit story links for its cold restarts after the
initial launch has verified the APK's selected default.

The complete prepared-Flet host suite must pass without skips. Device acceptance
requires startup, real media output, story/save/recovery, renderer/background
checks, capabilities, fresh-process storage, keyboard/profiling, links/Back,
force-stop storage, application records and diagnostics. Only completion of every
phase can produce `acceptance.json`; it binds the APK hash, selected mode, source
and hashes of the required receipts. CI verifies it even after a failed step.
The parent acceptance job rejects failed, cancelled or skipped dependencies.

## Ownership and evidence

D owns `build_android.py`, `RunnerActivity.java`, the changed/new workflows,
`scripts/startup_config.py`, `scripts/check_apk*.py`, `scripts/check_host.py`,
`scripts/check_device_acceptance.py`, `scripts/device_smoke.py`, the dedicated
packaging/source/cache/acceptance tests and this documentation. Runtime routing,
story scripts, Flutter sources, catalogs, SDK inputs and licenses are unchanged.

Local prepared-Flet verification passes 267 host tests with zero skips, including
mode/inventory mismatch, wrong-source/build/ABI/receipt, skipped acceptance,
damaged evidence and Flutter reuse regression cases. The real Flet protocol
probe also passes. These are host receipts; APK and Android acceptance are
recorded separately by the mode matrix workflow and are required before claiming
the complete artifact/device acceptance.
The service-lifetime probe retains the expected 14 service identities across
20 cycles; workflow syntax and expressions pass actionlint.
