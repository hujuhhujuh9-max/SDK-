"""Measure real AAR reuse after a build, without producing additional APKs."""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import build_android as build
from prepare import BuildInputs


def check(inputs, build_type="debug"):
    work = inputs.cache / "integration"
    cache = inputs.cache / ("flutter-aar" if build_type == "debug" else "flutter-aar-release")
    manifest = json.loads((cache / "manifest.json").read_text())
    expected = manifest["fingerprint"]
    # Reproduce a new build's clean Flet staging, using the same private cache.
    build.stage_flet(inputs, work)
    commands = []
    run = build.run

    def observed_run(*command, cwd=None):
        commands.append(tuple(str(value) for value in command))
        run(*command, cwd=cwd)

    def phase(name):
        commands.clear()
        started = time.perf_counter()
        repo = build.stage_flutter(inputs, work, build_type=build_type)
        elapsed = time.perf_counter() - started
        if any(command[1:3] == ("build", "aar") for command in commands):
            raise RuntimeError(name + " unexpectedly compiled the Flutter AAR")
        if repo != cache / "repo" or not build.reusable_flutter_repo(cache, expected, build_type=build_type):
            raise RuntimeError(name + " did not reuse the original verified repository")
        return {"phase": name, "seconds": elapsed, "aar_compilations": 0,
                "fingerprint": expected}

    # This ignored-at-the-end module is a real Python-only packaging input.
    # Never overwrite a pre-existing source file or build an APK while it exists.
    probe = ROOT / "runtime/_flutter_cache_acceptance.py"
    if probe.exists():
        raise RuntimeError("Cache acceptance probe source already exists")
    build.run = observed_run
    try:
        results = [phase("unchanged")]
        probe.write_text("CACHE_ACCEPTANCE_ONLY = True\n")
        try:
            results.append(phase("python-only-change"))
        finally:
            probe.unlink()
    finally:
        build.run = run
    receipt = "flutter-cache-reuse.json" if build_type == "debug" else "flutter-cache-reuse-release.json"
    output = inputs.cache / "outputs" / receipt
    output.write_text(json.dumps({"build_type": build_type,
                                  "scope": "real Flutter create/pub/analyze/test with verified AAR reuse",
                                  "phases": results}, indent=2) + "\n")
    print("Passed: Flutter reuse: " + json.dumps(results), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=ROOT / ".android-build")
    parser.add_argument("--build-type", choices=("debug", "release"), default="debug")
    args = parser.parse_args()
    check(BuildInputs(args.cache_dir), args.build_type)


if __name__ == "__main__":
    main()
