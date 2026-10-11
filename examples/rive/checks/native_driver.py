"""Native save acceptance using an event actually emitted by the Dart test."""

import hashlib
import json
import os
import threading
import traceback
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import renpy.exports as renpy
import renpy.store as store
from renpy import game as native_game
from renpy.display.core import EndInteraction

import sdk_bridge
from renfletpy import story
from rive_activity import SIGNAL_PROPERTIES
from story_activities import ActivityResult


mode = os.environ["RIVE_CHECK_MODE"]
event_path = Path(os.environ["RIVE_CHECK_EVENT"])
event = json.loads(event_path.read_text())
assert event["name"] == "SomeGeneralEvent" and event["type"] == "general"
assert event["properties"] == SIGNAL_PROPERTIES
assert type(event["properties"]["SomeBoolean"]) is bool
phase = "activity"
checks = []
half_state = None
old_revision = None
held_ticks = 0
owner = threading.get_ident()


def passed(name):
    checks.append(name)
    print("Passed: " + name, flush=True)


def submit(revision, name, payload=None):
    with ThreadPoolExecutor(max_workers=1) as worker:
        assert worker.submit(story.activity_command, revision, name, payload).result(timeout=5)


def write_receipt():
    current = story.current()
    Path(os.environ["RIVE_CHECK_RECEIPT"]).write_text(json.dumps({
        "mode": mode, "pid": os.getpid(), "owner_thread": owner, "checks": checks,
        "half_state": half_state, "schema": current.activity["version"] if current else 2,
        "event_sha256": hashlib.sha256(event_path.read_bytes()).hexdigest(),
        "return_count": store._rive_probe_returns,
        "result": store._rive_probe_result.snapshot() if isinstance(store._rive_probe_result, ActivityResult) else None,
        "cancelled": store._rive_probe_cancelled.snapshot() if isinstance(store._rive_probe_cancelled, ActivityResult) else None,
    }, indent=2) + "\n")


def tick():
    try:
        advance()
    except (EndInteraction, native_game.FullRestartException, native_game.QuitException, native_game.JumpException):
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)


def advance():
    global phase, old_revision, half_state, held_ticks
    assert threading.get_ident() == owner
    current = story.current()
    if phase == "activity" and current:
        assert current.kind == "rive_console"
        old_revision = current.revision
        if mode in ("reopen", "migrate"):
            half_state = current.activity["state"]
            assert current.activity["version"] == 2
            assert half_state == {"progress": 55.0, "downloading": mode == "migrate", "receipt": None}
            assert not renpy.can_load("_reload-1")
            passed("fresh native process restored saved progress/boolean without a trigger or live controller")
            if mode == "migrate":
                passed("version 1 native save migrated progress into version 2 model before resume")
            finish(current.revision)
            phase = "menu-held"
            return
        submit(current.revision, "progress", 55.0)
        if mode != "legacy-seed":
            submit(current.revision, "downloading", False)
        assert current.activity["state"]["progress"] == 25.0
        passed("event worker queued plain commands without mutating native state")
        phase = "half"
    elif phase == "half":
        data = current.activity["state"]
        assert data == ({"progress": 55.0} if mode == "legacy-seed" else
                        {"progress": 55.0, "downloading": False, "receipt": None})
        half_state = data
        if mode in ("seed", "legacy-seed"):
            native_game.interface.mobile_save()
            assert renpy.can_load("_reload-1")
            passed("actual native mobile save captured halfway Rive game values")
            write_receipt()
            os._exit(0)
        sdk_bridge.set_presentation("page")
        assert sdk_bridge.request_save("save")
        phase = "manual-save"
    elif phase == "manual-save" and not sdk_bridge.save_status()["busy"]:
        assert renpy.can_load(store.RENFLETPY_SAVE_SLOT)
        passed("normal SDK quick save captured the native Rive activity wait")
        submit(current.revision, "progress", 10.0)
        submit(current.revision, "downloading", True)
        story.process_activity_commands()
        assert sdk_bridge.request_save("load")
        phase = "manual-load"
    elif phase == "manual-load" and not sdk_bridge.save_status()["busy"]:
        assert current.revision != old_revision and current.activity["state"] == half_state
        assert not story.activity_command(old_revision, "receipt", event)
        assert not story.cancel_activity(old_revision)
        passed("normal SDK quick load restored saved values and rejected the old Rive callbacks")
        finish(current.revision)
        phase = "menu-held"
    elif phase == "menu-held":
        assert current and current.selected == "completed"
        assert store._rive_probe_result is None and store._rive_probe_returns == 0
        held_ticks += 1
        if held_ticks < 4:
            return
        passed("real Rive event completion remains pending while the app menu owns presentation")
        assert not story.activity_command(current.revision, "receipt", event)
        sdk_bridge.set_presentation("interlude")
        phase = "returned"
    elif phase == "returned" and store._rive_probe_returns == 1:
        result = store._rive_probe_result
        assert result == ActivityResult("completed", {
            "progress": 100.0, "downloading": mode == "migrate", "signal": SIGNAL_PROPERTIES})
        assert current and current.kind == "rive_console"
        with ThreadPoolExecutor(max_workers=1) as worker:
            assert worker.submit(story.cancel_activity, current.revision,
                                 {"progress": 25.0, "reason": "user_cancelled"}).result(timeout=5)
        passed("actual Dart event receipt returned one typed result through the native story call")
        phase = "cancel-return"
    elif phase == "cancel-return" and store._rive_probe_returns == 2:
        assert store._rive_probe_cancelled == ActivityResult("cancelled", {
            "progress": 25.0, "reason": "user_cancelled"})
        assert story.current() is None
        assert [entry.selected for entry in story.history()] == ["completed", "cancelled"]
        assert len([entry for entry in store._history_list if getattr(entry, "renfletpy_result", "")]) == 2
        passed("completion/cancellation return once with one native history entry each")
        write_receipt()
        renpy.quit()


def finish(revision):
    sdk_bridge.set_presentation("page")
    submit(revision, "progress", 100.0)
    submit(revision, "receipt", event)
    story.process_activity_commands()
