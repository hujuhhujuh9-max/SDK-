#!/usr/bin/env python3
"""Create an editable application project from the working SDK sample."""

import argparse
import ctypes
import errno
import json
import os
import shlex
import shutil
import tempfile
from pathlib import Path

from project import ROOT, generated_entry, load_project


def _publish(stage, destination):
    """Linux atomic rename without replacing a concurrently created path."""
    libc = ctypes.CDLL(None, use_errno=True)
    rename = libc.renameat2
    rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    rename.restype = ctypes.c_int
    if rename(-100, os.fsencode(stage), -100, os.fsencode(destination), 1):
        number = ctypes.get_errno()
        raise OSError(number, os.strerror(number), str(destination))


def create_project(destination, *, application_id="com.example.myapp",
                   display_name="My RenFletPy App", version_code=1, version_name="0.1.0",
                   source_root=None):
    """Copy only game, assets and the small app template; refuse existing paths."""
    source = ROOT if source_root is None else Path(source_root).resolve()
    destination = Path(destination).absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(errno.EEXIST, "Project destination already exists", str(destination))
    for sample in (source / "game", source / "assets", source / "templates/app"):
        if destination.resolve().is_relative_to(sample.resolve()):
            raise ValueError("Project destination cannot be inside a copied sample tree.")
        if sample.is_symlink() or not sample.is_dir():
            raise ValueError("Missing regular SDK sample tree: " + str(sample))
    template = source / "templates/app"
    template_config = template / "renfletpy.json"
    if template_config.is_symlink() or not template_config.is_file():
        raise ValueError("App template config must be a regular JSON file.")
    template_python = template / "app"
    if template_python.is_symlink() or not template_python.is_dir():
        raise ValueError("App template Python must be a regular source directory.")
    config = json.loads(template_config.read_text(encoding="utf-8"))
    if not isinstance(config, dict):
        raise ValueError("App template config must be an object.")
    config.update(application_id=application_id, display_name=display_name,
                  version_code=version_code, version_name=version_name)
    destination.parent.mkdir(parents=True, exist_ok=True)

    def omit_generated(directory, names):
        return [name for name in names if generated_entry(name)]

    with tempfile.TemporaryDirectory(prefix=".renfletpy-project-", dir=destination.parent) as temporary:
        stage = Path(temporary) / "project"
        stage.mkdir()
        shutil.copytree(template_python, stage / "app", symlinks=True, ignore=omit_generated)
        shutil.copytree(source / "game", stage / "game", symlinks=True, ignore=omit_generated)
        shutil.copytree(source / "assets", stage / "assets", symlinks=True, ignore=omit_generated)
        (stage / "renfletpy.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n",
                                             encoding="utf-8")
        load_project(stage / "renfletpy.json")
        _publish(stage, destination)
    return load_project(destination / "renfletpy.json")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="New project directory; must not already exist.")
    parser.add_argument("--application-id", "--package", default="com.example.myapp")
    parser.add_argument("--display-name", "--name", default="My RenFletPy App")
    parser.add_argument("--version-code", type=int, default=1)
    parser.add_argument("--version-name", default="0.1.0")
    parser.add_argument("--source-root", type=Path,
                        help="Copy the game, assets and app template from this SDK checkout.")
    args = parser.parse_args()
    try:
        project = create_project(args.destination, application_id=args.application_id,
                                 display_name=args.display_name, version_code=args.version_code,
                                 version_name=args.version_name, source_root=args.source_root)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print("Created project: " + str(project.path))
    print("Build: python3 build_android.py --project " + shlex.quote(str(project.path)))


if __name__ == "__main__":
    main()
