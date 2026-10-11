"""Actual native .save, process-loss, migration and completion acceptance."""

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
from story_activities import ActivityResult


mode = os.environ["ACTIVITY_CHECK_MODE"]
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
    # Model the Flet event thread without a second renderer or interpreter.
    with ThreadPoolExecutor(max_workers=1) as worker:
        assert worker.submit(story.activity_command, revision, name, payload).result(timeout=5)


def write_receipt():
    current = story.current()
    Path(os.environ["ACTIVITY_CHECK_RECEIPT"]).write_text(json.dumps({
        "mode": mode, "pid": os.getpid(), "owner_thread": owner, "checks": checks,
        "half_state": half_state,
        "schema": current.activity["version"] if current is not None else 2,
        "return_count": store._activity_probe_returns,
        "result": (store._activity_probe_result.snapshot()
                   if isinstance(store._activity_probe_result, ActivityResult) else None),
        "cancelled": (store._activity_probe_cancelled.snapshot()
                      if isinstance(store._activity_probe_cancelled, ActivityResult) else None),
    }, indent=2) + "\n")


def tick():
    try:
        advance()
    except (EndInteraction, native_game.FullRestartException, native_game.QuitException,
            native_game.JumpException):
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)


def advance():
    global phase, old_revision, half_state, held_ticks
    assert threading.get_ident() == owner
    current = story.current()
    if phase == "activity" and current is not None:
        assert current.kind == "field_survey"
        old_revision = current.revision
        if mode in ("reopen", "migrate"):
            half_state = current.activity["state"]
            assert current.activity["version"] == 2
            assert half_state["samples"] == ["telescope"]
            assert half_state["draft"] == "A spectral line still needs checking"
            assert half_state["selected"] == ("telescope" if mode == "migrate" else "spectrograph")
            assert not renpy.can_load("_reload-1"), "Loaded mobile save remained pending"
            passed("fresh native process restored the half-save with reconstructed plain game values")
            if mode == "migrate":
                assert half_state["notes"] == {"telescope": ""}
                passed("version 1 native .save migrated to version 2 before story resumption")
            finish_activity(current.revision)
            phase = "menu-held"
            return
        submit(current.revision, "draft", "Checked the telescope mirror")
        submit(current.revision, "record")
        if mode != "legacy-seed":
            submit(current.revision, "select", "spectrograph")
        submit(current.revision, "draft", "A spectral line still needs checking")
        assert current.activity["state"] == story.current().activity["state"]
        passed("UI worker submits plain messages without mutating native model")
        phase = "half"
    elif phase == "half":
        data = current.activity["state"]
        if mode == "legacy-seed":
            assert data == {"found": ["telescope"], "note": "A spectral line still needs checking"}
        else:
            assert data == {"samples": ["telescope"], "draft": "A spectral line still needs checking",
                            "selected": "spectrograph", "notes": {"telescope": "Checked the telescope mirror"}}
        half_state = data
        if mode in ("seed", "legacy-seed"):
            native_game.interface.mobile_save()
            assert renpy.can_load("_reload-1")
            passed("actual mobile native save captured halfway activity state")
            write_receipt()
            os._exit(0)
        sdk_bridge.set_presentation("page")
        assert sdk_bridge.request_save("save")
        phase = "manual-save"
    elif phase == "manual-save" and not sdk_bridge.save_status()["busy"]:
        assert renpy.can_load(store.RENFLETPY_SAVE_SLOT)
        passed("normal SDK quick save wrote the native activity wait context")
        submit(current.revision, "draft", "Later text must not survive loading")
        story.process_activity_commands()
        assert sdk_bridge.request_save("load")
        phase = "manual-load"
    elif phase == "manual-load" and not sdk_bridge.save_status()["busy"]:
        assert current.revision != old_revision
        assert current.activity["state"] == half_state
        assert not story.activity_command(old_revision, "draft", "Delayed old event")
        assert not story.cancel_activity(old_revision)
        passed("normal SDK quick load restores draft/selection and rejects previous controls")
        finish_activity(current.revision)
        phase = "menu-held"
    elif phase == "menu-held":
        assert current is not None and current.selected == "completed"
        assert store._activity_probe_result is None and store._activity_probe_returns == 0
        held_ticks += 1
        if held_ticks < 4:
            return
        passed("completed activity stays pending while normal SDK menu owns presentation")
        assert not story.cancel_activity(current.revision)
        assert not story.activity_command(current.revision, "record")
        sdk_bridge.set_presentation("interlude")
        phase = "returned"
    elif phase == "returned" and store._activity_probe_returns == 1:
        result = store._activity_probe_result
        assert isinstance(result, ActivityResult) and result.status == "completed"
        assert result.value["samples"] == ["telescope", "spectrograph"]
        assert result.value["notes"]["spectrograph"] == "A spectral line still needs checking"
        assert current is not None and current.kind == "field_survey"
        with ThreadPoolExecutor(max_workers=1) as worker:
            assert worker.submit(story.cancel_activity, current.revision, {"reason": "later"}).result(timeout=5)
        passed("one meaningful completed result returned through actual native story call")
        phase = "cancel-return"
    elif phase == "cancel-return" and store._activity_probe_returns == 2:
        assert store._activity_probe_cancelled == ActivityResult("cancelled", {"reason": "later"})
        assert story.current() is None
        assert [entry.selected for entry in story.history()] == ["completed", "cancelled"]
        assert len([entry for entry in store._history_list if getattr(entry, "renfletpy_result", "")]) == 2
        passed("explicit cancellation returns once and each result has one native history entry")
        write_receipt()
        renpy.quit()


def finish_activity(revision):
    sdk_bridge.set_presentation("page")
    if mode == "migrate":
        submit(revision, "select", "spectrograph")
    submit(revision, "record")
    submit(revision, "finish")
    story.process_activity_commands()
