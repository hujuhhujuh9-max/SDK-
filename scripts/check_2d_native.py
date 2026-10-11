#!/usr/bin/env python3
"""Compile/lint/render/save/reopen the optional native 2D workload on Linux."""

import argparse
import json
import os
import select
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HOST = '''
define config.name = "Native 2D workload probe"
define config.main_menu = False
define config.screen_width = 720
define config.screen_height = 1280
define config.default_text_cps = 0
define config.check_conflicting_properties = True
define mira = Character("Mira")
default sdk_scale_probe_stage = "motion"
init 1 python:
    import scale_native_driver
    config.exception_handler = scale_native_driver.fail_exception
    config.overlay_screens.append("sdk_scale_probe_overlay")
screen sdk_scale_probe_overlay():
    timer 0.1 repeat True action Function(scale_native_driver.tick, _update_screens=False)
label renfletpy_activity(kind):
    return
label start:
    if scale_native_driver.mode == "reopen":
        $ renpy.load("scale-halfway")
    $ renpy.checkpoint()
    call screen sdk_scale_native_stage
    if _return != {"tier": "nominal", "outcome": "continued"}:
        $ raise AssertionError("Native continuation result changed")
    $ sdk_scale_probe_stage = "plain"
    call screen sdk_scale_native_stage(animated=False, shaders=False)
    $ sdk_scale_probe_stage = "shader"
    call screen sdk_scale_native_stage(animated=False, shaders=True)
    return
'''


def run(sdk, project, mode, log, env=None, savedir=None):
    command = [str(sdk / "renpy.sh"), str(project), mode]
    if mode == "lint":
        command.append("--error-code")
    if savedir:
        command.extend(["--savedir", str(savedir)])
    with log.open("w") as stream:
        result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, env=env, timeout=60)
    if result.returncode:
        raise RuntimeError("Native 2D " + mode + " failed; see " + str(log))


def verify(sdk, xvfb, output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="native-project-", dir=output) as temporary:
        project = Path(temporary)
        (project / "game").mkdir()
        shutil.copyfile(ROOT / "examples/2d/game/scale_native.rpy", project / "game/scale_native.rpy")
        (project / "game/host.rpy").write_text(HOST)
        for name in ("scale_native.py", "scale_workloads.py"):
            shutil.copyfile(ROOT / "runtime" / name, project / name)
        shutil.copyfile(ROOT / "scripts/scale_native_driver.py", project / "scale_native_driver.py")
        lint_env = dict(os.environ, SDK_2D_NATIVE_OUTPUT=str(output), SDK_2D_NATIVE_MODE="lint")
        run(sdk, project, "compile", output / "compile.log", env=lint_env)
        run(sdk, project, "lint", output / "lint.log", env=lint_env)
        read_fd, write_fd = os.pipe()
        with (output / "xserver.log").open("w") as stream:
            server = subprocess.Popen([str(xvfb), "-displayfd", str(write_fd), "-screen", "0",
                                       "720x1280x24", "-ac", "-nolisten", "tcp"],
                                      pass_fds=(write_fd,), stdout=stream, stderr=stream)
        os.close(write_fd)
        try:
            if not select.select([read_fd], [], [], 20)[0]:
                raise RuntimeError("Xvfb did not provide a display")
            number = os.read(read_fd, 64).decode().strip()
            if not number.isdigit():
                raise RuntimeError("Xvfb did not provide a numeric display")
            receipts = []
            for mode in ("initial", "reopen"):
                folder = output / mode
                folder.mkdir(exist_ok=True)
                (folder / "receipt.json").unlink(missing_ok=True)
                env = dict(os.environ, DISPLAY=":" + number, SDL_AUDIODRIVER="dummy",
                           SDK_2D_NATIVE_OUTPUT=str(folder), SDK_2D_NATIVE_MODE=mode)
                run(sdk, project, "run", folder / "native.log", env=env, savedir=project / "saves")
                receipt = folder / "receipt.json"
                if not receipt.is_file():
                    raise RuntimeError("Missing native " + mode + " receipt")
                receipts.append(json.loads(receipt.read_text()))
            result = {"scope": "host_native_functionality", "receipts": receipts,
                      "phone_performance": "unverified"}
            (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
            print(json.dumps(result, indent=2))
        finally:
            os.close(read_fd)
            server.terminate()
            server.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renpy-sdk", type=Path, required=True)
    parser.add_argument("--xvfb", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/2d-native")
    args = parser.parse_args()
    verify(args.renpy_sdk.resolve(), args.xvfb.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
