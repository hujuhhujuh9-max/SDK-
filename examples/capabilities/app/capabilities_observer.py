"""Project-only native acceptance observer, kept outside the Ren'Py save store.

Read committed game data on its owner thread. Do not drive gameplay, save/load,
controllers or Flet. The Android harness binds these receipts to actual pixels,
semantic controls, native save markers and distinct process IDs.
"""

import hashlib
import json
import os
import threading
from pathlib import Path

try:
    import sdk_bridge
    from renfletpy import story
except ImportError:
    from runtime import sdk_bridge
    from runtime.renfletpy import story


_owner = None
_installed = False
_last_activity = None
_last_app = None
_closed_results = set()


def _native():
    if _owner != threading.get_ident():
        raise RuntimeError("Capabilities observer belongs to the native story thread")


def _emit(marker, **values):
    _native()
    print(marker + " " + json.dumps({"pid": os.getpid(), "owner_thread": _owner, **values},
                                     sort_keys=True, allow_nan=False), flush=True)


def _signature(value):
    return json.dumps(value, sort_keys=True, allow_nan=False)


def activity(phase="committed", *, force=False):
    global _last_activity
    _native()
    current = story.current()
    if current is None or current.activity is None:
        _last_activity = None
        return
    value = {"kind": current.kind, "revision": current.revision, **current.activity}
    signature = _signature(value)
    if force or signature != _last_activity:
        _emit("SDK_CAP_ACTIVITY_STATE", phase=phase, **value)
        _last_activity = signature


def after_load():
    """SDK's restore callback runs first; historical results are not new returns."""
    _native()
    _closed_results.clear()
    current = story.current()
    for entry in story.history():
        if entry.activity is not None and entry.activity["result"] is not None and (
                current is None or entry.revision != current.revision):
            _closed_results.add(entry.revision)
    activity("restored", force=True)


def tick():
    global _last_app
    _native()
    activity()
    current = story.current()
    history = story.history()
    live_revisions = {entry.revision for entry in history}
    _closed_results.intersection_update(live_revisions)
    for entry in history:
        if (entry.activity is None or entry.activity["result"] is None
                or entry.revision in _closed_results
                or (current is not None and entry.revision == current.revision)):
            continue
        # The standard native poll closes only after consuming and recording
        # its result. Never call consume or claim a pending menu-held result.
        _emit("SDK_CAP_ACTIVITY_RESULT", kind=entry.kind, revision=entry.revision,
              result=entry.activity["result"])
        _closed_results.add(entry.revision)
    state = sdk_bridge.app_session.status()
    value = {key: state[key] for key in ("revision", "phase", "resume_kind", "showing_story", "result")}
    signature = _signature(value)
    if signature != _last_app:
        _emit("SDK_CAP_APP_STATE", **value)
        _last_app = signature


def install(renpy):
    global _owner, _installed
    if _installed:
        _native()
        return
    _owner = threading.get_ident()
    renpy.config.after_load_callbacks.append(after_load)
    _installed = True
    _emit("SDK_CAP_OBSERVER", schema=1, observer="project_capabilities",
          source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
