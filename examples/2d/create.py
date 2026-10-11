#!/usr/bin/env python3
"""Create the opt-in 2D project from the existing SDK template, atomically."""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))


def create(destination, *, source_root=ROOT, application_id="com.example.lab2d"):
    from create_project import _publish, create_project
    from project import load_project

    destination, source_root = Path(destination).absolute(), Path(source_root).resolve()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("2D project destination already exists: " + str(destination))
    rive_assets = source_root / "examples/rive/assets"
    required = ("rive/tree_loading_bar.riv", "rive/events_test.riv")
    if not all((rive_assets / name).is_file() for name in required):
        raise FileNotFoundError("Integrate the Rive example fixtures before creating the 2D project")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".sdk-2d-project-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "project"
        create_project(stage, application_id=application_id, display_name="2D Lab",
                       source_root=source_root)
        shutil.copyfile(HERE / "scale_setup.py", stage / "app/scale_setup.py")
        shutil.copyfile(HERE / "game/scale_native.rpy", stage / "game/scale_native.rpy")
        shutil.copytree(rive_assets, stage / "assets", dirs_exist_ok=True)
        config = json.loads((stage / "renfletpy.json").read_text(encoding="utf-8"))
        config.update(app_home="scale_setup:app_home_view", project_setup="scale_setup:register_scale")
        (stage / "renfletpy.json").write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        load_project(stage / "renfletpy.json")
        _publish(stage, destination)
    return load_project(destination / "renfletpy.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--application-id", default="com.example.lab2d")
    args = parser.parse_args()
    try:
        project = create(args.destination, source_root=args.source_root, application_id=args.application_id)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print("Created 2D project: " + str(project.path))


if __name__ == "__main__":
    main()
