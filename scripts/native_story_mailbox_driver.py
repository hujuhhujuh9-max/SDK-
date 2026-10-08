"""Actual-A/native-thread acceptance driver for temporary verifier projects."""

import hashlib
import json
import os
import threading
import time
import traceback
from collections import deque
from pathlib import Path

import native_story_mailbox
import renpy
import renpy.exports as exports
import renpy.store as store
import sdk_bridge as bridge
from renpy import config, game
from renpy.display.core import EndInteraction

MODE = os.environ["SDK_NATIVE_LIFECYCLE_MODE"]
RECEIPT = Path(os.environ["SDK_NATIVE_LIFECYCLE_RECEIPT"])
SLOT = "sdk-native-lantern-checkpoint"
OWNER = threading.get_ident()
PROJECT = Path(native_story_mailbox.__file__).parent
RECIPE_SHA256 = {name: hashlib.sha256((PROJECT / relative).read_bytes()).hexdigest()
                 for name, relative in {"game/story.rpy": "game/story.rpy", "game/profile.rpy": "game/profile.rpy",
                                        "app/host.rpy": "game/zz-host.rpy",
                                        "app/native_story_mailbox.py": "native_story_mailbox.py"}.items()}
checks = []
steps = deque()
marks = {}
workers = []
native_calls = []
confirmations = []
completions = []
restores = []
label_entries = []
disk_methods = []
disk_reads = []
resume_checks = 0
recovered_state = None
checkpoint_digest = None
sentinel = threading.Lock()
started = time.monotonic()


def passed(message):
    checks.append(message)
    print("Passed: native mailbox " + message, flush=True)


def adapter():
    return native_story_mailbox.runtime


def state():
    value = store.sdk_native_story_state
    return dict(value) if value is not None else None


def expect(status, phase, route=None, same_run=True):
    value = state()
    assert value is not None and (value["status"], value["phase"], value["route"]) == (status, phase, route), value
    if same_run and "run" in marks:
        assert value["run_id"] == marks["run"]["run_id"], (value, marks["run"])
    return value


def worker(function, *args, **kwargs):
    """Run only a real bridge submission on a separate callback thread."""
    result, errors = [], []
    before = len(native_calls)

    def submit():
        try:
            assert threading.get_ident() != OWNER
            workers.append(threading.get_ident())
            result.append(function(*args, **kwargs))
        except Exception as error:
            errors.append(error)

    thread = threading.Thread(target=submit, name="native-mailbox-submit")
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive() and not errors, errors
    assert len(native_calls) == before, "Worker submission executed a native operation"
    return result[0]


def blocked(reason):
    before = state()
    assert not store.sdk_native_story_input_allowed(), reason
    assert store.sdk_native_story_choose("continue") is False
    assert store.sdk_native_story_choose("finish") is False
    assert store.sdk_native_story_return() is False
    assert store.sdk_native_story_save_from_scene() is False
    assert state() == before
    passed(reason + " rejects stale Continue, Finish, Return and Save actions")


def submit_story(action, route="/app/records?record=current", guard=False):
    request = worker(bridge.request_story, action, "lantern", return_route=route)
    assert type(request) is int and request > 0, bridge.story_status()
    current = bridge.story_status()
    assert current["busy"] and current["request_id"] == request and current["action"] == action
    assert not any(item["request_id"] == request for item in confirmations)
    marks["request"] = request
    if guard:
        blocked("pending " + action)
    return request


def choose(value):
    def action():
        store.sdk_native_story_choose(value)
        raise AssertionError("Native choice did not transfer interaction")
    return action


def direct_return():
    marks["return_confirmations"] = len(confirmations)
    store.sdk_native_story_return()
    raise AssertionError("Native Return did not transfer interaction")


def step(screen, phase, action):
    steps.append((screen, phase, action))


def archive(slot=SLOT):
    return Path(config.savedir) / (slot + renpy.savegame_suffix)


def digest():
    return hashlib.sha256(archive().read_bytes()).hexdigest()


def capture(name):
    exports.screenshot(str(RECEIPT.parent / (MODE + "-" + name + ".png")))


def trap_disk():
    assert not disk_methods
    disk_reads.clear()

    def forbidden(name):
        def call(*args, **kwargs):
            disk_reads.append(name)
            raise AssertionError("Live Resume read native save API " + name)
        return call

    for name in ("can_load", "slot_json", "load"):
        disk_methods.append((name, getattr(store.renpy, name)))
        setattr(store.renpy, name, forbidden(name))


def restore_disk():
    while disk_methods:
        name, original = disk_methods.pop()
        setattr(store.renpy, name, original)


def submit_resume(active):
    marks["before_resume"] = state()
    marks["resume_labels"] = len(label_entries)
    marks["resume_active"] = active
    if active:
        bridge.set_presentation("page")
        blocked("app-page presentation")
    trap_disk()
    submit_story("resume", route="/app/settings?section=reading", guard=True)


def check_resume(phase, route=None):
    global resume_checks
    restore_disk()
    assert not disk_reads, disk_reads
    before = marks["before_resume"]
    value = expect("running", phase, route)
    assert (value["run_id"], value["phase"], value["route"]) == (before["run_id"], before["phase"], before["route"])
    assert len(label_entries) == marks["resume_labels"] + (0 if marks["resume_active"] else 1)
    assert bridge.story_status()["state"] == "active" and adapter().pending is None
    assert bridge.story_status()["return_route"] == "/app/settings?section=reading"
    if marks["resume_active"]:
        assert bridge.presentation() == "page", "Native acknowledgement navigated the chosen presentation"
    resume_checks += 1
    passed(("active" if marks["resume_active"] else "returned") + " Resume preserves live phase with no save reads")
    bridge.set_presentation("scene")


def initial():
    assert state() is None and bridge.story_status()["state"] == "idle"
    assert store.sdk_native_story_return() is False and not bridge.save_status()["available"]
    assert store.sdk_native_story_choose("continue") is False
    assert store.sdk_native_story_choose("finish") is False
    assert store.sdk_native_story_save_from_scene() is False
    assert adapter().owner == OWNER and adapter().sentinel_lock is sentinel
    assert bridge.reading_status()["large_text"] is False and bridge.reading_status()["text_speed"] == "instant"
    passed("the supplied A runtime starts idle, without a native continuation or invented checkpoint")
    passed("disposed native scene actions cannot end the app home interaction or create a checkpoint")
    request = worker(bridge.request_story, "start", "before-the-first-light")
    assert type(request) is int
    marks["foreign_request"] = request


def rejected_foreign():
    assert state() is None and bridge.story_status()["state"] == "idle"
    assert not label_entries
    assert confirmations[-1]["request_id"] == marks["foreign_request"] and not confirmations[-1]["success"]
    passed("a command for the existing demo cannot start the optional Lantern story")
    submit_story("start", guard=True)


def entered():
    marks["run"] = expect("running", "arrival", same_run=False)
    marks["session"] = bridge.story_status()["session_id"]
    assert confirmations[-1]["action"] == "start" and confirmations[-1]["success"]
    assert adapter().session_id == marks["session"] and adapter().run_id == marks["run"]["run_id"]
    assert len(label_entries) == 1
    passed("Start confirms only after the actual native scene and running state exist")
    capture("arrival")


def scene_save():
    global checkpoint_digest
    before = state()
    assert store.sdk_native_story_save_from_scene(), store.sdk_native_story_message
    assert state() == before and bridge.save_status()["available"] and not bridge.save_status()["busy"]
    checkpoint_digest = digest()
    passed("the native Save button creates a checkpoint and publishes Load availability to A")


def queue_save():
    assert worker(bridge.request_save, "save") is True
    assert bridge.save_status()["busy"]
    blocked("pending save-menu command")
    assert worker(bridge.request_story, "resume", "lantern") is None


def check_saved_choice():
    global checkpoint_digest
    expect("running", "choice")
    assert bridge.save_status()["available"] and "saved" in bridge.save_status()["message"].lower()
    checkpoint_digest = digest()
    marks["checkpoint"] = state()
    passed("the separate save-menu command executes on the native thread at the choice checkpoint")
    assert store.sdk_native_story_choose("continue") is False
    assert store.sdk_native_story_choose("finish") is False
    assert state() == marks["checkpoint"]
    passed("stale Continue and Finish actions are rejected outside their native phase")


def check_returned(phase, route=None, direct=False):
    value = expect("returned", phase, route)
    assert store.sdk_native_story_last_result == store.sdk_native_story_status()
    assert bridge.story_status()["state"] == "suspended" and adapter().run_id == value["run_id"]
    assert store.sdk_native_story_return() is False and adapter().pending is None
    assert store.sdk_native_story_choose("continue") is False
    assert store.sdk_native_story_choose("finish") is False
    assert store.sdk_native_story_save_from_scene() is False
    assert confirmations[-1]["action"] == "return" and confirmations[-1]["success"]
    if direct:
        assert len(confirmations) == marks["return_confirmations"] + 1
    assert digest() == checkpoint_digest
    passed(("native Return" if direct else "worker Return") + " confirms after the native caller receives returned status")


def reading(name, value):
    def action():
        assert worker(bridge.request_reading, name, value) is True
        assert bridge.reading_status()["busy"]
        blocked("pending reading command")
        assert worker(bridge.request_story, "resume", "lantern") is None
    return action


def queue_load():
    assert store.persistent.renfletpy_large_text is True and store._preferences.text_cps == 30
    marks["old_session"] = bridge.story_status()["session_id"]
    marks["old_request"] = bridge.story_status()["request_id"]
    marks["current_route"] = bridge.story_status()["return_route"]
    Path(os.environ["SDK_NATIVE_LIFECYCLE_RECORDS"]).write_text('{"revision": 2}\n')
    bridge.set_presentation("diagnostics")
    assert worker(bridge.request_save, "load") is True
    assert bridge.save_status()["busy"]
    assert worker(bridge.request_story, "resume", "lantern") is None


def check_load():
    value = expect("running", "choice")
    assert value == marks["checkpoint"]
    current = bridge.story_status()
    assert current["session_id"] != marks["old_session"] and current["state"] == "active"
    assert current["request_id"] is None and not current["busy"] and adapter().pending is None
    assert adapter().run_id == value["run_id"] and adapter().sentinel_lock is sentinel
    assert bridge.presentation() == "diagnostics" and current["return_route"] == marks["current_route"]
    assert store.persistent.renfletpy_large_text is True and store._preferences.text_cps == 30
    assert bridge.reading_status()["large_text"] is True and bridge.reading_status()["text_speed"] == "animated"
    assert json.loads(Path(os.environ["SDK_NATIVE_LIFECYCLE_RECORDS"]).read_text()) == {"revision": 2}
    passed("manual Load restores older native progress with fresh runtime IDs and keeps current records and preferences")
    before = bridge.story_status()
    assert bridge.confirm_story_command(marks["old_request"], success=True) is False
    assert bridge.finish_story(marks["old_session"], result={"stale": True}) is False
    assert bridge.story_status() == before and bridge.presentation() == "diagnostics"
    assert before["return_route"] == marks["current_route"]
    passed("old confirmations and completions cannot alter the restored session, presentation or return route")
    blocked("diagnostics presentation")
    bridge.set_presentation("scene")
    capture("loaded-choice")


def finish_race():
    """Queue Return after Finish chooses a result, before native caller handoff."""
    try:
        store.sdk_native_story_choose("finish")
    except EndInteraction:
        marks["race_request"] = submit_story("return", guard=True)
        raise
    raise AssertionError("Finish did not select a native interaction result")


def check_completed():
    value = expect("completed", "done", "tower")
    current = bridge.story_status()
    assert current["state"] == "completed" and current["result"] == store.sdk_native_story_last_result
    assert current["result"] == store.sdk_native_story_status() and len(completions) == 1
    assert bridge.confirm_story_command(marks["race_request"], success=True) is False
    assert not any(item["request_id"] == marks["race_request"] and item["success"] for item in confirmations)
    before_calls = len(native_calls)
    assert adapter().handoff(store.sdk_native_story_last_result) is False
    assert not any(item["name"] == "finish_story" for item in native_calls[before_calls:])
    assert worker(bridge.request_story, "resume", "lantern") is None
    assert store.sdk_native_story_return() is False and bridge.story_status() == current
    assert digest() == checkpoint_digest
    passed("completion wins the late Return race, publishes once and rejects completed Resume")
    assert value["route"] == "tower"
    capture("completed")
    finish()


def lifecycle_steps():
    step("home", None, initial)
    step("home", None, rejected_foreign)
    step("scene", "arrival", entered)
    step("scene", "arrival", scene_save)
    step("scene", "arrival", choose("continue"))
    step("scene", "choice", queue_save)
    step("scene", "choice", check_saved_choice)
    step("scene", "choice", reading("large_text", True))
    step("scene", "choice", reading("large_text", False))
    step("scene", "choice", lambda: submit_resume(True))
    step("scene", "choice", lambda: check_resume("choice"))
    step("scene", "choice", direct_return)
    step("home", "choice", lambda: check_returned("choice", direct=True))
    step("home", "choice", lambda: submit_resume(False))
    step("scene", "choice", lambda: check_resume("choice"))
    step("scene", "choice", choose("garden"))
    step("scene", "ending", lambda: submit_story("return", route="/app/records?record=2", guard=True))
    step("home", "ending", lambda: check_returned("ending", "garden"))
    step("home", "ending", reading("large_text", True))
    step("home", "ending", reading("text_speed", "animated"))
    step("home", "ending", queue_load)
    step("scene", "choice", check_load)
    step("scene", "choice", choose("tower"))
    step("scene", "ending", finish_race)
    step("home", "done", check_completed)


def seed_checkpoint():
    global checkpoint_digest
    marks["run"] = expect("running", "choice", same_run=False)
    assert store.sdk_native_story_save_from_scene()
    checkpoint_digest = digest()
    assert bridge.save_status()["available"]
    passed("a real manual native checkpoint exists before background recovery")


def mobile_seed(status):
    expected = "running" if status == "active" else status
    route = "tower" if status == "returned" else "garden"
    expect(expected, "done" if status == "completed" else "ending", route)
    action = {"active": "return", "returned": "resume", "completed": "start"}[status]
    request = submit_story(action)
    dispatched = adapter().take(store.sdk_native_story_status(), scene_shown=status == "active")
    assert dispatched == action and adapter().pending["request_id"] == request
    assert adapter().sentinel_lock is sentinel
    game.interface.mobile_save()
    assert store.sdk_native_story_owns_slot("_reload-1") and digest() == checkpoint_digest
    passed("mobile_save keeps " + status + " native truth while the live adapter holds an unpickleable lock and pending command")
    finish(crash=True)


def seed_steps(status):
    step("home", None, lambda: submit_story("start"))
    step("scene", "arrival", choose("continue"))
    step("scene", "choice", seed_checkpoint)
    step("scene", "choice", choose("tower" if status == "returned" else "garden"))
    if status != "active":
        step("scene", "ending", direct_return if status == "returned" else choose("finish"))
    step("scene" if status == "active" else "home", "done" if status == "completed" else "ending",
         lambda: mobile_seed(status))


def check_recovery(status):
    global recovered_state, checkpoint_digest
    expected = "running" if status == "active" else status
    route = "tower" if status == "returned" else "garden"
    recovered_state = expect(expected, "done" if status == "completed" else "ending", route, same_run=False)
    marks["run"] = recovered_state
    current = bridge.story_status()
    assert current["state"] == {"active": "active", "returned": "suspended", "completed": "completed"}[status]
    assert current["request_id"] is None and not current["busy"] and current["result"] is None
    assert adapter().pending is None and bridge.take_story_command() is None
    assert adapter().run_id == recovered_state["run_id"] and adapter().session_id == current["session_id"]
    assert adapter().owner == OWNER and adapter().sentinel_lock is sentinel
    assert restores and not exports.can_load("_reload-1") and store.sdk_native_story_owns_slot(SLOT)
    checkpoint_digest = digest()
    assert len(completions) == 0, "Loading replayed a completion"
    passed("fresh-process " + status + " recovery replaces pending runtime IDs and consumes only its own reload")
    if status == "completed":
        assert store.sdk_native_story_last_result == store.sdk_native_story_status()
        assert store.sdk_native_story_last_result["result"] == "garden"
        assert worker(bridge.request_story, "resume", "lantern") is None
        before = len(native_calls)
        assert adapter().handoff(store.sdk_native_story_last_result) is False
        assert not any(item["name"] == "finish_story" for item in native_calls[before:])
        passed("completed recovery retains the plain caller result without replaying completion into A")
        finish()


def recover_steps(status):
    screen = "scene" if status == "active" else "home"
    phase = "done" if status == "completed" else "ending"
    step(screen, phase, lambda: check_recovery(status))
    if status != "completed":
        step(screen, phase, lambda: submit_resume(status == "active"))
        step("scene", "ending", lambda: check_resume("ending", "tower" if status == "returned" else "garden"))
        step("scene", "ending", direct_return)
        step("home", "ending", lambda: check_returned("ending", "tower" if status == "returned" else "garden", direct=True))
        step("home", "ending", finish)


def on_label(name, abnormal):
    if name == "sdk_native_story":
        assert type(store.action) is str, "A live command object entered native label parameters"
        label_entries.append(store.action)


def setup():
    actual = hashlib.sha256(Path(bridge.__file__).read_bytes()).hexdigest()
    assert actual == os.environ["SDK_NATIVE_MAILBOX_BRIDGE_SHA256"]
    assert adapter().owner == OWNER
    adapter().sentinel_lock = sentinel

    def native(name, original):
        def call(*args, **kwargs):
            assert threading.get_ident() == OWNER, "Native operation ran on a callback worker"
            native_calls.append({"name": name, "thread": threading.get_ident()})
            return original(*args, **kwargs)
        return call

    for name in ("take", "entered", "prepare_return", "handoff"):
        setattr(adapter(), name, native(name, getattr(adapter(), name)))
    original_restore = adapter().restore

    def restore(status):
        before = (bridge.presentation(), bridge.story_status()["return_route"])
        result = native("restore", original_restore)(status)
        assert before == (bridge.presentation(), bridge.story_status()["return_route"])
        if status["status"] != "unavailable":
            restores.append(dict(status))
        return result

    adapter().restore = restore
    original_confirm = bridge.confirm_story_command

    def confirm(request_id, *, success, message=""):
        before = bridge.story_status()
        accepted = native("confirm_story_command", original_confirm)(request_id, success=success, message=message)
        if accepted:
            status = store.sdk_native_story_status()
            if success:
                if before["action"] in ("start", "resume"):
                    assert status["status"] == "running" and exports.get_screen("sdk_native_story_scene") is not None
                else:
                    assert before["action"] == "return" and status["status"] == "returned"
                    assert store.sdk_native_story_last_result == status
            confirmations.append({"request_id": request_id, "action": before["action"],
                                  "success": success, "native_status": status["status"]})
        return accepted

    bridge.confirm_story_command = confirm
    original_finish = bridge.finish_story

    def complete(session_id, **kwargs):
        accepted = native("finish_story", original_finish)(session_id, **kwargs)
        if accepted:
            assert store.sdk_native_story_last_result == store.sdk_native_story_status()
            assert store.sdk_native_story_last_result["status"] == "completed"
            completions.append(session_id)
        return accepted

    bridge.finish_story = complete
    for name in ("save", "load", "save_persistent", "end_interaction", "screenshot"):
        setattr(store.renpy, name, native(name, getattr(store.renpy, name)))
    config.label_callbacks.append(on_label)
    if MODE == "mailbox-lifecycle":
        lifecycle_steps()
    elif MODE.endswith("-seed"):
        seed_steps(MODE.removeprefix("mailbox-").removesuffix("-seed"))
    elif MODE.endswith("-recover"):
        recover_steps(MODE.removeprefix("mailbox-").removesuffix("-recover"))
    else:
        raise ValueError("Unknown native mailbox mode: " + MODE)


def finish(crash=False):
    restore_disk()
    assert not disk_reads and native_calls and all(item["thread"] == OWNER for item in native_calls)
    assert workers and all(value != OWNER for value in workers)
    passed("worker submissions leave native flow, rendering and save/preference operations on one native owner")
    RECEIPT.write_text(json.dumps({"mode": MODE, "pid": os.getpid(), "checks": checks,
                                  "bridge_sha256": os.environ["SDK_NATIVE_MAILBOX_BRIDGE_SHA256"],
                                  "recipe_sha256": RECIPE_SHA256,
                                  "savedir": config.savedir, "state": state(),
                                  "last_result": store.sdk_native_story_last_result,
                                  "bridge_status": bridge.story_status(), "recovered_state": recovered_state,
                                  "native_owner": OWNER, "worker_submissions": len(workers),
                                  "native_operations": len(native_calls), "resume_without_disk": resume_checks,
                                  "confirmations": confirmations, "completion_publications": len(completions),
                                  "restores": restores, "label_entries": label_entries}, indent=2) + "\n")
    if crash:
        os._exit(0)
    exports.quit()


def tick():
    try:
        if time.monotonic() - started > 45:
            raise AssertionError("Native mailbox stalled at " + repr(steps[0] if steps else None)
                                 + " state=" + repr(state()) + " bridge=" + repr(bridge.story_status()))
        if not steps:
            return
        screen, phase, action = steps[0]
        name = "sdk_native_story_scene" if screen == "scene" else "sdk_native_story_app_home"
        if exports.get_screen(name) is None:
            return
        if phase is not None and (state() is None or state()["phase"] != phase):
            return
        if bridge.story_status()["busy"] or bridge.save_status()["busy"] or bridge.reading_status()["busy"]:
            return
        steps.popleft()
        action()
    except (EndInteraction, game.FullRestartException, game.QuitException):
        raise
    except Exception:
        restore_disk()
        traceback.print_exc()
        os._exit(1)
