"""Compile the independent examples and exercise native saves and gallery flow."""

import argparse
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
EXAMPLES = ("dialogue", "choice", "input", "animation")


def run(sdk, project, command, log_path, env=None, saves=None):
    args = [str(sdk / "renpy.sh"), str(project), command]
    if command == "lint":
        args.append("--error-code")
    if saves is not None:
        args += ["--savedir", str(saves)]
    with log_path.open("w") as log:
        try:
            result = subprocess.run(args, env=env, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=60)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Ren'Py {command} timed out; see {log_path}") from error
    if result.returncode:
        raise RuntimeError(f"Ren'Py {command} failed; see {log_path}")


def verify(sdk, xvfb, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").unlink(missing_ok=True)
    results = {"independent_compiles": []}
    with tempfile.TemporaryDirectory(prefix="project-", dir=output) as folder:
        workspace = Path(folder)
        for name in EXAMPLES:
            project = workspace / name
            (project / "game").mkdir(parents=True)
            shutil.copyfile(HERE / "game" / (name + ".rpy"), project / "game" / (name + ".rpy"))
            run(sdk, project, "compile", output / ("compile-" + name + ".log"))
            results["independent_compiles"].append(name)
            print("Passed: independent " + name + " compile", flush=True)

        project = workspace / "gallery"
        shutil.copytree(HERE / "game", project / "game")
        run(sdk, project, "compile", output / "compile-gallery.log")
        run(sdk, project, "lint", output / "lint.log")
        print("Passed: gallery compile and lint", flush=True)
        shutil.copyfile(HERE / "checks/probe.rpy", project / "game/probe.rpy")
        shutil.copyfile(HERE / "checks/native_driver.py", project / "sdk_examples_check.py")

        read_fd, write_fd = os.pipe()
        try:
            with (output / "xserver.log").open("w") as log:
                server = subprocess.Popen([str(xvfb), "-displayfd", str(write_fd), "-screen",
                                           "0", "720x1280x24", "-ac", "-nolisten", "tcp"],
                                          pass_fds=(write_fd,), stdout=log, stderr=log)
            os.close(write_fd)
            write_fd = None
            try:
                if not select.select([read_fd], [], [], 30)[0]:
                    raise RuntimeError(f"Xvfb startup failed; see {output / 'xserver.log'}")
                display = os.read(read_fd, 64).decode().strip()
                if not display.isdigit():
                    raise RuntimeError(f"Xvfb did not provide a display; see {output / 'xserver.log'}")
                for mode in ("native", "gallery", *("first-" + name for name in EXAMPLES)):
                    artifacts = output / mode
                    artifacts.mkdir(exist_ok=True)
                    receipt = artifacts / "results.json"
                    receipt.unlink(missing_ok=True)
                    env = dict(os.environ, DISPLAY=":" + display, SDL_AUDIODRIVER="dummy",
                               SDK_EXAMPLES_OUTPUT=str(artifacts), SDK_EXAMPLES_MODE=mode)
                    run(sdk, project, "run", artifacts / "native.log", env=env,
                        saves=workspace / (mode + "-saves"))
                    if not receipt.is_file():
                        raise RuntimeError(f"Missing {mode} receipt; see {artifacts / 'native.log'}")
                    results[mode] = json.loads(receipt.read_text())
                    print(f"Passed: {mode} ({len(results[mode]['checks'])} checks)", flush=True)
            finally:
                server.terminate()
                server.wait(timeout=10)
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
    (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
    print("Receipts and captures: " + str(output), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renpy-sdk", type=Path)
    parser.add_argument("--xvfb", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/renpy-examples-check")
    args = parser.parse_args()
    sdk = args.renpy_sdk
    if sdk is None:
        sys.path.insert(0, str(ROOT))
        from prepare import BuildInputs
        sdk = BuildInputs(ROOT / ".android-build").sdk_root("renpy")
    if not (sdk / "renpy.sh").is_file():
        parser.error("Prepare the pinned SDK with 'python3 prepare.py setup renpy', or pass --renpy-sdk.")
    xvfb = args.xvfb or shutil.which("Xvfb") or ROOT / ".android-build/xserver/root/usr/bin/Xvfb"
    if not Path(xvfb).is_file():
        parser.error("Install Xvfb or pass --xvfb /path/to/Xvfb.")
    verify(sdk.resolve(), Path(xvfb).resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
