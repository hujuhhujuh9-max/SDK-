"""Require the optional app starter's checks against the pinned Flet source."""

import argparse
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flet-root", type=Path)
    parser.add_argument("--output", type=Path,
                        default=ROOT / ".android-build/app-starter-check.json")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    if args.flet_root is None:
        from build_android import stage_flet
        from prepare import BuildInputs

        inputs = BuildInputs(ROOT / ".android-build")
        inputs.setup("flet")
        work = inputs.cache / "app-starter-inspection"
        work.mkdir(parents=True, exist_ok=True)
        flet = stage_flet(inputs, work)
    else:
        flet = args.flet_root.resolve()
    source = flet / "sdk/python/packages/flet/src"
    if not (source / "flet/__init__.py").is_file():
        raise RuntimeError("Prepared Flet Python source is missing")
    sys.path.insert(0, str(source))
    __import__("flet")
    suite = unittest.TestSuite()
    for pattern in ("test_app_session.py", "test_app_story.py", "test_app_home_flet.py",
                    "test_app_starter_protocol.py", "test_app_starter_integration.py",
                    "test_app_confirmation_protocol.py"):
        cases = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern=pattern)
        if not cases.countTestCases():
            raise RuntimeError("Missing required app-starter checks: " + pattern)
        suite.addTests(cases)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not result.testsRun:
        raise RuntimeError("App-starter checks must pass without skips")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({
        "scope": "real pinned-Flet controls, protocol and app-story handoff",
        "tests": result.testsRun, "skips": len(result.skipped),
        "flet_source": str(source), "success": True,
    }, indent=2) + "\n")
    print(f"Passed: {result.testsRun} app-starter checks with prepared Flet", flush=True)


if __name__ == "__main__":
    main()
