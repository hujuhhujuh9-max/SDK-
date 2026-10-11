#!/usr/bin/env python3
"""Materialize the cross-boundary example through supported project APIs."""

import argparse
import json
import shutil
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))


def create(destination, *, source_root=ROOT, application_id="org.renfletpy.capabilities"):
    from create_project import _publish, create_project
    from project import generated_entry, load_project

    source_root, destination = Path(source_root).resolve(), Path(destination).absolute()
    examples = source_root / "examples"
    if destination.exists() or destination.is_symlink():
        raise FileExistsError("Capabilities project already exists: " + str(destination))
    destination.parent.mkdir(parents=True, exist_ok=True)

    def omit_generated(directory, names):
        return [name for name in names if generated_entry(name)]

    with tempfile.TemporaryDirectory(prefix=".sdk-capabilities-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "project"
        create_project(stage, source_root=source_root, application_id=application_id,
                       display_name="Project Capabilities")
        for source, target in (
            (HERE / "capabilities_app.py", "capabilities_app.py"),
            (HERE / "app/capabilities_observer.py", "capabilities_observer.py"),
            (examples / "project_app/my_app.py", "notebook_app.py"),
            (examples / "flutter_component/app/my_app.py", "pulse_app.py"),
            (examples / "2d/scale_setup.py", "scale_setup.py"),
        ):
            shutil.copyfile(source, stage / "app" / target)
        shutil.copyfile(examples / "2d/game/scale_native.rpy", stage / "game/scale_native.rpy")
        shutil.copyfile(HERE / "game/capabilities_probe.rpy", stage / "game/capabilities_probe.rpy")
        shutil.copytree(examples / "rive/assets", stage / "assets", dirs_exist_ok=True)
        shutil.copytree(examples / "flutter_component/components", stage / "components",
                        ignore=omit_generated)
        config_path = stage / "renfletpy.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        config.update(
            app_home="capabilities_app:app_home_view", project_setup="capabilities_app:register",
            extensions=[json.loads((examples / "flutter_component/extension.json").read_text(encoding="utf-8"))],
        )
        config_path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        load_project(config_path)
        _publish(stage, destination)
    return load_project(destination / "renfletpy.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--application-id", default="org.renfletpy.capabilities")
    args = parser.parse_args()
    try:
        project = create(args.destination, application_id=args.application_id)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(project.path)


if __name__ == "__main__":
    main()
