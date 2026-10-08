"""Verify the optional callable story, isolated saves and native mobile recovery.

This runs the pinned Ren'Py engine on Linux, including its Android background
save API and the profile's actual Android path-selection branch. It does not
claim Android device validation. Every project, save directory and writable SDK
copy belongs to a temporary workspace below --output.
"""

import argparse
import hashlib
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
PROFILE = "sdk-native-lantern-v1"
SLOT = "sdk-native-lantern-checkpoint"


def save_hashes(directory):
    return {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted(directory.glob("*.save"))}


def slot_file(directory, slot):
    matches = list(directory.glob(slot + "-*.save"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one native archive for {slot} in {directory}, found {len(matches)}")
    return matches[0]


def copy_metadata(source, destination, identity):
    """Change only JSON; preserve the native log and its original signature."""
    with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination, "w") as modified:
        for member in original.infolist():
            data = original.read(member.filename)
            if member.filename == "json":
                if identity == "corrupt":
                    data = b"{this is not JSON"
                else:
                    metadata = json.loads(data)
                    if identity is None:
                        metadata.pop("sdk_native_story", None)
                    else:
                        metadata["sdk_native_story"] = identity
                    data = json.dumps(metadata).encode("utf-8")
            modified.writestr(member, data)


def stage_project(workspace, name, recipe, demo=False, android_profile=False):
    project = workspace / name
    game = project / "game"
    game.mkdir(parents=True)
    shutil.copyfile(recipe / "story.rpy", game / "story.rpy")
    if demo:
        shutil.copyfile(ROOT / "game/script.rpy", game / "script.rpy")
        for source in (ROOT / "game").glob("*.py"):
            shutil.copyfile(source, game / source.name)
        for source in (ROOT / "runtime").glob("*.py"):
            shutil.copyfile(source, project / source.name)
    else:
        # The probe installs callbacks with recovery enabled before this
        # unchanged host's idempotent init-time installation.
        shutil.copyfile(recipe / "host.rpy", game / "zz-host.rpy")
        profile = (recipe / "profile.rpy").read_text()
        if android_profile:
            # Exercise the real early profile source with Android's flag only
            # during path selection. The engine and SDL remain Linux-native.
            profile = '''python early:
    import os
    _sdk_lifecycle_original_android = renpy.android
    _sdk_lifecycle_original_private = os.environ.get("ANDROID_PRIVATE")
    renpy.android = True
    os.environ["ANDROID_PRIVATE"] = os.environ["SDK_NATIVE_LIFECYCLE_PRIVATE"]
''' + profile + '''
python early:
    _sdk_lifecycle_android_savedir = renpy.config.savedir
    renpy.android = _sdk_lifecycle_original_android
    if _sdk_lifecycle_original_private is None:
        os.environ.pop("ANDROID_PRIVATE", None)
    else:
        os.environ["ANDROID_PRIVATE"] = _sdk_lifecycle_original_private
'''
        (game / "profile.rpy").write_text(profile)
    shutil.copyfile(ROOT / "scripts/native_lifecycle_probe.rpy", game / "probe.rpy")
    shutil.copyfile(ROOT / "scripts/native_lifecycle_driver.py", project / "native_lifecycle_check.py")
    return project


def run_process(sdk, project, saves, mode, output, env, override=None):
    receipt = output / (mode + ".json")
    receipt.unlink(missing_ok=True)
    launch_env = dict(env, SDK_NATIVE_LIFECYCLE_MODE=mode,
                      SDK_NATIVE_LIFECYCLE_RECEIPT=str(receipt))
    launch_env.pop("RENPY_AUTO_LOAD", None)
    if override is not None:
        launch_env["RENPY_AUTO_LOAD"] = override
    log_path = output / (mode + ".log")
    with log_path.open("w") as log:
        try:
            result = subprocess.run([str(sdk / "renpy.sh"), str(project), "run", "--savedir", str(saves)],
                                    env=launch_env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Native {mode} timed out; see {log_path}") from error
    if result.returncode or not receipt.is_file():
        raise RuntimeError(f"Native {mode} failed; see {log_path}")
    data = json.loads(receipt.read_text())
    if data.get("mode") != mode or not data.get("checks"):
        raise RuntimeError(f"Native {mode} wrote an invalid receipt: {receipt}")
    print(f"Passed: {mode} ({len(data['checks'])} checks, PID {data['pid']})", flush=True)
    return data


def run_source_check(sdk, project, saves, command, log_path, env):
    args = [str(sdk / "renpy.sh"), str(project), command]
    if command == "lint":
        args.append("--error-code")
    args += ["--savedir", str(saves)]
    with log_path.open("w") as log:
        try:
            result = subprocess.run(args, env=env, stdout=log, stderr=subprocess.STDOUT, timeout=60)
        except subprocess.TimeoutExpired as error:
            raise RuntimeError(f"Native {command} timed out; see {log_path}") from error
    # The pinned SDK can report an init exception and still exit compile with
    # status zero. A successful source gate requires exception-free output too.
    report = log_path.read_text()
    if (result.returncode or "Full traceback:" in report or "Traceback (most recent call last)" in report
            or (project / "traceback.txt").is_file()):
        raise RuntimeError(f"Native {command} failed; see {log_path}")


def check(sdk, xvfb, output, recipe=None):
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").unlink(missing_ok=True)
    recipe = recipe or ROOT / "examples/renpy/lifecycle/game"
    with tempfile.TemporaryDirectory(prefix="project-", dir=output) as folder:
        workspace = Path(folder)
        # SDK tools compile their common scripts and may update caches.
        # Never make the caller's prepared installation a shared writable input.
        engine = workspace / "sdk"
        shutil.copytree(sdk, engine, symlinks=True)
        source_env = dict(os.environ, RENPY_PATH_TO_SAVES=str(workspace / "engine-saves"))
        source_env.pop("RENPY_AUTO_LOAD", None)
        library = workspace / "library-source"
        (library / "game").mkdir(parents=True)
        shutil.copyfile(recipe / "story.rpy", library / "game/story.rpy")
        standalone = workspace / "standalone-source"
        shutil.copytree(recipe, standalone / "game")
        run_source_check(engine, library, workspace / "library-source-saves", "compile",
                         output / "compile-library.log", source_env)
        run_source_check(engine, standalone, workspace / "standalone-source-saves", "compile",
                         output / "compile-standalone.log", source_env)
        run_source_check(engine, standalone, workspace / "standalone-source-saves", "lint",
                         output / "lint-standalone.log", source_env)
        source_checks = ["library compile", "standalone compile", "standalone lint"]
        print("Passed: library compile, standalone compile and lint", flush=True)
        private = workspace / "android-private"
        demo_saves = private / "saves"
        optional_saves = demo_saves / PROFILE
        demo_saves.mkdir(parents=True)
        records = private / "application-records.json"
        records.write_text('{"revision": 1}\n')
        demo = stage_project(workspace, "demo", recipe, demo=True)
        optional = stage_project(workspace, "optional", recipe)
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
                    raise RuntimeError("Xvfb startup failed; see xserver.log")
                display = os.read(read_fd, 64).decode().strip()
                if not display.isdigit():
                    raise RuntimeError("Xvfb did not provide a display; see xserver.log")
                env = dict(os.environ, DISPLAY=":" + display, SDL_AUDIODRIVER="dummy",
                           RENPY_PATH_TO_SAVES=str(workspace / "engine-saves"),
                           SDK_NATIVE_LIFECYCLE_PRIVATE=str(private),
                           SDK_NATIVE_LIFECYCLE_RECORDS=str(records))
                receipts = []

                def run(project, saves, mode, override=None):
                    result = run_process(engine, project, saves, mode, output, env, override)
                    receipts.append(result)
                    return result

                run(demo, demo_saves, "demo-seed")
                baseline = save_hashes(demo_saves)
                quick = slot_file(demo_saves, "renfletpy-quick")
                reload = slot_file(demo_saves, "_reload-1")
                assert len(baseline) == 2, baseline
                run(optional, optional_saves, "lifecycle")
                assert save_hashes(demo_saves) == baseline, "Optional lifecycle changed demo archives"

                for status in ("active", "returned", "completed"):
                    seed = run(optional, optional_saves, status + "-seed")
                    checkpoint = slot_file(optional_saves, SLOT)
                    checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
                    recovery = run(optional, optional_saves, status + "-recover")
                    assert seed["pid"] != recovery["pid"], "Recovery did not use a fresh process"
                    assert seed["state"]["run_id"] == recovery["recovered_state"]["run_id"]
                    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == checkpoint_hash
                    assert not list(optional_saves.glob("_reload-1-*.save")), "Owned recovery was not consumed"
                    assert save_hashes(demo_saves) == baseline, "Optional recovery changed demo archives"

                run(optional, optional_saves, "checkpoint-override", override=SLOT)
                checkpoint_hash = hashlib.sha256(slot_file(optional_saves, SLOT).read_bytes()).hexdigest()
                run(optional, optional_saves, "autosave")
                assert hashlib.sha256(slot_file(optional_saves, SLOT).read_bytes()).hexdigest() == checkpoint_hash
                assert save_hashes(demo_saves) == baseline, "Optional worker autosave changed demo archives"
                android = stage_project(workspace, "android-profile", recipe, android_profile=True)
                run(android, optional_saves, "android-profile")
                assert save_hashes(demo_saves) == baseline, "Android profile selection changed demo archives"

                identity = {"profile": PROFILE, "story_id": "lantern", "schema": 1}
                guard_cases = {"foreign": None, "corrupt": "corrupt",
                               "schema": dict(identity, schema=999),
                               "bool-schema": dict(identity, schema=True)}
                for name, metadata in guard_cases.items():
                    project = stage_project(workspace, "guard-" + name, recipe)
                    saves = demo_saves / (PROFILE + "-guard-" + name)
                    saves.mkdir()
                    copy_metadata(quick, saves / (SLOT + "-LT1.save"), metadata)
                    copy_metadata(reload, saves / "_reload-1-LT1.save", metadata)
                    guard_before = save_hashes(saves)
                    run(project, saves, "guard-" + name)
                    assert save_hashes(saves) == guard_before, "Rejected saves were modified"
                    run(project, saves, "override-reject-" + name, override=SLOT)
                    assert save_hashes(saves) == guard_before, "Rejected override changed saves"
                    assert save_hashes(demo_saves) == baseline, "Guard check changed demo archives"

                run(demo, demo_saves, "demo-recover")
                assert hashlib.sha256(quick.read_bytes()).hexdigest() == baseline[quick.name]
                results = {"scope": "Native Linux engine and Android profile path; no Android device run",
                           "demo_save_hashes": baseline, "receipts": receipts,
                           "source_checks": source_checks,
                           "checks": sum(len(item["checks"]) for item in receipts)}
                (output / "results.json").write_text(json.dumps(results, indent=2) + "\n")
                return results
            finally:
                server.terminate()
                server.wait(timeout=10)
        finally:
            os.close(read_fd)
            if write_fd is not None:
                os.close(write_fd)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--renpy-sdk", type=Path)
    parser.add_argument("--xvfb", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/native-lifecycle-check")
    args = parser.parse_args()
    sdk = args.renpy_sdk
    if sdk is None:
        sys.path.insert(0, str(ROOT))
        from prepare import BuildInputs
        sdk = BuildInputs(ROOT / ".android-build").sdk_root("renpy")
    if not (sdk / "renpy.sh").is_file():
        parser.error("Prepare Ren'Py with 'python3 prepare.py setup renpy', or pass --renpy-sdk.")
    xvfb = args.xvfb or shutil.which("Xvfb") or ROOT / ".android-build/xserver/root/usr/bin/Xvfb"
    if not Path(xvfb).is_file():
        parser.error("Install Xvfb or pass --xvfb /path/to/Xvfb.")
    result = check(sdk.resolve(), Path(xvfb).resolve(), args.output.resolve())
    print(f"Passed {result['checks']} native checks; receipts: {args.output}", flush=True)


if __name__ == "__main__":
    main()
