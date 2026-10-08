"""Exercise the optional native host with a supplied confirmed A bridge runtime.

Uses the real modified Ren'Py Linux engine and its mobile-save API, not an
Android device or the C route UI. SDK writes, projects and saves are isolated.
The bridge is copied unchanged; its source hash is recorded with the receipts.
"""

import argparse
import ast
import hashlib
import json
import os
import select
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from .check_native_lifecycle import (PROFILE, ROOT, SLOT, run_process,
                                        run_source_check, save_hashes, slot_file,
                                        stage_project as stage_demo)
except ImportError:
    from check_native_lifecycle import (PROFILE, ROOT, SLOT, run_process,
                                       run_source_check, save_hashes, slot_file,
                                       stage_project as stage_demo)

REQUIRED_APIS = (
    "request_story", "take_story_command", "confirm_story_command", "finish_story",
    "restore_story_status", "story_status", "presentation", "set_presentation",
    "request_save", "take_save_request", "save_status", "update_save_status",
    "request_reading", "take_reading_request", "reading_status",
    "initialize_reading", "update_reading_status", "quitting", "stop",
)
RECIPE_FILES = {"game/story.rpy": "game/story.rpy", "game/profile.rpy": "game/profile.rpy",
                "app/host.rpy": "game/zz-host.rpy", "app/native_story_mailbox.py": "native_story_mailbox.py"}


def recipe_hashes(project):
    return {name: hashlib.sha256((project / relative).read_bytes()).hexdigest()
            for name, relative in RECIPE_FILES.items()}


def validate_runtime(runtime):
    """Check the source contract without importing a host-only bridge into Python."""
    bridge = runtime / "sdk_bridge.py"
    if not bridge.is_file() or not (runtime / "renfletpy.py").is_file():
        raise ValueError("--bridge-runtime must contain sdk_bridge.py and renfletpy.py from A")
    tree = ast.parse(bridge.read_text(), filename=str(bridge))
    names = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = sorted(set(REQUIRED_APIS) - names)
    if missing:
        raise ValueError("Bridge lacks the confirmed A runtime API: " + ", ".join(missing))
    return hashlib.sha256(bridge.read_bytes()).hexdigest()


def stage_project(workspace, name, recipe, runtime, probe=True):
    project = workspace / name
    game = project / "game"
    game.mkdir(parents=True)
    for name in ("story.rpy", "profile.rpy"):
        shutil.copyfile(recipe / "game" / name, game / name)
    # Probe init 1 must enable recovery before this host's idempotent installer.
    shutil.copyfile(recipe / "app/host.rpy", game / "zz-host.rpy")
    shutil.copyfile(recipe / "app/native_story_mailbox.py", project / "native_story_mailbox.py")
    for source in runtime.glob("*.py"):
        shutil.copyfile(source, project / source.name)
    if probe:
        shutil.copyfile(ROOT / "scripts/native_story_mailbox_probe.rpy", game / "probe.rpy")
        shutil.copyfile(ROOT / "scripts/native_story_mailbox_driver.py", project / "native_story_mailbox_check.py")
    return project


def check(sdk, xvfb, output, runtime, recipe=None):
    bridge_hash = validate_runtime(runtime)
    recipe = recipe or ROOT / "examples/renpy/lifecycle"
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix="project-", dir=output) as folder:
        workspace = Path(folder)
        engine = workspace / "sdk"
        shutil.copytree(sdk, engine, symlinks=True)
        source_env = dict(os.environ, RENPY_PATH_TO_SAVES=str(workspace / "engine-saves"))
        source_env.pop("RENPY_AUTO_LOAD", None)
        source = stage_project(workspace, "source", recipe, runtime, probe=False)
        source_hashes = recipe_hashes(source)
        for command in ("compile", "lint"):
            run_source_check(engine, source, workspace / "source-saves", command,
                             output / (command + "-mailbox.log"), source_env)
        print("Passed: actual A native host compile and lint", flush=True)
        private = workspace / "private"
        demo_saves = private / "saves"
        optional_saves = demo_saves / PROFILE
        demo_saves.mkdir(parents=True)
        records = private / "application-records.json"
        records.write_text('{"revision": 1}\n')
        demo = stage_demo(workspace, "demo", recipe / "game", demo=True)
        optional = stage_project(workspace, "optional", recipe, runtime)
        if recipe_hashes(optional) != source_hashes:
            raise RuntimeError("Recipe changed during staging; rerun against stable source")
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
                           SDK_NATIVE_LIFECYCLE_RECORDS=str(records),
                           SDK_NATIVE_MAILBOX_BRIDGE_SHA256=bridge_hash)
                receipts = []

                def run(project, saves, mode):
                    result = run_process(engine, project, saves, mode, output, env)
                    if project == optional and result.get("bridge_sha256") != bridge_hash:
                        raise RuntimeError("Native receipt did not identify the supplied bridge")
                    if project == optional and result.get("recipe_sha256") != source_hashes:
                        raise RuntimeError("Native receipt did not identify the compiled recipe")
                    receipts.append(result)
                    return result

                run(demo, demo_saves, "demo-seed")
                baseline = save_hashes(demo_saves)
                quick = slot_file(demo_saves, "renfletpy-quick")
                slot_file(demo_saves, "_reload-1")
                assert len(baseline) == 2, baseline
                run(optional, optional_saves, "mailbox-lifecycle")
                assert save_hashes(demo_saves) == baseline, "Mailbox lifecycle changed demo archives"
                for status in ("active", "returned", "completed"):
                    seed = run(optional, optional_saves, "mailbox-" + status + "-seed")
                    checkpoint = slot_file(optional_saves, SLOT)
                    checkpoint_hash = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
                    recovered = run(optional, optional_saves, "mailbox-" + status + "-recover")
                    assert seed["pid"] != recovered["pid"], "Recovery did not use a fresh process"
                    assert seed["state"] == recovered["recovered_state"], "Recovery changed saved native truth"
                    assert hashlib.sha256(checkpoint.read_bytes()).hexdigest() == checkpoint_hash
                    assert not list(optional_saves.glob("_reload-1-*.save")), "Recovery was not consumed"
                    assert save_hashes(demo_saves) == baseline, "Mailbox recovery changed demo archives"
                run(demo, demo_saves, "demo-recover")
                assert hashlib.sha256(quick.read_bytes()).hexdigest() == baseline[quick.name]
                results = {"scope": "Actual A runtime and native Linux engine; no Android device or C route UI",
                           "bridge_sha256": bridge_hash, "bridge_runtime": str(runtime),
                           "recipe_sha256": source_hashes,
                           "source_checks": ["actual A native host compile", "actual A native host lint"],
                           "demo_save_hashes": baseline, "receipts": receipts,
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
    parser.add_argument("--bridge-runtime", type=Path, required=True,
                        help="Directory containing the actual confirmed A runtime Python files")
    parser.add_argument("--renpy-sdk", type=Path)
    parser.add_argument("--xvfb", type=Path)
    parser.add_argument("--recipe-root", type=Path, default=ROOT / "examples/renpy/lifecycle",
                        help="Callable story recipe containing game/ and app/ (default: repository example)")
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/native-story-mailbox-check")
    args = parser.parse_args()
    try:
        validate_runtime(args.bridge_runtime)
    except (ValueError, SyntaxError) as error:
        parser.error(str(error))
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
    result = check(sdk.resolve(), Path(xvfb).resolve(), args.output.resolve(),
                   args.bridge_runtime.resolve(), args.recipe_root.resolve())
    print(f"Passed {result['checks']} native mailbox checks; receipts: {args.output}", flush=True)


if __name__ == "__main__":
    main()
