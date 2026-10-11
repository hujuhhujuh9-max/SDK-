"""Exercise selected paired packages, source boundaries, cache identity and removal."""

import contextlib
import importlib.util
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import build_android as build
from project import ROOT, load_project
from project_extensions import extension_inventory, stage_project_flutter
from scripts.check_apk_source import apk_inputs_changed
import test_flutter_cache as cache_fixtures


EXAMPLE = ROOT / "examples/flutter_component"
spec = importlib.util.spec_from_file_location("pulse_example", EXAMPLE / "prepare_example.py")
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


class ProjectExtensionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.project = example.materialize(self.root / "project")
        self.config = json.loads(self.project.path.read_text())
        self.extension = self.project.extensions[0]

    def load(self):
        self.project.path.write_text(json.dumps(self.config))
        return load_project(self.project.path)

    def test_selects_both_halves_and_setup_without_executing_project_code(self):
        (self.project.python_dir / "my_app.py").write_text("raise AssertionError('validation executed project code')\n")
        loaded = self.load()
        self.assertEqual(loaded.project_setup, "my_app:register")
        self.assertEqual(loaded.extensions[0].name, "project_pulse")
        self.assertEqual(loaded.extensions[0].assets, ("assets/palette.json",))
        self.assertEqual(loaded.extensions[0].control_types, ("project_pulse.PulseDial",))
        self.config.pop("extensions")
        self.config.pop("project_setup")
        loaded = self.load()
        self.assertEqual(loaded.extensions, ())
        self.assertIsNone(loaded.project_setup)

    def test_setup_requires_non_keyword_existing_top_level_callable_path(self):
        for value in (True, "", "package.my_app:register", "my_app:register.attr", "missing:register",
                      "my-app:register", "my_app:lambda"):
            with self.subTest(value=value):
                self.config["project_setup"] = value
                with self.assertRaisesRegex(ValueError, "project_setup"):
                    self.load()

    def test_missing_pair_and_sdk_or_application_package_collisions_fail(self):
        config = self.config["extensions"][0]
        for name in ("flet", "json", "sdk_bridge", "my_app", "flutter", "project-pulse", "class"):
            with self.subTest(name=name):
                config["name"] = name
                with self.assertRaisesRegex(ValueError, "extension name"):
                    self.load()
        config["name"] = "project_pulse"
        for path in (self.extension.python_package / "__init__.py", self.extension.dart_package / "pubspec.yaml",
                     self.extension.dart_package / "lib/project_pulse.dart"):
            with self.subTest(path=path):
                data = path.read_bytes()
                path.unlink()
                with self.assertRaises(ValueError):
                    self.load()
                path.write_bytes(data)
        self.config["extensions"].append(dict(config))
        with self.assertRaisesRegex(ValueError, "duplicates"):
            self.load()

    def test_wire_types_are_namespaced_unique_and_not_both_controls_and_services(self):
        config = self.config["extensions"][0]
        for values in ([], ["Text"], ["project_pulse.PulseDial"] * 2, [True]):
            with self.subTest(values=values):
                config["control_types"] = values
                with self.assertRaisesRegex(ValueError, "type"):
                    self.load()
        config["control_types"] = ["project_pulse.PulseDial"]
        config["service_types"] = list(config["control_types"])
        with self.assertRaisesRegex(ValueError, "both"):
            self.load()

    def test_native_python_dependencies_and_installed_outputs_are_rejected(self):
        self.config["extensions"][0]["python_dependencies"] = ["numpy==2.3.4"]
        with self.assertRaisesRegex(ValueError, "native Python dependencies are unsupported"):
            self.load()
        self.config["extensions"][0]["python_dependencies"] = []
        for name in ("native.so", "installed.dist-info", "__pycache__", ".dart_tool"):
            with self.subTest(name=name):
                path = self.extension.python_package / name
                path.write_bytes(b"not a portable source")
                with self.assertRaisesRegex(ValueError, "generated or native output"):
                    self.load()
                path.unlink()

    def test_package_paths_cannot_escape_overlap_or_select_symlinks(self):
        config = self.config["extensions"][0]
        original = config["python_package"]
        for value in ("../outside", "app", "game", "assets", "missing"):
            with self.subTest(value=value):
                config["python_package"] = value
                with self.assertRaises(ValueError):
                    self.load()
        config["python_package"] = original
        asset = self.extension.dart_package / "assets/escape.json"
        asset.symlink_to(self.project.path)
        with self.assertRaisesRegex(ValueError, "links"):
            self.load()

    def test_yaml_duplicate_keys_sdk_overrides_and_unsupported_dependencies_fail(self):
        path = self.extension.dart_package / "pubspec.yaml"
        source = path.read_text()
        for suffix in ("\nname: other\n", "\ndependency_overrides:\n  flet: 2.0.0\n",
                       "\nworkspace: [other]\n", "\nresolution: workspace\n"):
            with self.subTest(suffix=suffix):
                path.write_text(source + suffix)
                with self.assertRaises(ValueError):
                    self.load()
        for dependency in ("    path: ../../outside", "    git: https://example.test/repository.git"):
            with self.subTest(dependency=dependency):
                path.write_text(source.replace("  flet: 1.0.3", "  unselected:\n" + dependency))
                with self.assertRaisesRegex(ValueError, "Dart dependenc"):
                    self.load()
        path.write_text(source.replace("assets/palette.json", "../missing.json"))
        with self.assertRaisesRegex(ValueError, "asset"):
            self.load()

    def test_flutter_staging_keeps_sources_immutable_registers_and_copies_tests_and_assets(self):
        work = self.root / "stage"
        module = work / "flutter"
        module.mkdir(parents=True)
        shutil.copytree(ROOT / "flutter/lib", module / "lib")
        shutil.copyfile(ROOT / "flutter/pubspec.yaml", module / "pubspec.yaml")
        before = build.tree_fingerprints(self.extension.dart_package)
        stage_project_flutter(self.project, module)
        import yaml
        pubspec = yaml.safe_load((module / "pubspec.yaml").read_text())
        self.assertEqual(pubspec["dependencies"]["project_pulse"], {"path": "../project-extensions/project_pulse"})
        self.assertEqual(pubspec["dependency_overrides"]["flet"], pubspec["dependencies"]["flet"])
        self.assertIn("project_pulse.Extension()", (module / "lib/project_extensions.dart").read_text().replace("project_0", "project_pulse"))
        self.assertTrue((module / "test/project_extensions/project_pulse/pulse_test.dart").is_file())
        self.assertTrue((work / "project-extensions/project_pulse/assets/palette.json").is_file())
        self.assertEqual(before, build.tree_fingerprints(self.extension.dart_package))
        self.assertEqual(len([name for name in pubspec["dependencies"] if name.startswith("flet_")]), 19)

    def test_directory_assets_include_resolution_variants(self):
        import yaml
        package = self.extension.dart_package
        variant = package / "assets/2x/palette.json"
        variant.parent.mkdir()
        variant.write_text('{"accent":"#ff5500"}')
        pubspec_path = package / "pubspec.yaml"
        pubspec = yaml.safe_load(pubspec_path.read_text())
        pubspec["flutter"]["assets"] = ["assets/"]
        pubspec_path.write_text(yaml.safe_dump(pubspec))
        extension = self.load().extensions[0]
        self.assertEqual(extension.assets, ("assets/2x/palette.json", "assets/palette.json"))
        self.assertIn("assets/flutter_assets/packages/project_pulse/assets/2x/palette.json",
                      extension_inventory(extension)["assets"])

    def test_asset_variants_require_flutter_ratio_directory_names(self):
        package = self.extension.dart_package
        for name in ("1.5x", "2x", "notx", "\uff12x", "\u0662x"):
            variant = package / "assets" / name / "palette.json"
            variant.parent.mkdir()
            variant.write_text('{"accent":"#ff5500"}')
        extension = self.load().extensions[0]
        self.assertEqual(extension.assets,
                         ("assets/1.5x/palette.json", "assets/2x/palette.json", "assets/palette.json"))

    def test_runtime_and_sealed_inventory_include_setup_python_asset_and_original_license(self):
        target = self.root / "private"
        build.stage_runtime(target, "app", self.project)
        values = {}
        exec((target / "project_config.py").read_text(), values)
        self.assertEqual(values["PROJECT_SETUP"], "my_app:register")
        self.assertTrue((target / "project_pulse/__init__.py").is_file())
        inventory = build.project_input_inventory(self.project)
        self.assertIn("project_pulse/__init__.py", inventory["python_files"])
        receipt = inventory["extensions"][0]
        self.assertEqual(receipt, extension_inventory(self.extension))
        self.assertEqual(receipt["python_files"]["project_pulse/__init__.py"], inventory["python_files"]["project_pulse/__init__.py"])
        self.assertIn("assets/flutter_assets/packages/project_pulse/assets/palette.json", receipt["assets"])
        self.assertEqual(receipt["license"]["path"], "third-party-notices/project-extension-project_pulse-LICENSE.txt")
        before = inventory["input_sha256"]
        (self.extension.dart_package / "assets/palette.json").write_text('{"accent":"#ff5500"}')
        self.assertNotEqual(before, build.project_input_inventory(self.project)["input_sha256"])

    def test_local_dependency_must_be_another_selected_pair_and_is_rebased(self):
        sibling = self.project.path.parent / "components/other"
        python = sibling / "python"
        dart = sibling / "flutter"
        shutil.copytree(self.extension.python_package, python)
        shutil.copytree(self.extension.dart_package, dart)
        pubspec = dart / "pubspec.yaml"
        pubspec.write_text(pubspec.read_text().replace("name: project_pulse", "name: project_other"))
        second = dict(self.config["extensions"][0], name="project_other",
                      python_package="components/other/python", dart_package="components/other/flutter",
                      control_types=["project_other.PulseDial"])
        self.config["extensions"].append(second)
        first_pubspec = self.extension.dart_package / "pubspec.yaml"
        relative = os.path.relpath(dart, self.extension.dart_package)
        first_pubspec.write_text(first_pubspec.read_text().replace("  flet: 1.0.3", "  flet: 1.0.3\n  project_other:\n    path: " + relative))
        loaded = self.load()
        module = self.root / "staging/flutter"
        (module / "lib").mkdir(parents=True)
        shutil.copyfile(ROOT / "flutter/pubspec.yaml", module / "pubspec.yaml")
        stage_project_flutter(loaded, module)
        import yaml
        staged = yaml.safe_load((module.parent / "project-extensions/project_pulse/pubspec.yaml").read_text())
        self.assertEqual(staged["dependencies"]["project_other"], {"path": "../project_other"})

    def test_new_staging_helper_requires_a_fresh_apk_in_source_guard(self):
        self.assertTrue(apk_inputs_changed({"status": "ahead", "files": [{"filename": "project_extensions.py"}]}))


class ProjectExtensionCacheTests(unittest.TestCase):
    def test_two_fresh_flutter_modules_use_one_native_download_and_keep_warm_rive_tests_running(self):
        fixture = cache_fixtures.FlutterCacheTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.stage()
        source = fixture.root / "rive_native/linux"
        before = build.tree_fingerprints(source)
        module = fixture.work / "flutter"
        obsolete = module / "build/rive_native/native/build/linux/bin/obsolete.so"
        obsolete.write_bytes(b"old build output")
        fixture.stage()
        self.assertFalse(obsolete.exists())
        self.assertEqual(fixture.native_downloads, 1)
        self.assertEqual(len(fixture.aar_builds()), 1)
        self.assertEqual(fixture.calls.count(("test", "--no-pub")), 2)
        self.assertFalse(any("--clean" in call for call in fixture.calls))
        self.assertEqual(before, build.tree_fingerprints(source))
        self.assertEqual((module / "build/rive_native/native/build/linux/bin/lib/debug_shared/librive_native.so").read_bytes(),
                         (source / "bin/lib/debug_shared/librive_native.so").read_bytes())

    def test_warm_marker_with_missing_native_file_recovers_only_the_missing_libraries(self):
        fixture = cache_fixtures.FlutterCacheTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.stage()
        (fixture.root / "rive_native/linux/bin/lib/debug_shared/librive_native.so").unlink()
        fixture.stage()
        self.assertEqual(fixture.native_downloads, 2)
        self.assertEqual(sum("--clean" in call for call in fixture.calls), 1)
        self.assertEqual(len(fixture.aar_builds()), 1)

    def test_native_library_staging_resolves_relative_uri_and_fails_when_recovery_is_incomplete(self):
        with tempfile.TemporaryDirectory(prefix="rive test ") as folder:
            root = Path(folder)
            native = root / "native package"
            library = native / "linux/bin/lib/debug_shared/librive_native.so"
            library.parent.mkdir(parents=True)
            library.write_bytes(b"native test library")
            module = root / "module"
            config = module / ".dart_tool/package_config.json"
            config.parent.mkdir(parents=True)
            config.write_text(json.dumps({"packages": [{"name": "rive_native", "rootUri": "../../native%20package/"}]}))
            with patch.object(build, "run") as setup:
                build.prepare_rive_linux_tests(Path("dart"), module)
            self.assertEqual(setup.call_count, 1)
            self.assertEqual((module / "build/rive_native/native/build/linux/bin/lib/debug_shared/librive_native.so").read_bytes(),
                             library.read_bytes())
            library.write_bytes(b"")
            with patch.object(build, "run") as setup, self.assertRaisesRegex(RuntimeError, "missing after setup"):
                build.prepare_rive_linux_tests(Path("dart"), module)
            self.assertEqual(setup.call_count, 2)
            self.assertIn("--clean", setup.call_args.args)

    def test_project_package_assets_dependencies_and_removal_invalidate_aar_reuse(self):
        fixture = cache_fixtures.FlutterCacheTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        project = example.materialize(fixture.root / "project")

        def stage(selected=project):
            with contextlib.redirect_stdout(io.StringIO()):
                return build.stage_flutter(fixture.inputs, fixture.work, project=selected)

        stage()
        stage()
        self.assertEqual(len(fixture.aar_builds()), 1)
        extension = project.extensions[0]
        for path in (extension.dart_package / "lib/project_pulse.dart",
                     extension.dart_package / "assets/palette.json",
                     extension.dart_package / "pubspec.yaml"):
            with self.subTest(input=path.name):
                path.write_text(path.read_text() + "\n")
                stage()
        self.assertEqual(len(fixture.aar_builds()), 4)
        config = json.loads(project.path.read_text())
        config["extensions"] = []
        project.path.write_text(json.dumps(config))
        stage(load_project(project.path))
        self.assertEqual(len(fixture.aar_builds()), 5)
        self.assertFalse((fixture.work / "project-extensions").exists())
        self.assertFalse((fixture.work / "flutter/test/project_extensions").exists())
        self.assertNotIn("project_pulse", (fixture.work / "flutter/pubspec.yaml").read_text())
        self.assertNotIn("project_pulse", (fixture.work / "flutter/lib/project_extensions.dart").read_text())
        stage(load_project(project.path))
        self.assertEqual(len(fixture.aar_builds()), 5)


if __name__ == "__main__":
    unittest.main()
