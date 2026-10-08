"""Exercise native Ren'Py save/load, interlude history and mobile recovery."""

import argparse
import hashlib
import io
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check_app(sdk, output):
    """Use the existing driver and pinned SDK with separately staged variants."""
    from build_android import stage_runtime

    output.mkdir(parents=True, exist_ok=True)
    binary = shutil.which("Xvfb")
    if binary is None:
        candidate = ROOT / ".android-build/xserver/root/usr/bin/Xvfb"
        if candidate.is_file():
            binary = str(candidate)
    if binary is None:
        raise RuntimeError("Install Xvfb to exercise native app story saves.")
    workspace = Path(tempfile.mkdtemp(prefix="app-project-", dir=output))
    read_fd, write_fd = os.pipe()
    try:
        with (output / "xserver.log").open("w") as server_log:
            server = subprocess.Popen([binary, "-displayfd", str(write_fd), "-screen", "0",
                                       "1080x1920x24", "-ac", "-nolisten", "tcp"],
                                      pass_fds=(write_fd,), stdout=server_log, stderr=server_log)
            try:
                os.close(write_fd)
                write_fd = None
                if not select.select([read_fd], [], [], 30)[0]:
                    raise RuntimeError("Xvfb did not provide an app-check display")
                display = ":" + os.read(read_fd, 64).decode().strip()
                save_root = workspace / "native-saves"
                receipts = []
                default_hashes = None
                trusted_bookmarks = {}
                modes = ("opening-mobile-seed", "app-warm", "app-seed", "app-recover",
                         "app-saved", "app-trust-cancel", "app-trust-accept",
                         "app-completed-seed", "app-completed-recover",
                         "opening-mobile-recover")
                for mode in modes:
                    template = "app" if mode.startswith("app-") else "story"
                    project = workspace / ("app-warm-project" if mode == "app-warm" else template + "-project")
                    if mode == "app-trust-cancel":
                        # Preserve the real native state/metadata, but model an
                        # unsigned bookmark copied from another installation.
                        for bookmark in (save_root / "app-starter/app-recipe-quick-LT1.save",
                                         project / "game/saves/app-recipe-quick-LT1.save"):
                            if not bookmark.is_file():
                                continue
                            trusted_bookmarks[bookmark] = bookmark.read_bytes()
                            unsigned = io.BytesIO()
                            with zipfile.ZipFile(io.BytesIO(trusted_bookmarks[bookmark])) as source, \
                                    zipfile.ZipFile(unsigned, "w") as target:
                                for member in source.infolist():
                                    if member.filename != "signatures":
                                        target.writestr(member, source.read(member))
                            bookmark.write_bytes(unsigned.getvalue())
                        assert trusted_bookmarks, "Missing real native bookmark for trust-prompt checks"
                    elif mode == "app-completed-seed":
                        for bookmark, data in trusted_bookmarks.items():
                            bookmark.write_bytes(data)
                    game = project / "game"
                    game.mkdir(parents=True, exist_ok=True)
                    for source in (ROOT / "game").glob("*.rpy"):
                        shutil.copyfile(source, game / source.name)
                    for source in (ROOT / "game").glob("*.py"):
                        shutil.copyfile(source, game / source.name)
                    stage_runtime(project, template)
                    shutil.copyfile(ROOT / "scripts/native_story_driver.py", project / "native_story_check.py")
                    shutil.copyfile(ROOT / "scripts/app_starter_native_driver.py",
                                    project / "app_starter_native_driver.py")
                    # Fixture the platform's chosen root before the app's python
                    # early block, without --savedir overriding its namespace.
                    (game / "00_app_save_root.rpy").write_text('''python early:
    import os
    renpy.__main__.path_to_saves = lambda gamedir, save_directory=None: os.environ["APP_STORY_SAVE_ROOT"]
''')
                    (game / "probe.rpy").write_text('''init 2 python:
    import native_story_check
    config.overlay_screens.append("native_story_check")
    config.default_fullscreen = True
    if os.environ["RENFLETPY_CHECK_MODE"].startswith("app-"):
        # Native-only fixture models the connected host. Real Flet ownership
        # and routing are checked separately through its actual protocol.
        sdk_bridge._story_detach = lambda: None
    else:
        assert not renpy.has_screen("confirm"), "App confirmation leaked into default startup"
    if os.environ["RENFLETPY_CHECK_MODE"] in ("app-recover", "app-completed-recover", "opening-mobile-recover"):
        config.auto_load = "_reload-1"

screen native_story_check():
    timer 0.15 repeat True action Function(native_story_check.tick, _update_screens=False)
''')
                    receipt = output / (mode + ".json")
                    receipt.unlink(missing_ok=True)
                    env = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy",
                               APP_STORY_SAVE_ROOT=str(workspace / "warm-saves" if mode == "app-warm" else save_root),
                               RENFLETPY_CHECK_MODE=mode,
                               RENFLETPY_CHECK_RECEIPT=str(receipt))
                    with (output / (mode + ".log")).open("w") as log:
                        result = subprocess.run([str(sdk / "renpy.sh"), str(project), "run"],
                                                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=75)
                    if result.returncode or not receipt.is_file():
                        raise RuntimeError(f"Native {mode} failed; see {output / (mode + '.log')}")
                    data = json.loads(receipt.read_text())
                    data["startup_template"] = template
                    receipts.append(data)
                    print(json.dumps(data), flush=True)
                    current_hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                      for p in save_root.glob("*.save")}
                    if mode == "opening-mobile-seed":
                        assert "_reload-1-LT1.save" in current_hashes
                        default_hashes = current_hashes
                    elif template == "app":
                        assert current_hashes == default_hashes, "App changed the default story's saves"
                assert receipts[2]["pid"] != receipts[3]["pid"] != receipts[4]["pid"]
                assert receipts[0]["pid"] != receipts[-1]["pid"]
                summary = {"startup_template": "app", "success": True,
                           "checks": ["default native recovery retained byte-for-byte through app saves",
                                      "default story still loads its original mobile recovery",
                                      "app warm/manual/mobile/saved resume passes in real native processes",
                                      "unsigned native save confirmation refuses and accepts through real signature checks"],
                           "receipts": receipts}
                (output / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
            finally:
                server.terminate()
                server.wait(timeout=10)
    finally:
        os.close(read_fd)
        if write_fd is not None:
            os.close(write_fd)
        shutil.rmtree(workspace)


def check(sdk, output, legacy_sdk=None, baseline_game_script=None):
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
                                       "1080x1920x24", "-ac", "-nolisten", "tcp"],
                                      pass_fds=(write_fd,), stdout=server_log, stderr=server_log)
            try:
                os.close(write_fd)
                write_fd = None
                if not select.select([read_fd], [], [], 30)[0]:
                    raise RuntimeError("Xvfb did not provide a display; see xserver.log")
                display = ":" + os.read(read_fd, 64).decode().strip()
                receipts = []
                modes = ("warm", "seed", "recover", "tactics-seed", "tactics-recover", "tactics-skip", "basic", "opening")
                if baseline_game_script is not None:
                    modes += ("baseline-seed", "baseline-load")
                modes += ("opening-mobile-seed", "opening-mobile-recover",
                          "replay-mobile-seed", "replay-mobile-recover")
                if legacy_sdk is not None:
                    modes += ("legacy-seed", "legacy-recover")
                for mode in modes:
                    # All processes use the same compiled game. Independently
                    # compiling separate projects creates different statement
                    # identities and cannot model a restart of the same APK.
                    project = workspace / "game-project"
                    game = project / "game"
                    game.mkdir(parents=True, exist_ok=True)
                    script = baseline_game_script if mode == "baseline-seed" else ROOT / "game/script.rpy"
                    shutil.copyfile(script, game / "script.rpy")
                    for source in (ROOT / "game").glob("*.rpy"):
                        if source.name != "script.rpy":
                            shutil.copyfile(source, game / source.name)
                    for source in (ROOT / "game").glob("*.py"):
                        shutil.copyfile(source, game / source.name)
                    if mode == "basic":
                        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                                        "color=c=blue:s=64x64:r=10", "-t", "0.5", "-an", "-c:v",
                                        "libx264", "-pix_fmt", "yuv420p", str(game / "probe.mp4")], check=True)
                    for source in (ROOT / "runtime").glob("*.py"):
                        shutil.copyfile(source, project / source.name)
                    shutil.copyfile(ROOT / "scripts/native_story_driver.py", project / "native_story_check.py")
                    (game / "probe.rpy").write_text('''init 1 python:
    import native_story_check
    config.overlay_screens.append("native_story_check")
    config.default_fullscreen = True
    if os.environ["RENFLETPY_CHECK_MODE"] in ("recover", "tactics-recover", "opening-mobile-recover", "replay-mobile-recover"):
        config.auto_load = "_reload-1"
    elif os.environ["RENFLETPY_CHECK_MODE"] == "basic":
        config.label_overrides["start"] = "native_basic_check"

screen native_story_check():
    timer 0.15 repeat True action Function(native_story_check.tick, _update_screens=False)

screen choice(items):
    vbox:
        for item in items:
            textbutton item.caption action item.action

screen native_basic_input(prompt):
    vbox:
        text prompt
        input id "input"

default basic_choices = []
default basic_name = ""
default basic_stage = "opening"

label native_basic_check:
    $ renpy.random.seed(12345)
    "First interaction."
    menu:
        "Take the path":
            $ basic_choices.append("path")
        "Wait":
            $ basic_choices.append("wait")
    $ basic_name = renpy.input("Your name?", screen="native_basic_input")
    pause 0.1
    $ renpy.movie_cutscene("probe.mp4", delay=0.1)
    $ basic_stage = "saved"
    "Snapshot ready."
    $ basic_draw = renpy.random.random()
    $ basic_stage = "drawn"
    "Random value [basic_draw]."
    return
''')
                    receipt = output / (mode + ".json")
                    receipt.unlink(missing_ok=True)
                    env = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy",
                               RENFLETPY_CHECK_MODE=mode.removeprefix("legacy-"), RENFLETPY_CHECK_RECEIPT=str(receipt))
                    saves = workspace / ("legacy-saves" if mode.startswith("legacy-")
                                         else "tactics-saves" if mode.startswith("tactics") and mode != "tactics-skip"
                                         else "skip-saves" if mode == "tactics-skip"
                                         else "opening-saves" if mode == "opening"
                                         else "baseline-saves" if mode.startswith("baseline-")
                                         else "opening-mobile-saves" if mode.startswith("opening-mobile-")
                                         else "replay-mobile-saves" if mode.startswith("replay-mobile-")
                                         else "warm-saves" if mode == "warm" else "cold-saves")
                    with (output / (mode + ".log")).open("w") as log:
                        engine = legacy_sdk if mode == "legacy-seed" else sdk
                        result = subprocess.run([str(engine / "renpy.sh"), str(project), "run",
                                                 "--savedir", str(saves)], env=env, stdout=log,
                                                stderr=subprocess.STDOUT, timeout=60)
                    if result.returncode or not receipt.is_file():
                        raise RuntimeError(f"Native {mode} check failed; see {output / (mode + '.log')}")
                    data = json.loads(receipt.read_text())
                    data["mode"] = mode
                    if mode in ("opening-mobile-recover", "replay-mobile-recover"):
                        marker = "SDK_RUNNER_SAVE action=loaded kind=scene progress=0 pid=" + str(data["pid"])
                        assert marker in (output / (mode + ".log")).read_text()
                    receipt.write_text(json.dumps(data, indent=2) + "\n")
                    receipts.append(data)
                    print(json.dumps(data), flush=True)
                assert receipts[1]["pid"] != receipts[2]["pid"]
                assert receipts[3]["pid"] != receipts[4]["pid"]
                if baseline_game_script is not None:
                    baseline = [entry for entry in receipts if entry["mode"].startswith("baseline-")]
                    assert baseline[0]["pid"] != baseline[1]["pid"]
                for prefix in ("opening-mobile-", "replay-mobile-"):
                    mobile = [entry for entry in receipts if entry["mode"].startswith(prefix)]
                    assert mobile[0]["pid"] != mobile[1]["pid"]
                if legacy_sdk is not None:
                    assert receipts[-2]["pid"] != receipts[-1]["pid"]
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
    parser.add_argument("--startup-template", choices=("story", "app"), default="story")
    parser.add_argument("--legacy-renpy-sdk", type=Path, help="Also restore a mobile save written by this original SDK.")
    parser.add_argument("--baseline-game-script", type=Path,
                        help="Also restore a valid quick save produced by this original story script.")
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/native-story-check")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    sdk = args.renpy_sdk
    if sdk is None:
        from prepare import BuildInputs
        sdk = BuildInputs(ROOT / ".android-build").sdk_root("renpy")
    if args.startup_template == "app":
        check_app(sdk.resolve(), args.output.resolve())
        return
    check(sdk.resolve(), args.output.resolve(),
          args.legacy_renpy_sdk.resolve() if args.legacy_renpy_sdk else None,
          args.baseline_game_script.resolve() if args.baseline_game_script else None)


if __name__ == "__main__":
    main()
