"""Native/Flet acceptance fixture; not packaged in the application."""

import hashlib
import json
import os
import traceback
from collections import deque
from pathlib import Path

import renpy
import renpy.exports as native
import renpy.store as store
from renpy import config, game
from renpy.display.core import EndInteraction

import native_app_bridge
import sdk_bridge
from native_app_ui import AppUI

MODE = os.environ["SDK_NATIVE_LIFECYCLE_MODE"]
RECEIPT = Path(os.environ["SDK_NATIVE_LIFECYCLE_RECEIPT"])
steps = deque()
checks = []
marks = {}
ui = None
disk_methods = []
loads = 0


def passed(message):
    checks.append(message)
    print("Passed: native app bridge " + message, flush=True)


def value():
    return dict(store.sdk_native_story_status())


def digest():
    slot = Path(config.savedir) / (store.SDK_NATIVE_STORY_SLOT + renpy.savegame_suffix)
    return hashlib.sha256(slot.read_bytes()).hexdigest()


def step(screen, phase, state, action):
    steps.append((screen, phase, state, action))


def ui_route(route):
    ui.call(ui.navigate(route))


def assert_route(route):
    snapshot = ui.call(ui.snapshot())
    assert snapshot["route"] == route, snapshot


def request(action, replace=False):
    before = sdk_bridge.story_status()
    if action == "start":
        if replace:
            ui_route("/app/story")
            ui.call(ui.click("Start from beginning"))
            assert_route("/app/story/start")
            assert not sdk_bridge.story_status()["busy"], "Opening confirmation submitted Start"
            ui.call(ui.click("Start again"))
        else:
            ui_route("/app")
            ui.call(ui.click("Start story"))
    elif action == "resume":
        ui_route("/app")
        ui.call(ui.click("Resume story"))
    elif action == "cancel":
        ui_route("/app/story")
        ui.call(ui.click("Cancel story"))
        assert_route("/app/story/cancel")
        assert not sdk_bridge.story_status()["busy"], "Opening confirmation submitted Cancel"
        ui.call(ui.click("Confirm cancellation"))
    else:
        async def back():
            await ui.page.on_view_pop(None)
        ui.call(back())
    current = sdk_bridge.story_status()
    assert current["busy"] and current["state"] == before["state"], (before, current)
    assert sdk_bridge.request_story(action, "lantern") is None, "Duplicate request was accepted"
    marks["request"] = current["request_id"]
    passed(action + " uses the Flet event loop and waits for native confirmation")


def start_scene():
    current = sdk_bridge.story_status()
    assert current["session_id"] == marks["request"] and current["state"] == "active", current
    marks["session"] = current["session_id"]
    marks["run"] = value()["run_id"]
    assert_route("/")
    assert store.sdk_native_story_save_checkpoint()
    metadata = native.slot_json(store.SDK_NATIVE_STORY_SLOT)
    assert metadata["sdk_app_host"] == 1 and store.sdk_native_story_owns_slot(store.SDK_NATIVE_STORY_SLOT), (
        metadata, type(metadata).__name__, type(metadata.get("sdk_app_host")).__name__)
    assert sdk_bridge.save_status()["available"], "Native Save did not refresh the shared bookmark status"
    marks["checkpoint"] = digest()
    passed("Start confirms only after the actual native scene; saves identify this caller host")
    native.end_interaction("continue")


def return_concurrently():
    request("return")
    # This button can win the race with the command timer. The ordinary caller
    # still consumes and confirms the pending command once.
    store.sdk_native_story_return()


def trap_resume():
    assert sdk_bridge.story_status()["session_id"] == marks["session"]
    assert value()["run_id"] == marks["run"] and digest() == marks["checkpoint"]
    assert_route("/app")

    def forbidden(*args, **kwargs):
        raise AssertionError("Live Resume attempted native save I/O")

    for name in ("can_load", "slot_json", "load"):
        disk_methods.append((name, getattr(store.renpy, name)))
        setattr(store.renpy, name, forbidden)
    request("resume")


def restore_disk():
    while disk_methods:
        name, method = disk_methods.pop()
        setattr(store.renpy, name, method)


def resumed():
    restore_disk()
    assert value()["run_id"] == marks["run"] and sdk_bridge.story_status()["session_id"] == marks["session"]
    assert_route("/")
    passed("Resume preserves native continuation/session and never reads the older checkpoint")
    store.sdk_native_story_return()


def resume_return_race():
    request("resume")
    store.sdk_native_story_return()


def paused_after_resume_race():
    assert not sdk_bridge.story_status()["busy"] and native_app_bridge._driver.command is None
    assert sdk_bridge.story_status()["session_id"] == marks["session"]
    assert_route("/app")
    passed("native Return racing with Resume publishes suspension and releases the mailbox")
    request("resume")


def complete():
    current = sdk_bridge.story_status()
    assert current["result"] == value() and current["result"]["result"] in ("garden", "tower"), current
    assert not sdk_bridge.finish_story(current["session_id"], result=value())
    assert_route("/app/story/result")
    passed("native completion reaches a readable result once with a confirmed plain payload")


def replace():
    marks["old_session"] = sdk_bridge.story_status()["session_id"]
    marks["old_run"] = value()["run_id"]
    request("start", replace=True)
    assert not sdk_bridge.finish_story(marks["old_session"], result={"stale": True})


def replaced():
    current = sdk_bridge.story_status()
    assert current["session_id"] != marks["old_session"] and value()["run_id"] != marks["old_run"], current
    assert current["session_id"] == marks["request"]
    assert not sdk_bridge.confirm_story_command(marks["request"], success=True)
    passed("confirmed replacement starts one fresh native run and retires the preceding result")
    request("cancel")


def cancelled(finish_when_done=True):
    assert store.sdk_native_story_state is None and not store.sdk_native_story_can_resume()
    assert_route("/app")
    assert sdk_bridge.app_story_status()["result"]["status"] == "cancelled"
    assert digest() == marks["checkpoint"], "Cancel removed the independent manual checkpoint"
    passed("Cancel unwinds native flow, clears continuation, and keeps the manual bookmark")
    if finish_when_done:
        finish()


def early_return():
    if not marks.get("early_return") or native.get_screen("sdk_native_story_scene") is None:
        return
    if value()["run_id"] == marks.get("skip_early_run"):
        return
    assert sdk_bridge.story_status()["busy"], "Early Return did not precede the native acknowledgement"
    marks["early_return"] = False
    marks["early_publication"] = True
    marks["early_origin"] = ui.call(ui.snapshot())["route"]
    store.sdk_native_story_return()


def fast_start():
    marks["early_return"] = True
    request("start")


def fast_started():
    marks["early_publication"] = False
    current = sdk_bridge.story_status()
    assert current["session_id"] == marks["request"] and current["state"] == "suspended", current
    assert store.sdk_native_story_can_resume() and native_app_bridge._driver.command is None
    assert_route("/app")
    passed("native Return before Start acknowledgement binds a paused session across a forced Flet turn")
    request("resume")


def fast_replace():
    marks["early_return"] = True
    marks["skip_early_run"] = value()["run_id"]
    replace()


def fast_replaced():
    marks["early_publication"] = False
    current = sdk_bridge.story_status()
    assert current["session_id"] == marks["request"] and current["session_id"] != marks["old_session"]
    assert value()["run_id"] != marks["old_run"] and store.sdk_native_story_can_resume()
    assert_route("/app/story/start")
    assert not sdk_bridge.story_status()["busy"] and native_app_bridge._driver.command is None
    passed("immediate Return from replacement preserves its new continuation and route across a forced Flet turn")
    finish()


def save_recovery():
    # The pending request exists solely in runtime modules, outside the saved
    # caller context; a fresh process must discard it and publish native truth.
    current = sdk_bridge.story_status()
    pending = sdk_bridge.request_story("return" if current["state"] == "active" else "start", "lantern",
                                      expected_revision=sdk_bridge.app_story_status()["revision"],
                                      replace=current["state"] == "suspended")
    assert pending is not None
    marks["abandoned_request"] = pending
    marks["seed_session"] = current["session_id"]
    native.take_screenshot()
    native.save("_reload-1", extra_info="Optional app bridge recovery")
    passed("native recovery archive excludes the pending runtime command and Flet page/services")
    finish(crash=True)


def check_recovery():
    seed = json.loads((RECEIPT.parent / MODE.replace("-recover", "-seed")).with_suffix(".json").read_text())
    current = sdk_bridge.story_status()
    assert seed["pid"] != os.getpid()
    assert current["session_id"] != seed["marks"]["seed_session"]
    assert value()["run_id"] == seed["state"]["run_id"]
    assert not current["busy"] and current["request_id"] is None, current
    assert not sdk_bridge.confirm_story_command(seed["marks"]["abandoned_request"], success=True)
    assert not sdk_bridge.finish_story(seed["marks"]["seed_session"], result={"stale": True})
    assert not native.can_load("_reload-1")
    assert_route("/app/records?recovered=1")
    assert ui.call(ui.records_draft()) == "Unsubmitted application draft"
    marks["run"], marks["session"] = value()["run_id"], current["session_id"]
    marks["checkpoint"] = digest()
    passed("fresh-process recovery retires commands/results and keeps explicit records plus its draft")


def resume_active():
    check_recovery()
    marks["action"] = store.action
    request("resume")


def active_acknowledged():
    assert store.action == marks["action"] and value()["phase"] == "choice"
    assert sdk_bridge.story_status()["session_id"] == marks["session"]
    passed("Resume of an already restored native interaction is acknowledged in place")
    store.sdk_native_story_return()


def load_checkpoint():
    marks["before_load"] = sdk_bridge.story_status()["session_id"]
    assert_route("/app")
    ui_route("/app/records?recovered=1")
    ui.call(ui.records_draft("A newer application edit"))
    sdk_bridge.request_story("start", "lantern", expected_revision=sdk_bridge.app_story_status()["revision"], replace=True)
    store.sdk_native_story_load_checkpoint()
    raise AssertionError("Successful checkpoint Load did not transfer native control")


def checkpoint_loaded():
    assert loads == 2 and value()["phase"] == "arrival"
    assert sdk_bridge.story_status()["session_id"] != marks["before_load"]
    assert not sdk_bridge.story_status()["busy"]
    assert_route("/app/records?recovered=1")
    assert ui.call(ui.records_draft()) == "A newer application edit"
    assert digest() == marks["checkpoint"]
    passed("explicit checkpoint Load refreshes identities without restoring application data or route")
    request("resume")


def on_load():
    global loads
    loads += 1


def setup():
    global ui
    if renpy.game.args.command != "run":
        return
    recovering = MODE.endswith("-recover")
    ui = AppUI("/app/records?recovered=1" if recovering else "/app")
    if recovering:
        ui.call(ui.records_draft("Unsubmitted application draft"))
    config.after_load_callbacks.append(on_load)
    original_tick = native_app_bridge.tick
    def delayed_acknowledgement():
        # Fault injection: an arbitrarily late polling tick must not orphan an
        # entered story whose native Return button has already been pressed.
        if (marks.get("early_return")
                and native.get_screen("sdk_native_story_scene") is not None
                and value()["run_id"] != marks.get("skip_early_run")):
            return
        original_tick()
    native_app_bridge.tick = delayed_acknowledgement
    original_refresh = sdk_bridge._refresh_story_status
    def interleaved_publication(command=None):
        original_refresh(command)
        if marks.get("early_publication"):
            # Force UI handling between entry confirmation and the already
            # known Return. An active Start event must never escape here.
            assert_route(marks["early_origin"])
    sdk_bridge._refresh_story_status = interleaved_publication
    if MODE == "app-lifecycle":
        step("idle", None, "idle", lambda: request("start"))
        step("scene", "arrival", "active", start_scene)
        step("scene", "choice", "active", return_concurrently)
        step("idle", "choice", "suspended", trap_resume)
        step("scene", "choice", "active", resumed)
        step("idle", "choice", "suspended", lambda: request("resume"))
        step("scene", "choice", "active", resume_return_race)
        step("idle", "choice", "suspended", paused_after_resume_race)
        step("scene", "choice", "active", lambda: native.end_interaction("garden"))
        step("scene", "ending", "active", lambda: native.end_interaction("finish"))
        step("idle", "done", "completed", lambda: (complete(), request("start")))
        step("scene", "arrival", "active", replace)
        step("scene", "arrival", "active", replaced)
        step("idle", None, "cancelled", lambda: cancelled(False))
        step("idle", None, "cancelled", fast_start)
        step("idle", "arrival", "suspended", fast_started)
        step("scene", "arrival", "active", fast_replace)
        step("idle", "arrival", "suspended", fast_replaced)
    elif MODE.endswith("-seed"):
        state = MODE.split("-")[1]
        step("idle", None, "idle", lambda: request("start"))
        step("scene", "arrival", "active", start_scene)
        if state == "active":
            step("scene", "choice", "active", save_recovery)
        elif state == "returned":
            step("scene", "choice", "active", return_concurrently)
            step("idle", "choice", "suspended", save_recovery)
        else:
            step("scene", "choice", "active", lambda: native.end_interaction("tower"))
            step("scene", "ending", "active", lambda: native.end_interaction("finish"))
            step("idle", "done", "completed", lambda: (complete(), save_recovery()))
    elif MODE == "app-active-recover":
        step("scene", "choice", "active", resume_active)
        step("scene", "choice", "active", active_acknowledged)
        step("idle", "choice", "suspended", load_checkpoint)
        step("scene", "arrival", "active", checkpoint_loaded)
        step("scene", "arrival", "active", lambda: request("cancel"))
        step("idle", None, "cancelled", cancelled)
    elif MODE == "app-returned-recover":
        step("idle", "choice", "suspended", lambda: (check_recovery(), ui_route("/app"), trap_resume()))
        step("scene", "choice", "active", resumed)
        step("idle", "choice", "suspended", finish)
    elif MODE == "app-completed-recover":
        def completed_recovery():
            check_recovery()
            assert sdk_bridge.story_status()["result"] == value()
            assert sdk_bridge.app_story_status()["result"]["status"] == "completed"
            assert sdk_bridge.request_story("resume", "lantern") is None
            passed("completed recovery publishes its result without inventing a resumable bookmark")
            finish()
        step("idle", "done", "completed", completed_recovery)
    elif MODE.startswith("app-foreign-"):
        def foreign_host():
            checkpoint = Path(config.savedir) / (store.SDK_NATIVE_STORY_SLOT + renpy.savegame_suffix)
            recovery = Path(config.savedir) / ("_reload-1" + renpy.savegame_suffix)
            before = [hashlib.sha256(path.read_bytes()).hexdigest() for path in (checkpoint, recovery)]
            assert not store.sdk_native_story_owns_slot(store.SDK_NATIVE_STORY_SLOT)
            assert not store.sdk_native_story_owns_slot("_reload-1")
            assert not store.sdk_native_story_load_checkpoint()
            assert store.sdk_native_story_state is None and config.auto_load is None
            assert [hashlib.sha256(path.read_bytes()).hexdigest() for path in (checkpoint, recovery)] == before
            passed("foreign caller schema rejects checkpoint and recovery without deleting their archives")
            finish()
        step("idle", None, "idle", foreign_host)
    else:
        raise ValueError("Unknown mode: " + MODE)


def finish(crash=False):
    restore_disk()
    snapshot = ui.call(ui.snapshot())
    ui.close()
    RECEIPT.write_text(json.dumps({"mode": MODE, "pid": os.getpid(), "checks": checks,
        "state": value(), "bridge": sdk_bridge.story_status(), "marks": marks,
        "ui": snapshot, "loads": loads, "native_thread": native_app_bridge._driver.thread,
        "flet_thread": ui.thread.ident}, indent=2) + "\n")
    if crash:
        os._exit(0)
    native.quit()


def tick():
    if not steps:
        return
    try:
        screen, phase, state, action = steps[0]
        name = "sdk_app_idle" if screen == "idle" else "sdk_native_story_scene"
        if native.get_screen(name) is None:
            return
        status = sdk_bridge.story_status()
        if status["busy"] or status["state"] != state:
            return
        if phase is not None:
            assert value()["phase"] == phase, (phase, value())
        steps.popleft()
        action()
    except (EndInteraction, game.FullRestartException, game.QuitException):
        raise
    except Exception:
        restore_disk()
        traceback.print_exc()
        os._exit(1)
