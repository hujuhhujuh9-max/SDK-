# Branch ownership

The product is one Android application containing the fixed modified
Flet/Flutter/Ren'Py stack. Development and builds happen in Linux.

`main` owns the shared Android runner, integration code, extra dependencies,
SDK lock, tests, and project documentation. Changes made on `main` remain
on `main`.

Each SDK branch owns its component archive, SDK-specific changes, removals,
manifest, and import tooling. Changes made on an SDK branch remain there.

| Owner branch | Component |
| --- | --- |
| `sdk/flutter-3.44.8` | Flutter Linux SDK |
| `sdk/renpy-8.5.3` | Ren'Py SDK |
| `sdk/renpy-rapt-8.5.3` | Ren'Py Android packaging tools |
| `sdk/flet-1.0.3` | Flet Dart and Python source |

Keep all component branches. Use separate checkouts when editing multiple
branches. Do not merge or cherry-pick changes across these branches unless
the owner explicitly requests that operation.

The build input preparer reads pinned SDK archive objects. It never commits or
pushes to a component branch. Generated SDK installations and build outputs
belong in the ignored runtime cache, rather than any tracked branch.

When a component changes, update its archive and manifest on its own branch.
Then update the reference and checksum in `sdk-lock.json` on `main` as a
separate integration change. This records the version used by the runner
without copying the component's branch changes into `main`. Build-time
assembly consumes these inputs; it does not merge their branches.

When two runners overlap, record the actual conflict and discuss the options
with the project owner before selecting startup, rendering, or interpreter
ownership. Independent build preparation can continue while that decision
is open.

Do not remove files from other branches as a side effect of cleaning one
branch. Keep a component's original notices and licenses with its archive.
