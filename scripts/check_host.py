"""Run the complete acceptance host suite with pinned Flet and no skips."""

import argparse
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flet-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / ".android-build/runtime-check/host-tests.json")
    args = parser.parse_args()
    # Remove old successful evidence even if preparation or discovery fails.
    args.output.unlink(missing_ok=True)
    source = args.flet_root.resolve() / "sdk/python/packages/flet/src"
    if not (source / "flet/__init__.py").is_file():
        raise RuntimeError("Acceptance requires the prepared pinned Flet source")
    sys.path[:0] = [str(source), str(ROOT)]
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    passed = result.wasSuccessful() and result.testsRun > 0 and not result.skipped
    receipt = {"source_sha": subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "status": "passed" if passed else "failed", "tests_run": result.testsRun,
        "skipped": len(result.skipped), "failures": len(result.failures), "errors": len(result.errors)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    if not passed:
        raise RuntimeError("Acceptance host checks must all run and pass without skips")


if __name__ == "__main__":
    main()
