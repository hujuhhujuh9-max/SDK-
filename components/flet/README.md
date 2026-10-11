# Flet 1.0.3 source baseline

This branch owns Flet-specific changes and removals for the fixed Android
application. Shared Android integration belongs on `main`. Keep both branches
independent; consuming an archive does not merge their Git histories.

The source archive comes from official tag `v1.0.3`, pinned to upstream commit
`a87ca7fc8a813b9d821858083c7539e8e79ab3ba`. Its original licenses and notices
are retained. `manifest.json` records its byte count and SHA-256. The baseline bytes remain unchanged; branch-owned patches are applied only
to a generated build copy.

The archive contains the Dart widget package in `packages/flet/` and the Python
package in `sdk/python/packages/flet/`. They are inputs to the Android
integration; this branch does not select the application's Activity or Python
startup owner.

```sh
git lfs pull --include="components/flet/archives/*"
mkdir -p work
tar -xzf components/flet/archives/flet-1.0.3-source.tar.gz -C work
```

The import workflow downloads the pinned source, verifies it, and writes only
to `sdk/flet-1.0.3`. Component changes and any corresponding archive/manifest
updates stay here. `main` records the version it consumes separately.

## Ren'Py embedding patch

`patches/renpy-embedding.patch` keeps embedded Flet socket startup inside the
existing connection cleanup path, so the owning Ren'Py host can cancel and
close Flet without starting or finalizing another interpreter. It also stamps
the fixed Flet/Flutter versions using Flet's existing release fields.

This modification follows Flet's Apache-2.0 license, retained in `LICENSE`.
The main-branch rights notice does not relicense this component.

## Pending method replies after unmount

`patches/unmounted-method-reply.patch` fixes a reproduced Python session race:
an awaited Flutter method can finish after navigation or an imperative UI rebuild
removes its target. A known pending call now wakes its caller with a defined
unmounted-control error instead of raising into the socket receive loop and
closing the connection. Cancelled, timed-out and completed calls still ignore
late replies, and normal/native-error replies keep their previous behavior.

The baseline archive is unchanged. The manifest seals this additional patch;
the application consumes this component commit through its separate SDK lock
update. Integration tests exercise actual socket continuity, control rebuilds,
waiter cleanup and subsequent calls.
