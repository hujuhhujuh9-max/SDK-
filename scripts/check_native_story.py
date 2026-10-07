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
                                       "1080x1920x24", "-ac", "-nolisten", "tcp"],
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
                    shutil.copyfile(ROOT / "scripts/native_story_driver.py", project / "native_story_check.py")
                    (game / "probe.rpy").write_text('''init 1 python:
    import native_story_check
    config.overlay_screens.append("native_story_check")
    config.default_fullscreen = True
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
