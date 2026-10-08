"""Compile, lint and exercise optional native examples in an isolated project."""
import argparse
import json
import os
import select
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renpy-sdk", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    root = ROOT
    output = (args.output or root / ".android-build/d-native-example-check").resolve()
    output.mkdir(parents=True, exist_ok=True)
    project = output / "project"
    if project.exists():
        shutil.rmtree(project)
    game = project / "game"
    game.mkdir(parents=True, exist_ok=True)
    for name in ("probe.rpy", "probe.rpyc"):
        (game / name).unlink(missing_ok=True)
    (output / "receipt.json").unlink(missing_ok=True)
    sdk = args.renpy_sdk
    if sdk is None:
        sys.path.insert(0, str(root))
        from prepare import BuildInputs
        sdk = BuildInputs(root / ".android-build").sdk_root("renpy")
    sdk = sdk.resolve()
    for name in ("dialogue", "choice", "input", "animation", "gallery"):
        shutil.copyfile(root / "examples/renpy/game" / (name + ".rpy"), game / (name + ".rpy"))
    for mode in ("compile", "lint"):
        with (output / (mode + ".log")).open("w") as log:
            result = subprocess.run([str(sdk / "renpy.sh"), str(project), mode], stdout=log, stderr=subprocess.STDOUT, timeout=60)
        if result.returncode:
            raise RuntimeError(mode + " failed; see " + str(output / (mode + ".log")))
    source_root = Path(__file__).resolve().parent
    shutil.copyfile(source_root / "native_examples_driver.py", project / "sdk_examples_probe_driver.py")
    shutil.copyfile(source_root / "native_examples_probe.rpy", game / "probe.rpy")
    binary = shutil.which("Xvfb") or str(root / ".android-build/xserver/root/usr/bin/Xvfb")
    if not Path(binary).is_file():
        raise RuntimeError("Install Xvfb to exercise the optional native examples")
    saves = output / "saves"
    if saves.exists():
        shutil.rmtree(saves)
    read_fd, write_fd = os.pipe()
    with (output / "xserver.log").open("w") as server_log:
        server = subprocess.Popen([binary, "-displayfd", str(write_fd), "-screen", "0", "1080x1920x24", "-ac", "-nolisten", "tcp"], pass_fds=(write_fd,), stdout=server_log, stderr=server_log)
        os.close(write_fd)
        try:
            if not select.select([read_fd], [], [], 30)[0]:
                raise RuntimeError("Xvfb did not provide a display")
            display = ":" + os.read(read_fd, 64).decode().strip()
            env = dict(os.environ, DISPLAY=display, SDL_AUDIODRIVER="dummy", SDK_EXAMPLES_PROBE_OUTPUT=str(output))
            with (output / "probe.log").open("w") as log:
                result = subprocess.run([str(sdk / "renpy.sh"), str(project), "run", "--savedir", str(saves)], env=env, stdout=log, stderr=subprocess.STDOUT, timeout=90)
            receipt = output / "receipt.json"
            if result.returncode or not receipt.is_file():
                raise RuntimeError("Native examples probe failed; see " + str(output / "probe.log"))
            print(json.dumps(json.loads(receipt.read_text())), flush=True)
        finally:
            os.close(read_fd)
            server.terminate()
            server.wait(timeout=10)


if __name__ == "__main__":
    main()
