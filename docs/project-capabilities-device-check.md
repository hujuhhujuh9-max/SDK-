The combined example has an API 35 emulator functionality check in
`scripts/check_project_capabilities.py`. The coordinator runs it against the
combined debug APK; workers do not operate that emulator concurrently.

```sh
python scripts/check_project_capabilities.py \
  runner-org-renfletpy-capabilities-debug-x86_64.apk \
  --source-sha FULL_SOURCE_COMMIT \
  --project-input-sha256 FULL_PROJECT_INPUT_SHA256 \
  --aapt "$ANDROID_HOME/build-tools/36.0.0/aapt" \
  --expected-api 35 \
  --output .android-build/project-capabilities-device
```

The host needs a JDK, Android build-tools and an installed Android 35 or newer
platform `android.jar`. The harness compiles `scripts/capabilities_pinch.java`
to a shell-only dex driver and injects a real two-pointer gesture. The driver
never enters the APK. A changed Canvas camera scale is required in addition to
Android acknowledging the injected events.

The harness installs the inspected APK and clears only the configured
`org.renfletpy.capabilities` fixture's data. It requires an API 35 x86_64 emulator,
checks the compiled project identity and installed APK hash, and preserves raw
device properties, display information, semantic XML, screenshots and logs.

It exercises notebook Back, a direct link, replacement-dialog Back and Cancel,
draft/selection ownership through native Start and Return, and the existing
Records and Saved games screens. PulseDial exercises real properties and tap
events, running/paused pixels, removal/recreation and background/resume.
The app Canvas and table exercise selection, pan, pinch zoom, row editing and
an asynchronous query over 10,000 rows.

The native journey renders 128 ATL sprites, eight compositing layers and two
shader passes before its registered Canvas and Rive activities. Each halfway
activity performs a quick save, changes its game values, then quick loads the
exact saved model with a new revision. It then changes a game value again,
waits for an actual Android recovery `.save`, closes the process and reopens in
a fresh PID. That newer model must restore exactly. Native save archive
metadata, game-data hashes and signatures are retained without unpickling
the saved game on the test host.

Rive readiness callbacks must report actual artboard bounds, input types and
reconstructed number/boolean values. Actual colored forest pixels must move
while `Downloading=True`. `Downloading=False` is intentionally static. A
trigger must emit its number, boolean and string result, and the project story
and native observer must each record exactly one returned result. All Rive
controller IDs created in the final process must have disposal logs after
completion. Runtime tracebacks, malformed/PID-mismatched receipts and visible
component errors fail the run.

On success, `capabilities-device.json` records the source, APK and project
hashes, emulator identity, three process IDs, native owner proofs, checks and a
SHA-256/size inventory for every retained artifact. The receipt has
`scope="emulator_functionality"` and `phone_performance_proven=false`.
Short pixel comparisons prove playback and pause functionality; they make no
frame-time, input-latency, startup or memory claim. Physical API 35 measurements
remain a separate check. Failed runs retain diagnostics and never retain an
earlier success receipt.

`python -m unittest tests.test_project_capabilities` checks the evidence gates
without contacting a device. Compiling the Java driver and these tests do not
constitute an executed emulator run.
