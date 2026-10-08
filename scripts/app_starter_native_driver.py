"""Independent Ren'Py-side acceptance driver for the optional app recipe."""

import os
from pathlib import Path

import renpy.exports as renpy
from renpy import config
from renpy import game
import renpy.store as store

import sdk_bridge
from app_session import session
from renfletpy import story

phase = "opening"
ticks = 0
old_story_revision = None
old_app_revision = None


def request(action):
    assert sdk_bridge.request_app_story(action, session.status()["revision"]), action


def advance(driver):
    global phase, ticks, old_story_revision, old_app_revision
    state = session.status()
    current = story.current()
    save = sdk_bridge.save_status()
    mode = driver.mode
    expected = Path(os.environ["APP_STORY_SAVE_ROOT"]) / "app-starter"
    assert Path(config.savedir).resolve() == expected.resolve(), config.savedir

    if phase == "opening":
        if mode == "app-completed-recover":
            if state["phase"] != "completed" or not renpy.get_screen("app_recipe_home_wait"):
                return
            assert state["result"]["value"] == "You kept a note from the lighthouse."
            assert state["resume_kind"] == "saved" and state["resume_available"]
            assert not renpy.can_load("_reload-1")
            assert not session.complete(state["revision"], "duplicate")
            driver.passed("completed mobile recovery returns home once and retains the explicit bookmark")
            driver.finish()
        elif mode == "app-recover":
            if state["phase"] != "active" or current is None:
                return
            assert current.speaker == "The folded note"
            assert current.selected is None
            assert store._app_recipe_state["phase"] == "active"
            assert not renpy.can_load("_reload-1"), "Stale app mobile recovery remains"
            driver.passed("app native mobile save recovers in a fresh process and is consumed")
            request("resume")
            phase = "recovered"
        elif mode in ("app-saved", "app-completed-seed"):
            if state["resume_kind"] != "saved":
                return
            assert state["phase"] == "ready" and not state["showing_story"]
            assert not sdk_bridge.request_app_story("start", state["revision"])
            request("resume")
            phase = "completed-resumed" if mode == "app-completed-seed" else "saved-resumed"
        else:
            if not renpy.get_screen("app_recipe_home_wait"):
                return
            assert state["phase"] == "ready"
            driver.passed("explicit app entry waits without starting the native story")
            request("start")
            assert not sdk_bridge.request_app_story("start", state["revision"])
            phase = "started"
    elif phase == "started":
        if state["busy"] or not renpy.get_screen("say"):
            return
        assert state["phase"] == "active" and state["showing_story"]
        assert "folded note" in store._history_list[-1].what
        old_app_revision = state["revision"]
        driver.passed("one native Start establishes the callable story without app restart")
        request("return")
        phase = "returned"
    elif phase == "returned" and not state["busy"]:
        assert not state["showing_story"] and state["resume_kind"] == "live"
        assert not renpy.can_load("app-recipe-quick"), "Return alone silently saved a bookmark"
        sdk_bridge.set_presentation("page")
        ticks = 0
        phase = "held"
    elif phase == "held":
        ticks += 1
        assert current is None and "folded note" in store._history_list[-1].what
        if ticks < 3:
            return
        driver.passed("Return holds the live native dialogue and makes no durability claim")
        request("resume")
        phase = "live-resumed"
    elif phase == "live-resumed" and not state["busy"]:
        assert state["showing_story"] and state["revision"] == old_app_revision
        sdk_bridge.set_presentation("scene")
        driver.passed("live Resume reveals the same native interaction")
        phase = "panel"
        renpy.end_interaction(True)
    elif phase == "panel" and current is not None:
        assert current.speaker == "The folded note"
        old_story_revision = current.revision
        old_app_revision = state["revision"]
        sdk_bridge.set_presentation("page")
        assert sdk_bridge.request_save("save")
        phase = "saved"
    elif phase == "saved" and not save["busy"]:
        assert renpy.can_load("app-recipe-quick") and "Saved." in save["message"], save
        metadata = renpy.slot_json("app-recipe-quick")
        assert metadata["app_story"] == store._app_recipe_state
        driver.passed("native app bookmark contains plain recipe identity and real script/interlude state")
        if mode == "app-seed":
            game.interface.mobile_save()
            assert renpy.can_load("_reload-1")
            driver.passed("app namespace receives the native Android-style mobile recovery slot")
            driver.write_receipt()
            os._exit(0)
        assert story.choose(current.revision, "keep")
        assert sdk_bridge.request_save("load")
        phase = "loaded"
    elif phase == "loaded" and not save["busy"]:
        if current is None or current.revision == old_story_revision:
            return
        assert current.selected is None
        assert not story.choose(old_story_revision, "share")
        assert state["revision"] > old_app_revision
        assert not session.complete(old_app_revision, "stale native result")
        driver.passed("native app load restores the exact choice with fresh story/session revisions")
        request("return")
        phase = "panel-returned"
    elif phase == "panel-returned" and not state["busy"]:
        sdk_bridge.set_presentation("page")
        assert story.choose(current.revision, "keep")
        ticks = 0
        phase = "choice-held"
    elif phase == "choice-held":
        ticks += 1
        assert current is not None and current.selected == "keep"
        if ticks < 3:
            return
        driver.passed("Return keeps a completed interlude pending until native Resume")
        request("resume")
        phase = "choice-resumed"
    elif phase == "choice-resumed" and not state["busy"]:
        sdk_bridge.set_presentation("interlude")
        phase = "last-dialogue"
    elif phase == "last-dialogue" and current is None and renpy.get_screen("say"):
        assert "remember where" in store._history_list[-1].what
        phase = "completed"
        renpy.end_interaction(True)
    elif phase == "completed" and state["phase"] == "completed":
        assert state["result"]["value"] == "You kept a note from the lighthouse."
        assert not state["showing_story"] and not state["busy"]
        assert not session.complete(state["revision"], "duplicate")
        assert renpy.can_load("app-recipe-quick"), "Completion deleted an explicit native bookmark"
        driver.passed("native completion returns one plain result without quitting or restarting the app")
        if mode == "app-completed-seed":
            game.interface.mobile_save()
            assert renpy.can_load("_reload-1")
            driver.passed("completed story creates a native mobile snapshot for app-home recovery")
            driver.write_receipt()
            os._exit(0)
        driver.finish()
    elif phase == "completed-resumed" and not state["busy"]:
        assert current is not None and current.speaker == "The folded note"
        assert story.choose(current.revision, "keep")
        sdk_bridge.set_presentation("interlude")
        phase = "last-dialogue"
    elif phase in ("recovered", "saved-resumed") and not state["busy"]:
        assert current is not None and current.speaker == "The folded note"
        assert current.selected is None and state["phase"] == "active"
        assert state["showing_story"] and state["resume_kind"] == "live"
        driver.passed("saved Resume uses native load and becomes a live interaction"
                      if phase == "saved-resumed" else "recovered story resumes its exact interlude")
        driver.finish()
