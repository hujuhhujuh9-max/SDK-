"""Native-thread acceptance driver; loaded only in verifier-created projects."""

import hashlib
import json
import os
import traceback
from collections import deque
from pathlib import Path

import renpy
import renpy.exports as exports
import renpy.store as store
from renpy import config, game
from renpy.display.core import EndInteraction

MODE = os.environ["SDK_NATIVE_LIFECYCLE_MODE"]
RECEIPT = Path(os.environ["SDK_NATIVE_LIFECYCLE_RECEIPT"])
SLOT = "sdk-native-lantern-checkpoint"
checks = []
marks = {}
steps = deque()
resume_pending = False
disk_methods = []
disk_reads = []
resume_checks = 0
completion_handoffs = []
last_handoff = None
recovered_state = None
checkpoint_digest = None


def passed(message):
    checks.append(message)
    print("Passed: native lifecycle " + message, flush=True)


def state():
    value = store.sdk_native_story_state
    return dict(value) if value is not None else None


def expect(status, phase, route=None, same_run=None):
    value = state()
    assert value is not None and value["status"] == status and value["phase"] == phase, value
    assert value["route"] == route, value
    if same_run is not None:
        assert value["run_id"] == marks[same_run]["run_id"], (value, marks[same_run])
    return value


def step(screen, phase, action):
    steps.append((screen, phase, action))


def select(value, trap_resume=False):
    def action():
        global resume_pending
        resume_pending = trap_resume
        exports.end_interaction(value)
    return action


def on_label(name, abnormal):
    global resume_pending
    if name != "sdk_native_story" or not resume_pending:
        return
    assert store.action == "resume"
    resume_pending = False

    def forbidden(name):
        def call(*args, **kwargs):
            disk_reads.append(name)
            raise AssertionError("Resume read native save API: " + name)
        return call

    # Ren'Py supplies its exported namespace to .rpy author code.
    for module in (store.renpy,):
        for name in ("can_load", "slot_json", "load"):
            disk_methods.append((module, name, getattr(module, name)))
            setattr(module, name, forbidden(name))


def restore_disk_methods():
    while disk_methods:
        module, name, original = disk_methods.pop()
        setattr(module, name, original)


def on_python():
    global last_handoff
    result = getattr(store, "sdk_native_story_last_result", None)
    if result is last_handoff:
        return
    last_handoff = result
    if result is not None and result["status"] == "completed":
        completion_handoffs.append(result["run_id"])


def archive(slot):
    return Path(config.savedir) / (slot + renpy.savegame_suffix)


def digest(slot=SLOT):
    return hashlib.sha256(archive(slot).read_bytes()).hexdigest()


def save_checkpoint():
    global checkpoint_digest
    assert store.sdk_native_story_save_checkpoint(), store.sdk_native_story_message
    assert store.sdk_native_story_owns_slot(SLOT)
    checkpoint_digest = digest()


def capture(name):
    exports.screenshot(str(RECEIPT.parent / (MODE + "-" + name + ".png")))


def check_initial():
    marks["run"] = expect("running", "arrival")
    assert store.sdk_native_story_last_result is None
    assert not store.sdk_native_story_can_resume()
    before = state()
    for action in ("start", "resume"):
        result = exports.call_in_new_context("sdk_native_story", action)
        assert result["status"] == "busy", result
        assert state() == before
    passed("Start enters one native story; reentrant calls cannot replace it")
    save_checkpoint()
    marks["first"] = state()
    passed("the callable story saves during its first native interaction")
    capture("arrival")


def check_return(phase, route=None):
    value = expect("returned", phase, route, "run")
    result = store.sdk_native_story_last_result
    assert result == {"story_id": "lantern", "run_id": value["run_id"],
                      "status": "returned", "phase": phase, "result": None}, result
    assert store.sdk_native_story_can_resume()
    assert not exports.can_load("_reload-1"), "Return left an earlier recovery timeline"
    passed("Return preserves the live " + phase + " phase and returns plain caller data")


def mobile_then(value):
    def action():
        game.interface.mobile_save()
        assert store.sdk_native_story_owns_slot("_reload-1")
        assert digest() == checkpoint_digest
        exports.end_interaction(value)
    return action


def check_live(phase, route=None):
    expect("running", phase, route, "run")
    passed("Resume reenters the live " + phase + " phase")


def load_checkpoint():
    assert store.sdk_native_story_owns_slot(SLOT)
    store.sdk_native_story_load_checkpoint()
    raise AssertionError("A compatible checkpoint did not transfer native control")


def check_first_load():
    expect("running", "arrival", same_run="first")
    assert "restored" in store.sdk_native_story_message.lower()
    passed("explicit Load restores the first interaction instead of replaying Start")


def save_choice():
    expect("running", "choice", same_run="run")
    before = state()
    original_save, original_load = store.renpy.save, store.renpy.load

    def failed(*args, **kwargs):
        raise OSError("simulated native storage failure")

    try:
        store.renpy.save = failed
        assert store.sdk_native_story_save_checkpoint() is False
        assert state() == before and "Could not save" in store.sdk_native_story_message
    finally:
        store.renpy.save = original_save
    save_checkpoint()
    passed("a native save error keeps live state and a later retry succeeds")
    try:
        store.renpy.load = failed
        assert store.sdk_native_story_load_checkpoint() is False
        assert state() == before and "Could not load" in store.sdk_native_story_message
        store.renpy.load = lambda *args, **kwargs: None
        assert store.sdk_native_story_load_checkpoint() is False
        assert state() == before and "cancelled" in store.sdk_native_story_message
    finally:
        store.renpy.load = original_load
    passed("native load errors and declined loads keep live state without reporting success")
    marks["choice"] = state()
    Path(os.environ["SDK_NATIVE_LIFECYCLE_RECORDS"]).write_text('{"revision": 2}\n')
    passed("a later checkpoint captures native choice state")


def check_choice_load():
    expect("running", "choice", same_run="choice")
    records = Path(os.environ["SDK_NATIVE_LIFECYCLE_RECORDS"])
    assert json.loads(records.read_text()) == {"revision": 2}
    passed("Load restores older story state while current application data stays current")


def check_completion():
    value = expect("completed", "done", "tower", "run")
    assert store.sdk_native_story_last_result == {
        "story_id": "lantern", "run_id": value["run_id"], "status": "completed",
        "phase": "done", "result": "tower"}
    assert completion_handoffs == [value["run_id"]]
    assert not store.sdk_native_story_can_resume()
    assert not exports.can_load("_reload-1"), "Completion left an earlier recovery timeline"
    passed("completion hands one result back to the caller and closes live continuation")


def check_completed_resume():
    expect("completed", "done", "tower", "run")
    assert store.sdk_native_story_last_result["status"] == "unavailable"
    assert store.sdk_native_story_last_result["result"] is None
    assert len(completion_handoffs) == 1
    passed("Resume after completion cannot emit the completed result again")


def check_restart():
    value = expect("running", "arrival")
    assert value["run_id"] != marks["run"]["run_id"]
    assert digest() == checkpoint_digest
    assert not exports.can_load("_reload-1"), "Start left an earlier recovery timeline"
    passed("new Start resets live state while preserving the manual checkpoint")


def lifecycle_steps():
    step("home", None, select("start"))
    step("scene", "arrival", check_initial)
    for phase, route, advance in (("arrival", None, "continue"),
                                  ("choice", None, "tower"),
                                  ("ending", "tower", None)):
        step("scene", phase, mobile_then("return"))
        step("home", phase, lambda p=phase, r=route: check_return(p, r))
        step("home", phase, select("resume", trap_resume=True))
        step("scene", phase, lambda p=phase, r=route: check_live(p, r))
        if advance is not None:
            step("scene", phase, select(advance))
    step("scene", "ending", load_checkpoint)
    step("scene", "arrival", check_first_load)
    step("scene", "arrival", select("continue"))
    step("scene", "choice", save_choice)
    step("scene", "choice", select("garden"))
    step("scene", "ending", select("return"))
    step("home", "ending", select("resume", trap_resume=True))
    step("scene", "ending", lambda: check_live("ending", "garden"))
    step("scene", "ending", load_checkpoint)
    step("scene", "choice", check_choice_load)
    step("scene", "choice", select("tower"))
    step("scene", "ending", mobile_then("finish"))
    step("home", "done", check_completion)
    step("home", "done", select("resume"))
    step("home", "done", check_completed_resume)
    step("home", "done", mobile_then("start"))
    step("scene", "arrival", check_restart)
    step("scene", "arrival", lambda: finish())


def seed_save():
    marks["run"] = expect("running", "choice")
    save_checkpoint()
    passed("manual checkpoint exists before the newer background continuation")


def mobile_seed():
    expected_status = MODE.removesuffix("-seed")
    status = "running" if expected_status == "active" else expected_status
    phase = "done" if status == "completed" else "ending"
    route = "tower" if status == "returned" else "garden"
    expect(status, phase, route, "run")
    game.interface.mobile_save()
    assert store.sdk_native_story_owns_slot("_reload-1")
    assert digest() == checkpoint_digest
    passed("native mobile_save captures " + expected_status + " state without replacing the checkpoint")
    finish(crash=True)


def seed_steps(status):
    step("home", None, select("start"))
    step("scene", "arrival", select("continue"))
    step("scene", "choice", seed_save)
    step("scene", "choice", select("tower" if status == "returned" else "garden"))
    if status != "active":
        step("scene", "ending", select("return" if status == "returned" else "finish"))
    step("scene" if status == "active" else "home", "done" if status == "completed" else "ending", mobile_seed)


def check_recovery(status):
    global recovered_state
    current_status = "running" if status == "active" else status
    phase = "done" if status == "completed" else "ending"
    route = "tower" if status == "returned" else "garden"
    recovered_state = expect(current_status, phase, route)
    assert not exports.can_load("_reload-1")
    assert store.sdk_native_story_owns_slot(SLOT)
    assert "restored" in store.sdk_native_story_message.lower()
    assert store.sdk_native_story_can_resume() == (status == "returned")
    if status == "completed":
        assert store.sdk_native_story_last_result["status"] == "completed"
    passed("a fresh native process recovers " + status + " state and consumes only its recovery save")
    capture("recovered")


def recover_steps(status):
    screen = "scene" if status == "active" else "home"
    phase = "done" if status == "completed" else "ending"
    step(screen, phase, lambda: check_recovery(status))
    if status == "returned":
        step("home", "ending", select("resume", trap_resume=True))
        step("scene", "ending", lambda: expect("running", "ending", "tower"))
        step("scene", "ending", lambda: finish())
    else:
        step(screen, phase, lambda: finish())


def check_checkpoint_override():
    expect("running", "choice")
    assert "restored" in store.sdk_native_story_message.lower()
    assert store.sdk_native_story_owns_slot(SLOT)
    passed("a valid explicit auto-load override restores only an owned checkpoint")
    finish()


def begin_autosave():
    marks["auto"] = expect("running", "choice")
    exports.force_autosave()


def await_autosave():
    if not exports.can_load("auto-1"):
        steps.appendleft(("scene", "choice", await_autosave))
        return
    identity = {"profile": store.SDK_NATIVE_STORY_PROFILE, "story_id": "lantern", "schema": 1}
    assert exports.slot_json("auto-1")["sdk_native_story"] == identity
    assert archive("auto-1").is_file()
    passed("native worker autosave stamps immutable profile metadata in the isolated archive")


def load_autosave():
    expect("running", "ending", "garden", "auto")
    Path(os.environ["SDK_NATIVE_LIFECYCLE_RECORDS"]).write_text('{"revision": 3}\n')
    exports.load("auto-1")
    raise AssertionError("Native worker autosave did not transfer control")


def check_autosave_load():
    expect("running", "choice", same_run="auto")
    assert json.loads(Path(os.environ["SDK_NATIVE_LIFECYCLE_RECORDS"]).read_text()) == {"revision": 3}
    passed("native worker autosave restores its story phase while newer application data stays current")
    finish()


def autosave_steps():
    step("home", None, select("start"))
    step("scene", "arrival", select("continue"))
    step("scene", "choice", begin_autosave)
    step("scene", "choice", await_autosave)
    step("scene", "choice", select("garden"))
    step("scene", "ending", load_autosave)
    step("scene", "choice", check_autosave_load)


def check_android_profile():
    private = Path(os.environ["SDK_NATIVE_LIFECYCLE_PRIVATE"])
    expected = private / "saves" / store.SDK_NATIVE_STORY_PROFILE
    assert Path(store._sdk_lifecycle_android_savedir) == expected
    assert Path(config.savedir) == expected
    assert expected != private / "saves"
    assert not renpy.android, "Android simulation leaked into SDL runtime ownership"
    passed("the real early Android branch selects an app-private profile child before native startup")


def android_mobile():
    save_checkpoint()
    game.interface.mobile_save()
    assert store.sdk_native_story_owns_slot("_reload-1")
    assert archive(SLOT).is_file() and archive("_reload-1").is_file()
    passed("manual and engine-owned mobile archives use the explicit Android profile directory")
    store._sdk_native_story_clear_recovery()
    finish()


def check_guard():
    assert state() is None, "An incompatible recovery hijacked optional startup"
    assert config.auto_load is None
    assert not store.sdk_native_story_can_resume()
    assert not store.sdk_native_story_owns_slot(SLOT)
    assert not store.sdk_native_story_owns_slot("_reload-1")
    passed("incompatible recovery metadata leaves startup on the optional home")
    original = store.renpy.load

    def forbidden(*args, **kwargs):
        raise AssertionError("An incompatible manual checkpoint reached native load")

    try:
        store.renpy.load = forbidden
        assert store.sdk_native_story_load_checkpoint() is False
        assert "compatible saved checkpoint" in store.sdk_native_story_message
    finally:
        store.renpy.load = original
    assert state() is None
    assert archive(SLOT).is_file() and archive("_reload-1").is_file()
    passed("incompatible manual metadata is refused without restoring or deleting either archive")


def check_foreign_cleanup():
    assert archive(SLOT).is_file() and archive("_reload-1").is_file()
    assert not store.sdk_native_story_owns_slot("_reload-1")
    passed("Start and Return preserve a foreign recovery archive instead of deleting it")
    finish(crash=True)


def guard_override():
    original = store._sdk_native_story_startup

    def guarded():
        try:
            original()
        except RuntimeError as error:
            assert "RENPY_AUTO_LOAD" in str(error)
            passed("the real startup guard rejects an incompatible environment auto-load override")
            finish(crash=True)
        raise AssertionError("Invalid RENPY_AUTO_LOAD bypassed the profile guard")

    config.start_callbacks[config.start_callbacks.index(original)] = guarded


def check_demo_library():
    assert config.save_directory == "sdk-runner-integration"
    assert not store._sdk_native_story_profile_installed
    assert store._sdk_native_story_metadata not in config.save_json_callbacks
    assert store._sdk_native_story_startup not in config.start_callbacks
    assert store._sdk_native_story_after_load not in config.after_load_callbacks
    assert state() is None and not store.sdk_native_story_can_resume()
    assert store.sdk_native_story_save_checkpoint() is False
    assert store.sdk_native_story_load_checkpoint() is False
    passed("copying only the callable library leaves demo entry, callbacks and save profile inactive")


def demo_seed_steps():
    import sdk_bridge
    from renfletpy import story
    step("say", None, check_demo_library)
    step("say", None, select(True))

    def quick_save():
        current = story.current()
        assert current.kind == "star_map"
        assert story.tap_star(current.revision, "deneb")
        assert sdk_bridge.request_save("save")

    def mobile():
        if sdk_bridge.save_status()["busy"]:
            steps.appendleft(("interlude", None, mobile))
            return
        assert exports.can_load("renfletpy-quick")
        assert "sdk_native_story" not in exports.slot_json("renfletpy-quick")
        current = story.current()
        assert story.tap_star(current.revision, "vega")
        game.interface.mobile_save()
        assert exports.can_load("_reload-1")
        passed("the unchanged demo produces its native quick and newer mobile saves")
        finish(crash=True)

    step("interlude", None, quick_save)
    step("interlude", None, mobile)


def demo_recover():
    from renfletpy import story
    current = story.current()
    assert current.kind == "star_map" and current.progress == ("deneb", "vega"), current
    assert exports.can_load("renfletpy-quick") and not exports.can_load("_reload-1")
    assert not store._sdk_native_story_profile_installed
    passed("the demo still recovers its newer native interlude after all optional story checks")
    finish()


def setup():
    if MODE.startswith("demo-"):
        if MODE == "demo-seed":
            demo_seed_steps()
        else:
            config.auto_load = "_reload-1"
            step("interlude", None, demo_recover)
        return
    if MODE == "android-profile":
        original_android = store.renpy.android
        original_private = os.environ.get("ANDROID_PRIVATE")
        try:
            store.renpy.android = True
            os.environ["ANDROID_PRIVATE"] = os.environ["SDK_NATIVE_LIFECYCLE_PRIVATE"]
            store.sdk_native_story_install_profile(auto_recover=True)
        finally:
            store.renpy.android = original_android
            if original_private is None:
                os.environ.pop("ANDROID_PRIVATE", None)
            else:
                os.environ["ANDROID_PRIVATE"] = original_private
    else:
        store.sdk_native_story_install_profile(auto_recover=True)
    config.label_callbacks.append(on_label)
    config.python_callbacks.append(on_python)
    if MODE == "lifecycle":
        lifecycle_steps()
    elif MODE.endswith("-seed"):
        seed_steps(MODE.removesuffix("-seed"))
    elif MODE.endswith("-recover"):
        recover_steps(MODE.removesuffix("-recover"))
    elif MODE == "checkpoint-override":
        step("scene", "choice", check_checkpoint_override)
    elif MODE == "autosave":
        autosave_steps()
    elif MODE == "android-profile":
        step("home", None, check_android_profile)
        step("home", None, select("start"))
        step("scene", "arrival", android_mobile)
    elif MODE.startswith("guard-"):
        step("home", None, check_guard)
        step("home", None, select("start"))
        step("scene", "arrival", select("return"))
        step("home", "arrival", check_foreign_cleanup)
    elif MODE.startswith("override-reject-"):
        guard_override()
    else:
        raise ValueError("Unknown native lifecycle mode: " + MODE)


def finish(crash=False):
    restore_disk_methods()
    RECEIPT.write_text(json.dumps({"mode": MODE, "pid": os.getpid(), "checks": checks,
                                  "savedir": config.savedir, "state": state(),
                                  "last_result": getattr(store, "sdk_native_story_last_result", None),
                                  "recovered_state": recovered_state,
                                  "resume_without_disk": resume_checks,
                                  "completion_handoffs": len(completion_handoffs)}, indent=2) + "\n")
    if crash:
        os._exit(0)
    exports.quit()


def tick():
    global resume_checks
    try:
        if disk_methods and exports.get_screen("sdk_native_story_scene") is not None:
            restore_disk_methods()
            assert not disk_reads, disk_reads
            resume_checks += 1
            passed("callable Resume reaches its native scene without can_load, slot_json or load")
        if not steps:
            return
        screen, phase, action = steps[0]
        name = {"home": "sdk_native_story_home", "scene": "sdk_native_story_scene",
                "say": "say", "interlude": "renfletpy_input"}[screen]
        if exports.get_screen(name) is None:
            return
        if phase is not None:
            assert state() is not None and state()["phase"] == phase, (phase, state())
        # Native interactions transfer control with exceptions. Consume the
        # driver operation before invoking one so loads do not repeat it.
        steps.popleft()
        action()
    except (EndInteraction, game.FullRestartException, game.QuitException):
        raise
    except Exception:
        restore_disk_methods()
        traceback.print_exc()
        os._exit(1)
