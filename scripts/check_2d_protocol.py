#!/usr/bin/env python3
"""Run the 2D model/lifecycle/protocol tests with real pinned Flet, rejecting skips."""

import argparse
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flet-root", type=Path, required=True)
    args = parser.parse_args()
    source = args.flet_root.resolve() / "sdk/python/packages/flet/src"
    if not (source / "flet/__init__.py").is_file():
        parser.error("Prepared pinned Flet source is missing")
    sys.path[:0] = [str(source), str(ROOT)]
    __import__("flet")
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_scale*.py")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if result.skipped or not result.testsRun or not result.wasSuccessful():
        raise RuntimeError("Prepared 2D workload tests must pass without skips")
    print(f"Passed: {result.testsRun} prepared-Flet 2D workload checks")


if __name__ == "__main__":
    main()
