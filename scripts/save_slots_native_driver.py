"""Named native bookmarks across distinct positions and independent builds."""

import hashlib
from pathlib import Path

import renpy.exports as renpy
from renpy import config
import renpy.store as store

import sdk_bridge
from app_session import session
from renfletpy import story

phase = "opening"
protected = {}
old_revision = None


def files():
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in Path(config.savedir).glob("*.save")
            if not path.name.startswith("renfletpy-manual-")}


def request(action, name=None, title=None):
    status = sdk_bridge.save_browser_status()
    options = {"name": name} if action == "create" else {}
    if title is not None:
        options["slot"] = next(row["slot"] for row in status["slots"] if row["name"] == title)
    assert sdk_bridge.request_save(action, revision=status["revision"], **options), (action, status)


def advance(driver):
    global phase, protected, old_revision
    app = driver.mode.startswith("app-")
    cold = driver.mode.endswith("cold")
    current = story.current()
    status = sdk_bridge.save_status()
    if status["busy"]:
        return
    if phase == "opening":
        if cold:
            assert sdk_bridge.request_save("list")
            phase = "cold-listed"
            return
        if app:
            state = session.status()
            if state["phase"] == "ready" and renpy.get_screen("app_recipe_home_wait"):
                assert sdk_bridge.request_app_story("start", state["revision"], replace=True)
                phase = "starting"
        elif current is not None and current.kind == "star_map":
            phase = "starting"
        elif renpy.get_screen("say"):
            renpy.end_interaction(True)
    elif phase == "starting":
        if app and (session.status()["busy"] or not renpy.get_screen("say")):
            return
        sdk_bridge.set_presentation("page")
        quick = "app-recipe-quick" if app else "renfletpy-quick"
        renpy.take_screenshot()
        renpy.save(quick, extra_info="Protected quick bookmark")
        renpy.save("auto-7", extra_info="Protected autosave")
        protected = files()
        assert sdk_bridge.request_save("list")
        phase = "listed"
    elif phase == "listed":
        assert sdk_bridge.save_browser_status()["ready"]
        request("create", name="Before choice")
        phase = "first-saved"
    elif phase == "first-saved":
        assert len(sdk_bridge.save_browser_status()["slots"]) == 1
        if app:
            sdk_bridge.set_presentation("scene")
            phase = "later-position"
            renpy.end_interaction(True)
        else:
            assert story.tap_star(current.revision, "deneb")
            request("create", name="Later choice")
            phase = "second-saved"
    elif phase == "later-position" and current is not None:
        assert current.speaker == "The folded note" and current.selected is None
        sdk_bridge.set_presentation("page")
        request("create", name="Later choice")
        phase = "second-saved"
    elif phase == "second-saved":
        assert len(sdk_bridge.save_browser_status()["slots"]) == 2
        if not app:
            assert story.tap_star(current.revision, "vega")
        request("overwrite", title="Later choice")
        phase = "overwritten"
    elif phase == "overwritten":
        assert len(sdk_bridge.save_browser_status()["slots"]) == 2
        request("create", name="Temporary save")
        phase = "temporary"
    elif phase == "temporary":
        assert len(sdk_bridge.save_browser_status()["slots"]) == 3
        request("delete", title="Temporary save")
        phase = "deleted"
    elif phase == "deleted":
        assert len(sdk_bridge.save_browser_status()["slots"]) == 2
        assert files() == protected, "Named writes changed a quick or automatic save"
        driver.passed("two named native bookmarks, overwrite and delete preserve quick/autosave bytes")
        old_revision = current.revision if current is not None else None
        request("load", title="Before choice")
        phase = "warm-loaded"
    elif phase == "warm-loaded":
        if app:
            assert current is None and renpy.get_screen("say")
            assert "folded note" in store._history_list[-1].what
            assert session.status()["showing_story"]
        else:
            assert current.kind == "star_map" and current.progress == ()
            assert current.revision != old_revision
        assert files() == protected
        driver.passed("named native load restores the earlier actual story position")
        driver.finish()
    elif phase == "cold-listed":
        rows = sdk_bridge.save_browser_status()["slots"]
        assert {row["name"] for row in rows} == {"Before choice", "Later choice"}
        protected = files()
        request("load", title="Later choice")
        phase = "cold-later-loaded"
    elif phase == "cold-later-loaded":
        if app:
            assert current is not None and current.speaker == "The folded note" and current.selected is None
            assert session.status()["phase"] == "active" and session.status()["showing_story"]
        else:
            assert current.kind == "star_map" and current.progress == ("deneb", "vega")
        driver.passed("second named bookmark preserves its overwritten position after a fresh build/process")
        request("load", title="Before choice")
        phase = "cold-first-loaded"
    elif phase == "cold-first-loaded":
        if app:
            assert current is None and renpy.get_screen("say")
            assert "folded note" in store._history_list[-1].what
            assert session.status()["showing_story"]
            sdk_bridge.set_presentation("scene")
            phase = "complete-choice"
            renpy.end_interaction(True)
        else:
            assert current.kind == "star_map" and current.progress == ()
            for star in ("deneb", "vega", "altair"):
                assert story.tap_star(current.revision, star)
            sdk_bridge.set_presentation("interlude")
            phase = "complete-choice"
    elif phase == "complete-choice" and current is not None and current.kind == "panel":
        assert current.selected is None
        assert story.choose(current.revision, "keep" if app else current.choices[0][0])
        sdk_bridge.set_presentation("interlude")
        phase = "complete-native"
    elif phase == "complete-choice" and not app and current is None and renpy.get_screen("say"):
        renpy.end_interaction(True)
    elif phase == "complete-native" and current is None and renpy.get_screen("say"):
        if app:
            assert "remember where" in store._history_list[-1].what
            driver.passed("independently compiled first bookmark continues into native ending dialogue")
            phase = "app-completed"
        elif "first light reaches" in store._history_list[-1].what:
            driver.passed("independently compiled first bookmark continues into native ending dialogue")
            phase = "complete-finale"
        renpy.end_interaction(True)
    elif phase == "complete-finale" and current is not None:
        assert current.speaker == "First light"
        assert files() == protected
        driver.finish()
    elif phase == "app-completed" and session.status()["phase"] == "completed":
        assert session.status()["result"]["value"] == "You kept a note from the lighthouse."
        assert files() == protected
        driver.passed("named story load reaches actual completion without altering quick/autosaves")
        driver.finish()
