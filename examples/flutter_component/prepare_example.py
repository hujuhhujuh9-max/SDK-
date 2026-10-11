#!/usr/bin/env python3
"""Create a standalone example project without modifying the SDK sample."""

import argparse
import json
import shutil
import sys
from pathlib import Path


EXAMPLE = Path(__file__).resolve().parent
SDK = EXAMPLE.parents[1]
sys.path.insert(0, str(SDK))

from create_project import create_project
from project import generated_entry, load_project


def materialize(destination, *, sdk_root=SDK):
    project = create_project(destination, application_id="org.renfletpy.projectpulse",
                             display_name="Project Pulse", source_root=sdk_root)
    destination = project.path.parent

    def omit_generated(directory, names):
        return [name for name in names if generated_entry(name)]

    shutil.copytree(EXAMPLE / "components", destination / "components", ignore=omit_generated)
    shutil.copyfile(EXAMPLE / "app/my_app.py", destination / "app/my_app.py")
    config = json.loads(project.path.read_text())
    config.update(project_setup="my_app:register",
                  extensions=[json.loads((EXAMPLE / "extension.json").read_text())])
    project.path.write_text(json.dumps(config, indent=2) + "\n")
    return load_project(project.path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    try:
        project = materialize(args.destination)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(project.path)


if __name__ == "__main__":
    main()
