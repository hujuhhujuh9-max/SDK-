"""Exercise pinned Flet and the optional native app story in one interpreter.

Preference service replies are simulated. Native scenes, commands, saves, loads,
process recovery and Flet control/event encoding use the pinned SDKs on Linux.
This check does not claim Android packaging or device acceptance.
"""

import argparse
import json
import os
import select
import shutil
import subprocess
import sysconfig
import tempfile
import zipfile
from pathlib import Path

if __package__:
    from .check_native_lifecycle import run_process, run_source_check, slot_file
else:
    from check_native_lifecycle import run_process, run_source_check, slot_file

ROOT = Path(__file__).resolve().parents[1]


def foreign_host_save(source, destination, schema):
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, "w") as modified:
        for member in original.infolist():
            data = original.read(member.filename)
            if member.filename == "json":
                metadata = json.loads(data)
                if schema is None:
                    metadata.pop("sdk_app_host", None)
                else:
                    metadata["sdk_app_host"] = schema
                data = json.dumps(metadata).encode()
            modified.writestr(member, data)


def stage_project(workspace):
    project = workspace / "project"
    game = project / "game"
    game.mkdir(parents=True)
    recipe = ROOT / "examples/renpy/lifecycle/game"
    shutil.copyfile(recipe / "story.rpy", game / "story.rpy")
    for source in (ROOT / "examples/app/game").glob("*.rpy"):
        shutil.copyfile(source, game / source.name)
    shutil.copyfile(ROOT / "scripts/native_app_bridge_probe.rpy", game / "zz-probe.rpy")
    for source in (ROOT / "runtime").glob("*.py"):
        shutil.copyfile(source, project / source.name)
    shutil.copyfile(ROOT / "scripts/native_app_bridge_driver.py", project / "native_app_bridge_check.py")
    shutil.copyfile(ROOT / "scripts/native_app_ui.py", project / "native_app_ui.py")
    return project


def check(sdk, flet, xvfb, output):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="project-", dir=output) as folder:
        workspace = Path(folder)
        engine = workspace / "sdk"
        shutil.copytree(sdk, engine, symlinks=True)
        project = stage_project(workspace)
        env = dict(os.environ, SDL_AUDIODRIVER="dummy", MSGPACK_PUREPYTHON="1",
                   RENPY_PATH_TO_SAVES=str(workspace / "engine-saves"))
        env.pop("RENPY_AUTO_LOAD", None)
        # Ren'Py supplies its interpreter; expose the prepared Flet dependency
        # set, not a second Python executable or an embedded renderer.
        env["SDK_NATIVE_APP_PYTHON_PATH"] = os.pathsep.join([str(flet / "sdk/python/packages/flet/src"),
                                            sysconfig.get_path("purelib")])
        run_source_check(engine, project, workspace / "source-saves", "compile", output / "compile.log", env)
        run_source_check(engine, project, workspace / "source-saves", "lint", output / "lint.log", env)
        read_fd, write_fd = os.pipe()
        server = None
        try:
            with (output / "xserver.log").open("w") as log:
                server = subprocess.Popen([str(xvfb), "-displayfd", str(write_fd), "-screen", "0",
                                           "720x1280x24", "-ac", "-nolisten", "tcp"],
                                          pass_fds=(write_fd,), stdout=log, stderr=log)
            os.close(write_fd)
            write_fd = None
            if not select.select([read_fd], [], [], 30)[0]:
                raise RuntimeError("Xvfb startup failed; see xserver.log")
            display = os.read(read_fd, 64).decode().strip()
            if not display.isdigit():
                raise RuntimeError("Xvfb did not provide a display")
            env["DISPLAY"] = ":" + display
            receipts = []
            for mode in ("app-lifecycle", "app-active-seed", "app-active-recover",
                         "app-returned-seed", "app-returned-recover", "app-completed-seed", "app-completed-recover"):
                saves = workspace / ("saves-lifecycle" if mode == "app-lifecycle" else "saves-" + mode.split("-")[1])
                receipts.append(run_process(engine, project, saves, mode, output, env))
            checkpoint = slot_file(workspace / "saves-lifecycle", "sdk-native-lantern-checkpoint")
            for name, schema in (("missing", None), ("newer", 999), ("boolean", True)):
                saves = workspace / ("saves-foreign-" + name)
                saves.mkdir()
                foreign_host_save(checkpoint, saves / checkpoint.name, schema)
                foreign_host_save(checkpoint, saves / "_reload-1-LT1.save", schema)
                receipts.append(run_process(engine, project, saves, "app-foreign-" + name, output, env))
            assert all(item["native_thread"] != item["flet_thread"] for item in receipts)
            result = {"scope": __doc__, "source_checks": ["compile", "lint"], "receipts": receipts,
                      "checks": sum(len(item["checks"]) for item in receipts)}
            (output / "results.json").write_text(json.dumps(result, indent=2) + "\n")
            return result
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
            if server is not None:
                server.terminate()
                server.wait(timeout=10)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renpy-sdk", type=Path)
    parser.add_argument("--flet-sdk", type=Path)
    parser.add_argument("--xvfb", type=Path, default=shutil.which("Xvfb"))
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/native-app-bridge-check")
    args = parser.parse_args()
    if args.renpy_sdk is None or args.flet_sdk is None:
        import sys
        sys.path.insert(0, str(ROOT))
        from prepare import BuildInputs
        from build_android import stage_flet
        inputs = BuildInputs(ROOT / ".android-build")
        if args.renpy_sdk is None:
            args.renpy_sdk = inputs.setup("renpy")
        if args.flet_sdk is None:
            inputs.setup("flet")
            work = inputs.cache / "native-app-inspection"
            work.mkdir(parents=True, exist_ok=True)
            args.flet_sdk = stage_flet(inputs, work)
    if not (args.renpy_sdk / "renpy.sh").is_file():
        parser.error("Pass the prepared, pinned Ren'Py SDK")
    if not (args.flet_sdk / "sdk/python/packages/flet/src/flet").is_dir():
        parser.error("Pass the prepared, pinned Flet source")
    if args.xvfb is None or not args.xvfb.is_file():
        parser.error("Install Xvfb or pass --xvfb")
    result = check(args.renpy_sdk.resolve(), args.flet_sdk.resolve(), args.xvfb.resolve(), args.output.resolve())
    print(f"Passed {result['checks']} native app bridge checks; receipts: {args.output}", flush=True)


if __name__ == "__main__":
    main()
