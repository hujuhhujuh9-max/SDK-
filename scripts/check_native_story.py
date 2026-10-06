"""Exercise native Ren'Py save/load, interlude history and mobile recovery."""

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# The driver lives outside Ren'Py's rollback store, just like the Flet loop.
DRIVER = '''
import json
import os
import traceback
from pathlib import Path
import renpy.exports as renpy
from renpy import game as renpy_game
from renpy.display.core import EndInteraction
import renpy.store as store
import sdk_bridge
from renfletpy import SaveState, story

mode = os.environ["RENFLETPY_CHECK_MODE"]
phase = "tactics-recover" if mode == "tactics-recover" else "recover" if mode == "recover" else "opening"
checks = []
old_revision = None
paused_ticks = 0

def passed(name):
    checks.append(name)
    print("Passed: native " + name, flush=True)

def finish():
    Path(os.environ["RENFLETPY_CHECK_RECEIPT"]).write_text(json.dumps({
        "mode": mode, "pid": os.getpid(), "checks": checks}, indent=2) + "\\n")
    renpy.quit()

def tick():
    try:
        advance()
    except (EndInteraction, renpy_game.FullRestartException, renpy_game.QuitException):
        raise
    except Exception:
        traceback.print_exc()
        os._exit(1)

def advance():
    global phase, old_revision, paused_ticks
    if mode.startswith("tactics"):
        advance_tactics()
        return
    current = story.current()
    status = sdk_bridge.save_status()
    if phase == "opening":
        assert sdk_bridge.request_reading("large_text", True)
        phase = "reading-size"
    elif phase == "reading-size" and not sdk_bridge.reading_status()["busy"]:
        assert store.persistent.renfletpy_large_text
        assert renpy.get_displayable("say", "what").style.size == 40
        passed("shared large text updates the actual native dialogue")
        assert sdk_bridge.request_reading("text_speed", "animated")
        phase = "reading-pace"
    elif phase == "reading-pace" and not sdk_bridge.reading_status()["busy"]:
        assert store._preferences.text_cps == 30
        assert sdk_bridge.request_reading("text_speed", "instant")
        phase = "reading-ready"
    elif phase == "reading-ready" and not sdk_bridge.reading_status()["busy"]:
        assert store._preferences.text_cps == 0
        passed("dialogue pace changes through the native preference owner")
        phase = "puzzle"
        renpy.end_interaction(True)
    elif phase == "puzzle" and current is not None:
        assert current.kind == "star_map"
        story.tap_star(current.revision, "deneb")
        old_revision = current.revision
        if mode == "seed":
            renpy_game.interface.mobile_save()
            assert renpy.can_load("_reload-1")
            passed("background save captures a move without quick save")
            Path(os.environ["RENFLETPY_CHECK_RECEIPT"]).write_text(json.dumps({
                "mode": mode, "pid": os.getpid(), "checks": checks}, indent=2) + "\\n")
            os._exit(0)  # Simulate process loss, preserving the mobile reload.
        assert sdk_bridge.request_save("save")
        phase = "manual-saved"
    elif phase == "manual-saved" and not status["busy"]:
        assert "Saved." in status["message"], status
        assert sdk_bridge.request_reading("text_speed", "animated")
        phase = "manual-preference"
    elif phase == "manual-preference" and not sdk_bridge.reading_status()["busy"]:
        story.tap_star(current.revision, "vega")
        assert sdk_bridge.request_save("load")
        phase = "manual-loaded"
    elif phase == "manual-loaded" and not status["busy"]:
        assert current.progress == ("deneb",), current
        assert current.revision != old_revision
        assert not story.tap_star(old_revision, "altair")
        passed("quick save restores exact progress and fresh controls")
        assert store._preferences.text_cps == 30
        passed("loading an older quick save keeps the current reading preferences")
        assert sdk_bridge.request_reading("text_speed", "instant")
        phase = "manual-reading-reset"
    elif phase == "manual-reading-reset" and not sdk_bridge.reading_status()["busy"]:
        renpy_game.interface.mobile_save()
        story.tap_star(current.revision, "vega")
        phase = "background-loaded"
        renpy.load("_reload-1")
    elif phase == "background-loaded":
        assert current.progress == ("deneb",), current
        assert not renpy.can_load("_reload-1"), "Loaded background save was not consumed"
        passed("mobile save restores active minigame")
        renpy.force_autosave()
        phase = "auto-saving"
    elif phase == "auto-saving" and renpy.can_load("auto-1"):
        story.tap_star(current.revision, "vega")
        phase = "auto-loaded"
        renpy.load("auto-1")
    elif phase in ("auto-loaded", "recover"):
        assert current is not None and current.progress == ("deneb",), current
        assert isinstance(store._renfletpy_saved_state, SaveState)
        assert any("before sunrise" in entry.what for entry in store._history_list)
        assert not renpy.can_load("_reload-1"), "Stale recovery remains after a successful load"
        passed("fresh process recovers mobile save" if phase == "recover" else "autosave worker restores active minigame")
        if mode == "recover":
            assert store.persistent.renfletpy_large_text
            assert store._preferences.text_cps == 0
            assert sdk_bridge.reading_status()["large_text"]
            assert sdk_bridge.reading_status()["text_speed"] == "instant"
            passed("reading preferences survive process loss independently of the story save")
        sdk_bridge.set_presentation("page")
        story.tap_star(current.revision, "vega")
        story.tap_star(current.revision, "altair")
        paused_ticks = 0
        phase = "paused-menu-result"
    elif phase in ("paused-menu-result", "paused-diagnostic-result"):
        assert current is not None and current.selected == "aligned"
        assert not [entry for entry in store._history_list if entry.kind == "interlude"]
        paused_ticks += 1
        if paused_ticks < 3:
            return
        if phase == "paused-menu-result":
            sdk_bridge.set_presentation("diagnostics")
            phase = "paused-diagnostic-result"
            paused_ticks = 0
            return
        passed("menus and diagnostics hold a completed minigame until resume")
        sdk_bridge.set_presentation("interlude")
        phase = "result"
    elif phase == "result" and current is None:
        assert store.scene_title == "A sky worth waiting for"
        results = [entry for entry in store._history_list if entry.kind == "interlude"]
        assert len(results) == 1 and results[0].renfletpy_result == "Constellation aligned"
        passed("restored result returns once to native dialogue and history")
        if mode == "recover":
            finish()
        assert sdk_bridge.request_save("save")
        phase = "scene-saved"
    elif phase == "scene-saved" and not status["busy"]:
        phase = "panel"
        renpy.end_interaction(True)
    elif phase == "panel" and current is not None:
        assert current.speaker == "Field journal"
        renpy.save("probe-panel")
        old_revision = current.revision
        story.choose(current.revision, "company")
        phase = "panel-result"
    elif phase == "panel-result" and current is None:
        assert any(getattr(entry, "renfletpy_result", "") == "The company" for entry in store._history_list)
        phase = "panel-loaded"
        renpy.load("probe-panel")
    elif phase == "panel-loaded":
        assert current.speaker == "Field journal" and current.selected is None
        assert current.revision != old_revision
        assert not story.choose(old_revision, "company")
        assert not any(getattr(entry, "renfletpy_result", "") == "The company" for entry in store._history_list)
        passed("panel save restores choices and removes future history")
        story.choose(current.revision, "constellation")
        phase = "journal-result"
    elif phase == "journal-result" and current is None:
        assert any("next summer" in entry.what for entry in store._history_list)
        phase = "final-dialogue"
        renpy.end_interaction(True)
    elif phase == "final-dialogue":
        assert any("first light reaches" in entry.what for entry in store._history_list)
        phase = "ending"
        renpy.end_interaction(True)
    elif phase == "ending" and current is not None:
        assert current.speaker == "First light"
        history = sdk_bridge.transcript()
        if not history or history[-1][0] != "First light":
            return  # The shared-history timer runs independently of this driver.
        assert [entry[0] for entry in history] == ["Mira", "Star map", "Mira", "Field journal", "Mira", "Mira", "First light"], history
        passed("native dialogue and Flet results share chronological history")
        renpy.save("probe-ending")
        story.choose(current.revision, "replay")
        phase = "replayed"
    elif phase == "replayed" and current is None:
        assert store.scene_title == "Before the First Light"
        assert story.history() == ()
        assert len(store._history_list) == 1
        phase = "ending-loaded"
        renpy.load("probe-ending")
    elif phase == "ending-loaded":
        assert current.speaker == "First light"
        assert len(store._history_list) == 6
        passed("ending waits for explicit replay and can be restored after replay")
        phase = "scene-loaded"
        renpy.load("renfletpy-quick")
    elif phase == "scene-loaded":
        assert current is None and store.scene_title == "A sky worth waiting for"
        assert len([entry for entry in store._history_list if entry.kind == "interlude"]) == 1
        passed("normal scene save restores input and native history")
        finish()

def capture(name):
    renpy.screenshot(str(Path(os.environ["RENFLETPY_CHECK_RECEIPT"]).parent / (mode + "-" + name + ".png")))

def advance_tactics():
    global phase, old_revision, paused_ticks
    import renpy.pygame as pygame
    from tactics import Cell, GOAL, project
    current = story.current()
    status = sdk_bridge.save_status()
    view = store._tactics_view

    def click(x, y):
        px, py = view.screen_position(x, y)
        view.event(pygame.event.Event(pygame.MOUSEBUTTONUP, button=1), px, py, 0)

    if phase == "opening":
        phase = "tactics-stars"
        renpy.end_interaction(True)
    elif phase == "tactics-stars" and current is not None:
        story.choose(current.revision, "skipped")
        phase = "tactics-dialogue"
    elif phase == "tactics-dialogue" and current is None:
        phase = "tactics-journal"
        renpy.end_interaction(True)
    elif phase == "tactics-journal" and current is not None:
        story.choose(current.revision, "route")
        phase = "tactics-board"
    elif phase == "tactics-board" and current is not None and current.kind == "tactics":
        if view.state is None:
            return
        capture("start")
        assert view.scale > 0
        assert story.tactics_state().selected_uid == "scout"
        passed("adapted tactics board renders in the portrait story viewport")
        if mode == "tactics-skip":
            view.skip()
            phase = "tactics-skipped"
            return
        click(574, 210)
        assert story.current().selected_unit == "knight"
        click(430, 350)
        assert story.current().selected_unit == "scout"
        passed("native displayable taps select the painted units")
        click(376, 347)
        assert story.tactics_state().selected.cell == Cell(0, 4, 0)
        phase = "tactics-ground"
    elif phase == "tactics-ground":
        capture("ground")
        click(442, 284)
        assert story.tactics_state().selected.cell == Cell(1, 4, 1)
        passed("native taps move on ground and onto an elevated shelf")
        phase = "tactics-height"
    elif phase == "tactics-height":
        capture("height")
        view.reset()
        assert story.tactics_state().selected.cell == Cell(1, 4, 0)
        passed("native reset restores the route without restarting the story")
        phase = "tactics-reset"
    elif phase == "tactics-reset":
        capture("reset")
        click(376, 347)
        click(574, 210)
        old_revision = current.revision
        sdk_bridge.set_presentation("page")
        assert sdk_bridge.request_save("save")
        phase = "tactics-saved"
    elif phase == "tactics-saved" and not status["busy"]:
        before = story.current()
        click(*project(GOAL))
        view.reset()
        assert story.current() == before
        passed("the shared menu blocks native board taps and reset")
        sdk_bridge.set_presentation("scene")
        view.reset()
        assert sdk_bridge.request_save("load")
        phase = "tactics-loaded"
    elif phase == "tactics-loaded" and not status["busy"]:
        state = story.tactics_state()
        assert state.units[1].cell == Cell(0, 4, 0)
        assert state.selected_uid == "knight"
        assert current.revision != old_revision
        assert not story.move_tactics_unit(old_revision, GOAL)
        passed("native quick save restores every position, selection and fresh controls")
        capture("loaded")
        renpy.force_autosave()
        phase = "tactics-auto-saving"
    elif phase == "tactics-auto-saving" and renpy.can_load("auto-1"):
        story.reset_tactics(current.revision)
        phase = "tactics-auto-loaded"
        renpy.load("auto-1")
    elif phase == "tactics-auto-loaded":
        assert story.tactics_state().units[1].cell == Cell(0, 4, 0)
        assert current.selected_unit == "knight"
        passed("native worker autosave captures the live tactics board")
        renpy_game.interface.mobile_save()
        assert renpy.can_load("_reload-1")
        passed("mobile save captures the tactics board before process loss")
        Path(os.environ["RENFLETPY_CHECK_RECEIPT"]).write_text(json.dumps({
            "mode": mode, "pid": os.getpid(), "checks": checks}, indent=2) + "\\n")
        os._exit(0)
    elif phase == "tactics-recover":
        assert current is not None and current.kind == "tactics"
        assert story.tactics_state().units[1].cell == Cell(0, 4, 0)
        assert current.selected_unit == "knight"
        assert not renpy.can_load("_reload-1")
        if view.state is None or view.revision != current.revision:
            return
        capture("recovered")
        passed("a fresh Ren’Py process recovers the moved board and native screen")
        sdk_bridge.set_presentation("scene")
        story.select_tactics_unit(current.revision, "scout")
        click(*project(GOAL))
        assert story.current().selected == "reached"
        sdk_bridge.set_presentation("page")
        paused_ticks = 0
        phase = "tactics-paused-result"
    elif phase == "tactics-paused-result":
        assert current is not None and current.selected == "reached"
        assert not any(getattr(entry, "renfletpy_result", "") == "Scout reached the balcony"
                       for entry in store._history_list)
        paused_ticks += 1
        if paused_ticks < 3:
            return
        passed("a completed tactics result waits for shared-menu resume")
        sdk_bridge.set_presentation("scene")
        phase = "tactics-result"
    elif phase in ("tactics-result", "tactics-skipped") and current is None:
        reached = phase == "tactics-result"
        expected = "Scout reached the balcony" if reached else "Route skipped"
        results = [entry for entry in store._history_list
                   if getattr(entry, "renfletpy_result", "") == expected]
        assert len(results) == 1
        assert any(("found a path" if reached else "balcony can wait") in entry.what
                   for entry in store._history_list)
        passed("tactics completion returns once to native dialogue and history" if reached
               else "skipping the native route resumes its story branch")
        capture("result")
        finish()
'''


def check(sdk, output):
    output.mkdir(parents=True, exist_ok=True)
    binary = shutil.which("Xvfb")
    if binary is None:
        candidate = ROOT / ".android-build/xserver/root/usr/bin/Xvfb"
        if candidate.is_file():
            binary = str(candidate)
    if binary is None:
        raise RuntimeError("Install Xvfb to exercise native Ren'Py rendering and saves.")
    workspace = Path(tempfile.mkdtemp(prefix="project-", dir=output))
    read_fd, write_fd = os.pipe()
    try:
        with (output / "xserver.log").open("w") as server_log:
            server = subprocess.Popen([binary, "-displayfd", str(write_fd), "-screen", "0",
                                       "720x1280x24", "-ac", "-nolisten", "tcp"],
                                      pass_fds=(write_fd,), stdout=server_log, stderr=server_log)
            try:
                os.close(write_fd)
                write_fd = None
                if not select.select([read_fd], [], [], 30)[0]:
                    raise RuntimeError("Xvfb did not provide a display; see xserver.log")
                display = ":" + os.read(read_fd, 64).decode().strip()
                receipts = []
                for mode in ("warm", "seed", "recover", "tactics-seed", "tactics-recover", "tactics-skip"):
                    # All processes use the same compiled game. Independently
                    # compiling separate projects creates different statement
                    # identities and cannot model a restart of the same APK.
                    project = workspace / "game-project"
                    game = project / "game"
                    game.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(ROOT / "game/script.rpy", game / "script.rpy")
                    for source in (ROOT / "game").glob("*.py"):
                        shutil.copyfile(source, game / source.name)
                    for source in (ROOT / "runtime").glob("*.py"):
                        shutil.copyfile(source, project / source.name)
                    (project / "native_story_check.py").write_text(DRIVER)
                    (game / "probe.rpy").write_text('''init 1 python:
    import native_story_check
    config.overlay_screens.append("native_story_check")
    if os.environ["RENFLETPY_CHECK_MODE"] in ("recover", "tactics-recover"):
        config.auto_load = "_reload-1"

screen native_story_check():
    timer 0.15 repeat True action Function(native_story_check.tick, _update_screens=False)
''')
                    receipt = output / (mode + ".json")
                    receipt.unlink(missing_ok=True)
                    env = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy",
                               RENFLETPY_CHECK_MODE=mode, RENFLETPY_CHECK_RECEIPT=str(receipt))
                    saves = workspace / ("tactics-saves" if mode.startswith("tactics") and mode != "tactics-skip"
                                         else "skip-saves" if mode == "tactics-skip"
                                         else "warm-saves" if mode == "warm" else "cold-saves")
                    with (output / (mode + ".log")).open("w") as log:
                        result = subprocess.run([str(sdk / "renpy.sh"), str(project), "run",
                                                 "--savedir", str(saves)], env=env, stdout=log,
                                                stderr=subprocess.STDOUT, timeout=60)
                    if result.returncode or not receipt.is_file():
                        raise RuntimeError(f"Native {mode} check failed; see {output / (mode + '.log')}")
                    data = json.loads(receipt.read_text())
                    receipts.append(data)
                    print(json.dumps(data), flush=True)
                assert receipts[1]["pid"] != receipts[2]["pid"]
                assert receipts[3]["pid"] != receipts[4]["pid"]
                (output / "results.json").write_text(json.dumps(receipts, indent=2) + "\n")
            finally:
                server.terminate()
                server.wait(timeout=10)
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        shutil.rmtree(workspace)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renpy-sdk", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/native-story-check")
    args = parser.parse_args()
    sdk = args.renpy_sdk
    if sdk is None:
        sys.path.insert(0, str(ROOT))
        from prepare import BuildInputs
        sdk = BuildInputs(ROOT / ".android-build").sdk_root("renpy")
    check(sdk.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
