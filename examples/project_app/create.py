"""Materialize an external multipage app using the normal project scaffold."""

import argparse
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from create_project import create_project


def create(destination):
    project = create_project(destination, application_id="com.example.notebook",
                             display_name="Notebook and Stories")
    shutil.copyfile(Path(__file__).with_name("my_app.py"), project.python_dir / "my_app.py")
    config = json.loads(project.path.read_text())
    config["project_setup"] = "my_app:register"
    project.path.write_text(json.dumps(config, indent=2) + "\n")
    return project.path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(create(args.destination))
