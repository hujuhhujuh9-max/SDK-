# Official Rive acceptance fixtures

These unmodified fixtures came from the published `rive_native` 0.1.11 source
archive at <https://pub.dev/api/archives/rive_native-0.1.11.tar.gz>, under
`test/assets/`. The package's MIT license is reproduced in `LICENSE.txt`.
Copyright (c) 2020 Rive. Source repository: <https://github.com/rive-app/rive-flutter>.

| File | SHA-256 | Purpose |
| --- | --- | --- |
| `tree_loading_bar.riv` | `9c3d2780d7978d896ce98a3b8bcd2b4ca62aa6c047fed1406c8c5dbfabad3635` | `Loading` machine: `Progress` number and `Downloading` boolean |
| `events_test.riv` | `40e7cf7176d670858bf2a26ead30e7a7763bf5387abba0832920e61124397818` | `State Machine 1`: `FireGeneralEvent`, `FireOpenUrlEvent`, `FireBothEvents` triggers; typed custom event properties |
| `runtime_nested_inputs.riv` | `64e25b5ae0caa9f7b6c25532ab6eca125cdd4737b7b70a2a417cfa94d5ecd3e8` | Nondefault artboard selection and intrinsic sizing regression |

The console uses the first two files. The third is a selection/lifecycle fixture,
not an assertion that nested state-machine paths are exposed by the Python API.
