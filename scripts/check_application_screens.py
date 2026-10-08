"""Run C's real application screen interactions against pinned, patched Flet."""

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flet-root", type=Path, help="Reuse already prepared, patched Flet source")
    parser.add_argument("--with-mailbox", action="store_true",
                        help="Also test A's real mailbox in an integrated A/C checkout")
    args = parser.parse_args()
    sys.path.insert(0, str(ROOT))
    if args.flet_root is None:
        from build_android import stage_flet
        from prepare import BuildInputs

        inputs = BuildInputs(ROOT / ".android-build")
        inputs.setup("flet")
        work = inputs.cache / "application-screens-inspection"
        work.mkdir(parents=True, exist_ok=True)
        flet = stage_flet(inputs, work)
    else:
        flet = args.flet_root.resolve()
    source = flet / "sdk/python/packages/flet/src"
    if not (source / "flet/__init__.py").is_file():
        raise RuntimeError("Prepared Flet Python source is missing")
    sys.path.insert(0, str(source))
    __import__("flet")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_application_screens*.py")
    if args.with_mailbox:
        from runtime import sdk_bridge

        required = ("story_status", "request_story", "take_story_command", "confirm_story_command",
                    "restore_story_status", "finish_story")
        if not all(callable(getattr(sdk_bridge, name, None)) for name in required):
            raise RuntimeError("--with-mailbox requires A's published story bridge in this checkout")
        suite.addTests(unittest.defaultTestLoader.discover(
            str(ROOT / "tests"), pattern="application_screen_mailbox_cases.py"))
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not result.testsRun:
        raise RuntimeError("Application screen checks must pass without skips")
    print(f"Passed: {result.testsRun} application screen checks with prepared Flet", flush=True)


if __name__ == "__main__":
    main()
