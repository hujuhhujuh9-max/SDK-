"""Verify external source boundaries and complete, non-overwriting scaffolds."""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import create_project as scaffold
from project import ROOT, load_project


PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jA9sAAAAASUVORK5CYII=")


class ProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.path = self.root / "renfletpy.json"
        for name in ("game", "app", "assets"):
            (self.root / name).mkdir()
        (self.root / "game/script.rpy").write_text("label start:\n    return\n")
        (self.root / "app/my_app.py").write_text("raise AssertionError('must not import while validating')\n")
        self.config = json.loads((ROOT / "templates/app/renfletpy.json").read_text())
        self.write_config()

    def write_config(self, **changes):
        self.path.write_text(json.dumps(dict(self.config, **changes)), encoding="utf-8")

    def test_frozen_project_contains_resolved_sources_without_importing_app_code(self):
        loaded = load_project(self.path)
        self.assertEqual(loaded.path, self.path.resolve())
        self.assertEqual(loaded.application_id, "com.example.myapp")
        self.assertEqual(loaded.display_name, "My RenFletPy App")
        self.assertEqual(loaded.version_code, 1)
        self.assertEqual(loaded.version_name, "0.1.0")
        self.assertEqual(loaded.startup_template, "app")
        self.assertEqual(loaded.game_dir, self.root / "game")
        self.assertEqual(loaded.python_dir, self.root / "app")
        self.assertEqual(loaded.assets_dir, self.root / "assets")
        self.assertEqual(loaded.app_home, "my_app:app_home_view")
        self.assertIsNone(loaded.icon)
        with self.assertRaises(FrozenInstanceError):
            loaded.display_name = "Changed"

    def test_optional_factory_and_icon_preserve_builtin_and_allow_empty_python_tree(self):
        del self.config["app_home"]
        del self.config["icon"]
        (self.root / "app/my_app.py").unlink()
        self.write_config(startup_template="story")
        loaded = load_project(self.path)
        self.assertIsNone(loaded.app_home)
        self.assertIsNone(loaded.icon)
        self.assertEqual(loaded.startup_template, "story")

    def test_printable_unicode_label_and_android_package_version_are_retained(self):
        self.write_config(application_id="Com.Example_notes2", display_name="Notes & Café 'Stories'",
                          version_code=2100000000, version_name="v2.1.0-preview+4")
        loaded = load_project(self.path)
        self.assertEqual(loaded.application_id, "Com.Example_notes2")
        self.assertEqual(loaded.display_name, "Notes & Café 'Stories'")
        self.assertEqual(loaded.version_code, 2100000000)
        self.assertEqual(loaded.version_name, "v2.1.0-preview+4")

    def test_invalid_identity_version_and_mode_fail_before_building(self):
        fields = {
            "application_id": [None, True, "onlyone", "com.2notes", "com..notes", "com.notes-1",
                               "com.notes\ncommand", "com." + "a" * 151, "公司.notes"],
            "display_name": [None, "", " ", " padded", "padded ", "x" * 81, "two\nlines", "\ud800"],
            "version_code": [None, True, False, "1", 1.0, 0, -1, 2100000001],
            "version_name": [None, "", "1 2", "'quoted'", "1\n2", "x" * 51, "版本1"],
            "startup_template": [None, True, "", "other", {}],
        }
        for field, values in fields.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    self.write_config(**{field: value})
                    with self.assertRaisesRegex(ValueError, field):
                        load_project(self.path)

    def test_unknown_missing_duplicate_and_malformed_config_are_rejected(self):
        self.write_config(extra="unexpected")
        with self.assertRaisesRegex(ValueError, "Unknown.*extra"):
            load_project(self.path)
        self.path.write_text(json.dumps({key: value for key, value in self.config.items()
                                        if key != "game_dir"}))
        with self.assertRaisesRegex(ValueError, "Missing.*game_dir"):
            load_project(self.path)
        source = json.dumps(self.config)[:-1] + ', "version_code": 2}'
        self.path.write_text(source)
        with self.assertRaisesRegex(ValueError, "Duplicate.*version_code"):
            load_project(self.path)
        for content in (b"not json", b"[]", b"null", b"\xff"):
            with self.subTest(content=content):
                self.path.write_bytes(content)
                with self.assertRaises(ValueError):
                    load_project(self.path)

    def test_config_itself_must_be_a_regular_file(self):
        link = self.root / "linked.json"
        link.symlink_to(self.path)
        for path in (link, self.root, self.root / "missing.json"):
            with self.subTest(path=path):
                with self.assertRaisesRegex(ValueError, "regular JSON file"):
                    load_project(path)

    def test_paths_cannot_escape_select_outputs_or_use_missing_and_non_directory_sources(self):
        (self.root / "file").write_text("not a directory")
        (self.root / "cache").mkdir()
        values = [None, 1, "", ".", "../outside", str(self.root / "game"), "missing",
                  "file", "game\\..\\app", "game\0", "cache"]
        for field in ("game_dir", "python_dir", "assets_dir"):
            for value in values:
                with self.subTest(field=field, value=value):
                    self.write_config(**{field: value})
                    with self.assertRaisesRegex(ValueError, field):
                        load_project(self.path)

    def test_source_roots_cannot_overlap(self):
        (self.root / "game/nested").mkdir()
        for changes in ({"python_dir": "game"}, {"assets_dir": "app"},
                        {"python_dir": "game/nested"}):
            with self.subTest(changes=changes):
                self.write_config(**changes)
                with self.assertRaisesRegex(ValueError, "overlap"):
                    load_project(self.path)

    def test_source_paths_and_nested_entries_cannot_be_symlinks(self):
        (self.root / "linked").symlink_to(self.root / "game", target_is_directory=True)
        self.write_config(game_dir="linked")
        with self.assertRaisesRegex(ValueError, "symlink"):
            load_project(self.path)
        self.write_config()
        child = self.root / "assets/linked.svg"
        for target in (self.root / "game/script.rpy", self.root / "missing"):
            with self.subTest(target=target):
                child.symlink_to(target)
                with self.assertRaisesRegex(ValueError, "links"):
                    load_project(self.path)
                child.unlink()

    def test_source_trees_reject_fifo_and_unsafe_filenames(self):
        fifo = self.root / "assets/channel"
        os.mkfifo(fifo)
        with self.assertRaisesRegex(ValueError, "special/unsafe"):
            load_project(self.path)
        fifo.unlink()
        for name in ("unsafe\nname", "back\\slash"):
            with self.subTest(name=name):
                file = self.root / "assets" / name
                file.write_text("source")
                with self.assertRaisesRegex(ValueError, "special/unsafe"):
                    load_project(self.path)
                file.unlink()

    def test_generated_compiled_native_and_installed_dependency_entries_are_rejected(self):
        for name in ("old.pyc", "old.rpyc", "bundle.rpa", "native.so", "installer.apk",
                     "library.aar", "library.jar", "escape.pth", "__pycache__", "saves",
                     "build", ".git", "dependency.dist-info"):
            with self.subTest(name=name):
                file = self.root / "assets" / name
                file.write_text("generated")
                with self.assertRaisesRegex(ValueError, "generated or native output"):
                    load_project(self.path)
                file.unlink()

    def test_project_python_cannot_shadow_sdk_bootstrap_runtime_or_package_names(self):
        for name in ("main.py", "sdk_bridge.py", "app_home.py", "project_config.py", "json.py",
                     "httpx.py", "flet_spinkit", "renpy", "lib", "flet_extensions.json",
                     "PROJECT-NOTICE.txt"):
            with self.subTest(name=name):
                file = self.root / "app" / name
                if "." not in name:
                    file.mkdir()
                    (file / "__init__.py").write_text("# package\n")
                else:
                    file.write_text("# source\n")
                with self.assertRaisesRegex(ValueError, "shadow SDK"):
                    load_project(self.path)
                if file.is_dir():
                    shutil.rmtree(file)
                else:
                    file.unlink()

    def test_namespaced_application_packages_and_data_remain_supported(self):
        package = self.root / "app/notes_app"
        package.mkdir()
        (package / "__init__.py").write_text("# package\n")
        (package / "json.py").write_text("VALUE = 1\n")
        (package / "schema.json").write_text('{"version": 1}\n')
        self.assertEqual(load_project(self.path).python_dir, self.root / "app")

    def test_game_python_cannot_shadow_sdk_or_duplicate_app_module_and_package_names(self):
        for name, message in (("sdk_bridge.py", "shadow SDK"), ("my_app.py", "Ambiguous")):
            with self.subTest(name=name):
                file = self.root / "game" / name
                file.write_text("# source\n")
                with self.assertRaisesRegex(ValueError, message):
                    load_project(self.path)
                file.unlink()
        (self.root / "app/notes").mkdir()
        (self.root / "app/notes/__init__.py").write_text("# package\n")
        (self.root / "game/notes.py").write_text("# source\n")
        with self.assertRaisesRegex(ValueError, "Ambiguous.*notes"):
            load_project(self.path)

    def test_factory_needs_simple_python_identifiers_and_existing_top_level_module(self):
        for value in (True, "", "my_app", "package.my_app:home", "my_app:home.attr",
                      "my-app:home", "missing:home", "class:home", "my_app:lambda"):
            with self.subTest(value=value):
                self.write_config(app_home=value)
                with self.assertRaisesRegex(ValueError, "app_home"):
                    load_project(self.path)

    def test_game_needs_native_source_and_reserves_generated_identity_filename(self):
        (self.root / "game/script.rpy").unlink()
        with self.assertRaisesRegex(ValueError, "native .rpy source"):
            load_project(self.path)
        (self.root / "game/_renfletpy_project.rpy").write_text("# source\n")
        with self.assertRaisesRegex(ValueError, "reserved"):
            load_project(self.path)

    def test_icon_is_an_existing_in_project_png_and_reserves_generated_asset(self):
        (self.root / "branding").mkdir()
        icon = self.root / "branding/icon.png"
        icon.write_bytes(PNG)
        self.write_config(icon="branding/icon.png")
        self.assertEqual(load_project(self.path).icon, icon)
        (self.root / "assets/_renfletpy_project_icon.png").write_bytes(PNG)
        with self.assertRaisesRegex(ValueError, "reserved"):
            load_project(self.path)

    def test_invalid_icons_reject_text_wrong_extension_dimensions_links_and_escape(self):
        icon = self.root / "icon.png"
        for content in (b"not an image", PNG[:32], PNG[:16] + b"\0" * 8 + PNG[24:]):
            with self.subTest(content=content[:32]):
                icon.write_bytes(content)
                self.write_config(icon="icon.png")
                with self.assertRaisesRegex(ValueError, "icon"):
                    load_project(self.path)
        icon.write_bytes(PNG)
        (self.root / "icon.jpg").write_bytes(PNG)
        (self.root / "link.png").symlink_to(icon)
        for value in ("missing.png", "icon.jpg", "link.png", "../icon.png", str(icon)):
            with self.subTest(value=value):
                self.write_config(icon=value)
                with self.assertRaisesRegex(ValueError, "icon"):
                    load_project(self.path)


class CreateProjectTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "sdk"
        self.source.mkdir()
        for name in ("game", "assets", "templates/app"):
            shutil.copytree(ROOT / name, self.source / name)
        self.destination = self.root / "new app"

    def create(self, **options):
        return scaffold.create_project(self.destination, source_root=self.source, **options)

    def test_scaffold_copies_proven_sources_and_only_small_application_template(self):
        unused = self.source / "templates/app/runtime"
        unused.mkdir()
        (unused / "sdk_bridge.py").write_text("# SDK runtime must not be duplicated\n")
        loaded = self.create(application_id="com.example.notes", display_name="Notes & Stories",
                             version_code=3, version_name="2.0.0")
        self.assertEqual(loaded.path, self.destination / "renfletpy.json")
        self.assertEqual(loaded.application_id, "com.example.notes")
        self.assertEqual(loaded.display_name, "Notes & Stories")
        self.assertEqual(loaded.version_code, 3)
        self.assertEqual(loaded.version_name, "2.0.0")
        self.assertEqual({path.name for path in self.destination.iterdir()},
                         {"renfletpy.json", "app", "game", "assets"})
        for name in ("game", "assets"):
            for file in (self.source / name).rglob("*"):
                if file.is_file():
                    self.assertEqual((self.destination / name / file.relative_to(self.source / name))
                                     .read_bytes(), file.read_bytes())
        self.assertEqual((loaded.python_dir / "my_app.py").read_bytes(),
                         (self.source / "templates/app/app/my_app.py").read_bytes())
        self.assertEqual([path for path in self.root.glob(".renfletpy-project-*")], [])

    def test_scaffold_drops_old_compiled_files_saves_and_build_caches(self):
        for folder in ("game/__pycache__", "game/saves", "game/cache", "assets/build"):
            directory = self.source / folder
            directory.mkdir()
            (directory / "old.dat").write_text("old state")
        for name in ("game/old.rpyc", "game/old.pyc", "assets/old.apk"):
            (self.source / name).write_text("old output")
        self.create()
        self.assertFalse(any(path.name == "old.dat" for path in self.destination.rglob("*")))
        self.assertFalse(any(path.suffix in (".rpyc", ".pyc", ".apk")
                             for path in self.destination.rglob("*")))
        self.assertTrue((self.destination / "game/script.rpy").is_file())

    def test_existing_file_directory_and_broken_link_are_never_overwritten(self):
        for kind in ("file", "directory", "broken link"):
            with self.subTest(kind=kind):
                if kind == "file":
                    self.destination.write_text("keep me")
                elif kind == "directory":
                    self.destination.mkdir()
                else:
                    self.destination.symlink_to(self.root / "missing")
                inode = self.destination.lstat().st_ino
                with self.assertRaises(FileExistsError):
                    self.create()
                self.assertEqual(self.destination.lstat().st_ino, inode)
                if self.destination.is_dir():
                    self.destination.rmdir()
                else:
                    self.destination.unlink()

    def test_failed_validation_leaves_no_destination_or_temporary_clutter(self):
        original = (self.source / "templates/app/renfletpy.json").read_bytes()
        with self.assertRaisesRegex(ValueError, "application_id"):
            self.create(application_id="invalid")
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob(".renfletpy-project-*")), [])
        self.assertEqual((self.source / "templates/app/renfletpy.json").read_bytes(), original)

    def test_source_links_cannot_copy_or_modify_outside_files(self):
        outside = self.root / "outside.svg"
        outside.write_text("keep me")
        (self.source / "assets/link.svg").symlink_to(outside)
        with self.assertRaisesRegex(ValueError, "links"):
            self.create()
        self.assertEqual(outside.read_text(), "keep me")
        self.assertFalse(self.destination.exists())
        self.assertEqual(list(self.root.glob(".renfletpy-project-*")), [])

    def test_symlinked_template_config_cannot_write_through_to_sdk_or_external_file(self):
        original = self.source / "templates/app/renfletpy.json"
        outside = self.root / "outside.json"
        outside.write_bytes(original.read_bytes())
        original.unlink()
        original.symlink_to(outside)
        prior = outside.read_bytes()
        with self.assertRaisesRegex(ValueError, "regular JSON file"):
            self.create()
        self.assertEqual(outside.read_bytes(), prior)
        self.assertFalse(self.destination.exists())

    def test_atomic_publication_refuses_a_concurrently_created_empty_directory(self):
        publish = scaffold._publish
        inodes = []

        def concurrently_create(stage, destination):
            self.assertFalse(destination.exists())
            self.assertTrue((stage / "app/my_app.py").is_file())
            self.assertEqual(load_project(stage / "renfletpy.json").startup_template, "app")
            destination.mkdir()
            inodes.append(destination.stat().st_ino)
            publish(stage, destination)

        with patch.object(scaffold, "_publish", side_effect=concurrently_create):
            with self.assertRaises(FileExistsError):
                self.create()
        self.assertEqual(self.destination.stat().st_ino, inodes[0])
        self.assertEqual(list(self.destination.iterdir()), [])
        self.assertEqual(list(self.root.glob(".renfletpy-project-*")), [])

    def test_destination_inside_sample_tree_is_rejected_before_copying(self):
        for name in ("game", "assets", "templates/app"):
            with self.subTest(name=name):
                destination = self.source / name / "new-project"
                with self.assertRaisesRegex(ValueError, "inside a copied sample tree"):
                    scaffold.create_project(destination, source_root=self.source)
                self.assertFalse(destination.exists())

    def test_cli_aliases_produce_a_valid_project_without_building_the_sdk(self):
        result = subprocess.run([sys.executable, str(ROOT / "create_project.py"), str(self.destination),
                                 "--source-root", str(self.source), "--package", "org.renfletpy.example",
                                 "--name", "RenFletPy Example"], capture_output=True, text=True,
                                env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"))
        self.assertEqual(result.returncode, 0, result.stderr)
        loaded = load_project(self.destination / "renfletpy.json")
        self.assertEqual(loaded.application_id, "org.renfletpy.example")
        self.assertEqual(loaded.display_name, "RenFletPy Example")
        self.assertIn("Created project:", result.stdout)
        self.assertIn("--project '", result.stdout)


if __name__ == "__main__":
    unittest.main()
