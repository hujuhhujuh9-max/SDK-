"""Verify project activity saves through the real pinned native Ren'Py runtime."""

import argparse
import hashlib
import json
import os
import select
import shutil
import subprocess
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def stage(project, mode, support):
    game = project / "game"
    game.mkdir(parents=True)
    for source in (ROOT / "runtime").glob("*.py"):
        shutil.copyfile(source, project / source.name)
    # A parallel worker may run before the coordinator's two runtime modules
    # have been integrated. They are read-only inputs, never modified here.
    for name in ("project_api.py", "app_navigation.py"):
        if not (project / name).is_file():
            shutil.copyfile(support / "runtime" / name, project / name)
    (project / "project_config.py").write_text(
        'STARTUP_TEMPLATE = "story"\nAPP_HOME = None\nPROJECT_SETUP = "survey_activity:register"\n')
    for source in (ROOT / "game").glob("*.py"):
        shutil.copyfile(source, game / source.name)
    for source in (ROOT / "game").glob("*.rpy"):
        content = source.read_text()
        if source.name == "script.rpy":
            content = content.replace("label start:\n", "label sdk_default_start:\n", 1)
        (game / source.name).write_text(content)
    shutil.copyfile(HERE / "checks/host.rpy", game / "activity_host.rpy")
    shutil.copyfile(HERE / "checks/native_driver.py", project / "activity_native_driver.py")
    shutil.copyfile(HERE / ("checks/legacy_survey.py" if mode == "legacy-seed" else "survey_activity.py"),
                    project / "survey_activity.py")


def verify(sdk, xvfb, output, support):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").unlink(missing_ok=True)
    receipts = []
    with tempfile.TemporaryDirectory(prefix="activities-", dir=output) as folder:
        workspace = Path(folder)
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
                    raise RuntimeError("Activity Xvfb startup failed; see xserver.log")
                display = os.read(read_fd, 64).decode().strip()
                if not display.isdigit():
                    raise RuntimeError("Activity Xvfb did not provide a display")
                for mode in ("warm", "seed", "reopen", "legacy-seed", "migrate"):
                    project = workspace / (mode + "-project")
                    stage(project, mode, support)
                    receipt = output / (mode + ".json")
                    receipt.unlink(missing_ok=True)
                    saves = workspace / ("warm-saves" if mode == "warm" else
                                         "legacy-saves" if mode in ("legacy-seed", "migrate") else "current-saves")
                    env = dict(os.environ, DISPLAY=":" + display, SDL_AUDIODRIVER="dummy",
                               ACTIVITY_CHECK_MODE=mode, ACTIVITY_CHECK_RECEIPT=str(receipt))
                    with (output / (mode + ".log")).open("w") as log:
                        result = subprocess.run([str(sdk / "renpy.sh"), str(project), "run", "--savedir", str(saves)],
                                                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
                    if result.returncode or not receipt.is_file():
                        raise RuntimeError(f"Native activity {mode} failed; see {output / (mode + '.log')}")
                    data = json.loads(receipt.read_text())
                    data["independent_compilation"] = True
                    receipt.write_text(json.dumps(data, indent=2) + "\n")
                    receipts.append(data)
                    print(f"Passed: native activity {mode} ({len(data['checks'])} checks)", flush=True)
                assert len({receipt["pid"] for receipt in receipts}) == len(receipts)
                assert receipts[1]["half_state"] == receipts[2]["half_state"]
                assert receipts[3]["schema"] == 1 and receipts[4]["schema"] == 2
            finally:
                server.terminate()
                server.wait(timeout=10)
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)
    inputs = [ROOT / "runtime/renfletpy.py", ROOT / "runtime/story_activities.py",
              ROOT / "game/script.rpy", HERE / "survey_activity.py",
              support / "runtime/project_api.py", support / "runtime/app_navigation.py"]
    summary = {"success": True, "platform": "native Linux / pinned modified Ren'Py", "receipts": receipts,
               "input_hashes": {str(path.relative_to(ROOT) if path.is_relative_to(ROOT) else path):
                                hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
               "unverified": ["fresh integrated APK", "Android lifecycle", "physical API 35 phone"]}
    (output / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renpy-sdk", type=Path, required=True)
    parser.add_argument("--xvfb", type=Path, default=shutil.which("Xvfb"))
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/story-activities-check")
    parser.add_argument("--support-root", type=Path, default=ROOT,
                        help="Read coordinator runtime modules here before parallel integration")
    args = parser.parse_args()
    if not (args.renpy_sdk / "renpy.sh").is_file() or args.xvfb is None or not args.xvfb.is_file():
        parser.error("Provide the prepared pinned Ren'Py SDK and an installed Xvfb executable")
    verify(args.renpy_sdk.resolve(), args.xvfb.resolve(), args.output.resolve(), args.support_root.resolve())


if __name__ == "__main__":
    main()
