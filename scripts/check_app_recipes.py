"""Require the app-control recipes' checks against the pinned Flet sources."""

import argparse
import hashlib
import importlib
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXTENSIONS = ("flet-code-editor", "flet-datatable2", "flet-color-pickers", "flet-spinkit")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--flet-root", type=Path,
                        help="Reuse an already prepared, patched Flet source directory")
    parser.add_argument("--output", type=Path,
                        default=ROOT / ".android-build/app-recipes-check.json")
    args = parser.parse_args()
    args.output.unlink(missing_ok=True)
    sys.path.insert(0, str(ROOT))
    if args.flet_root is None:
        from build_android import stage_flet
        from prepare import BuildInputs

        inputs = BuildInputs(ROOT / ".android-build")
        inputs.setup("flet")
        work = inputs.cache / "app-recipes-inspection"
        work.mkdir(parents=True, exist_ok=True)
        flet = stage_flet(inputs, work)
    else:
        flet = args.flet_root.resolve()
    packages = flet / "sdk/python/packages"
    modules = ("flet", *EXTENSIONS)
    for name in modules:
        source = packages / name / "src"
        if not (source / name.replace("-", "_") / "__init__.py").is_file():
            raise RuntimeError("Prepared Flet Python source is missing: " + name)
        sys.path.insert(0, str(source))
    # Import the actual dependencies before discovery: missing extension sources
    # cannot turn the required protocol cases into a successful skipped suite.
    for name in modules:
        importlib.import_module(name.replace("-", "_"))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"),
                                               pattern="test_app_recipes_flet.py")
    if not suite.countTestCases():
        raise RuntimeError("Missing required app-control recipe checks")
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or not result.testsRun:
        raise RuntimeError("App-control recipe checks must pass without skips")
    inputs = ("runtime/app_recipes.py", "tests/test_app_recipes_flet.py",
              "scripts/check_app_recipes.py", "sdk-lock.json")
    receipt = {
        "scope": "real pinned-Flet editor, table, picker and loading protocol",
        "source_sha": subprocess.check_output(["git", "rev-parse", "HEAD"],
                                               cwd=ROOT, text=True).strip(),
        "source_dirty": bool(subprocess.check_output(["git", "status", "--porcelain"],
                                                      cwd=ROOT, text=True).strip()),
        "inputs_sha256": {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                          for name in inputs},
        "tests": result.testsRun, "skips": len(result.skipped), "success": True,
        "flet_sources": {name: str(packages / name / "src") for name in modules},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(f"Passed: {result.testsRun} app-control recipe checks with prepared Flet", flush=True)


if __name__ == "__main__":
    main()
