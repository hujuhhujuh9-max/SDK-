"""Verify Rive activity save/restore with pinned native Ren'Py and a Dart event receipt."""

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
    for source in (support / "runtime").glob("*.py"):
        shutil.copyfile(source, project / source.name)
    for name in ("rive_activity.py", "rive_control.py"):
        shutil.copyfile(ROOT / "runtime" / name, project / name)
    (project / "project_config.py").write_text(
        'STARTUP_TEMPLATE = "story"\nAPP_HOME = None\nPROJECT_SETUP = "rive_project:setup"\n')
    for source in (support / "game").glob("*.py"):
        shutil.copyfile(source, game / source.name)
    for source in (support / "game").glob("*.rpy"):
        content = source.read_text()
        if source.name == "script.rpy":
            content = content.replace("label start:\n", "label sdk_default_start:\n", 1)
        (game / source.name).write_text(content)
    shutil.copyfile(HERE / "checks/host.rpy", game / "rive_host.rpy")
    shutil.copyfile(HERE / "checks/native_driver.py", project / "rive_native_driver.py")
    shutil.copyfile(HERE / ("checks/legacy_rive.py" if mode == "legacy-seed" else "app/rive_project.py"),
                    project / "rive_project.py")


def verify(sdk, xvfb, event, output, support):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").unlink(missing_ok=True)
    payload = json.loads(event.read_text())
    if payload.get("name") != "SomeGeneralEvent" or payload.get("type") != "general":
        raise ValueError("Pass build/rive-evidence/event.json emitted by the actual Flutter native trigger test")
    shutil.copyfile(event, output / "event.json")
    event = (output / "event.json").resolve()
    receipts = []
    with tempfile.TemporaryDirectory(prefix="rive-", dir=output) as folder:
        workspace = Path(folder)
        read_fd, write_fd = os.pipe()
        try:
            with (output / "xserver.log").open("w") as log:
                server = subprocess.Popen([str(xvfb), "-displayfd", str(write_fd), "-screen", "0",
                                           "720x1280x24", "-ac", "-nolisten", "tcp"],
                                          pass_fds=(write_fd,), stdout=log, stderr=log)
            os.close(write_fd)
            write_fd = None
            try:
                if not select.select([read_fd], [], [], 30)[0]:
                    raise RuntimeError("Rive Xvfb startup failed; see xserver.log")
                display = os.read(read_fd, 64).decode().strip()
                if not display.isdigit():
                    raise RuntimeError("Rive Xvfb did not provide a display")
                for mode in ("warm", "seed", "reopen", "legacy-seed", "migrate"):
                    project = workspace / (mode + "-project")
                    stage(project, mode, support)
                    receipt = output / (mode + ".json")
                    receipt.unlink(missing_ok=True)
                    saves = workspace / ("warm-saves" if mode == "warm" else
                                         "legacy-saves" if mode in ("legacy-seed", "migrate") else "current-saves")
                    env = dict(os.environ, DISPLAY=":" + display, SDL_AUDIODRIVER="dummy",
                               RIVE_CHECK_MODE=mode, RIVE_CHECK_EVENT=str(event), RIVE_CHECK_RECEIPT=str(receipt))
                    with (output / (mode + ".log")).open("w") as log:
                        result = subprocess.run([str(sdk / "renpy.sh"), str(project), "run", "--savedir", str(saves)],
                                                env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
                    if result.returncode or not receipt.is_file():
                        raise RuntimeError(f"Native Rive {mode} failed; see {output / (mode + '.log')}")
                    data = json.loads(receipt.read_text())
                    data["independent_compilation"] = True
                    receipt.write_text(json.dumps(data, indent=2) + "\n")
                    receipts.append(data)
                    print(f"Passed: native Rive {mode} ({len(data['checks'])} checks)", flush=True)
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
    inputs = [support / "runtime" / name for name in
              ("renfletpy.py", "story_activities.py", "sdk_bridge.py", "project_api.py", "app_navigation.py")]
    inputs += [support / "game/script.rpy", ROOT / "runtime/rive_activity.py", HERE / "app/rive_project.py"]
    summary = {"success": True, "platform": "native Linux / pinned modified Ren'Py", "receipts": receipts,
               "event_sha256": hashlib.sha256(event.read_bytes()).hexdigest(),
               "input_hashes": {str(path): hashlib.sha256(path.read_bytes()).hexdigest() for path in inputs},
               "unverified": ["embedded Flutter with native story in Android", "Android GPU renderer/lifecycle",
                              "physical API 35 phone performance"]}
    (output / "results.json").write_text(json.dumps(summary, indent=2) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renpy-sdk", type=Path, required=True)
    parser.add_argument("--xvfb", type=Path, default=shutil.which("Xvfb"))
    parser.add_argument("--event-json", type=Path, required=True,
                        help="Actual build/rive-evidence/event.json generated by the Flutter trigger test")
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/rive-native-check")
    parser.add_argument("--support-root", type=Path, default=ROOT,
                        help="Integrated activity/navigation/native runtime, read-only before parallel integration")
    args = parser.parse_args()
    if not (args.renpy_sdk / "renpy.sh").is_file() or args.xvfb is None or not args.xvfb.is_file():
        parser.error("Provide the prepared pinned Ren'Py SDK and an installed Xvfb executable")
    if not args.event_json.is_file():
        parser.error("Run the Flutter native trigger test to produce --event-json first")
    verify(args.renpy_sdk.resolve(), args.xvfb.resolve(), args.event_json.resolve(),
           args.output.resolve(), args.support_root.resolve())


if __name__ == "__main__":
    main()
