# Modified Ren'Py SDK 8.5.3

Branch: `sdk/renpy-8.5.3`

This distribution removes player rollback and roll-forward from the original
engine source: rewind APIs, actions, key bindings, screen options, preferences,
rewind history, fixed-choice replay and obsolete UI/tutorial translations.
The runner does not need configuration flags to disable them.

Save/load, quick saves, autosaves and mobile recovery retain the active load
point, mutable state and random state. Earlier completed interactions are
pruned. Save-exclusion types and mutation restoration remain necessary for
loading saves; old rewind pickles are mapped to the new save-only types.

The modified sources remove 2,323 lines overall (3,313 removed,
990 added). [The source diff](patches/remove-player-rollback.patch) is for
review and reproducing the fork; its changes are already in the archive.
Do not apply it again during runner assembly. Obsolete compiled copies of
changed/deleted sources are omitted so Ren'Py compiles the modified sources.
All original binaries, licenses and notices are preserved. Bundled upstream
HTML documentation describes stock Ren'Py; the removals above override its
rollback feature documentation for this fork.

The modified archive is stored with Git LFS at
`archives/renpy-8.5.3-sdk.tar.bz2` (147,247,431 bytes).
Its SHA-256 is `3da8a585d5af973230e5b1d3e5c38db3987c6e583062c84b3056c862fa8248b0`. `manifest.json` also records the original archive
checksum and import provenance. The unmodified archive remains in Git history
at `c5068b1511fa84b3a7c6fbc111ac95a56eb1d96e`.

From the repository root:

```sh
git lfs pull --include="components/renpy/archives/*"
cd components/renpy
tar -xf archives/renpy-8.5.3-sdk.tar.bz2
```

The extracted root is `renpy-8.5.3-sdk/`. Matching Android packaging tools are
owned by `sdk/renpy-rapt-8.5.3`. Main pins this component through `sdk-lock.json`.
