"""Bind extension packages, asset bytes, notices and the setup hook to APK claims."""

import copy
import json
import unittest
import zipfile

from scripts.check_apk import inspect_apk
import test_project_artifacts as artifact_fixtures


class ProjectExtensionAPKTests(unittest.TestCase):
    def setUp(self):
        self.fixture = artifact_fixtures.ProjectArtifactTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.python = b"# project-owned paired Python package\n"
        self.asset = b'{"accent":"#25b8c5"}\n'
        self.license = b"Original project extension license\n"
        self.asset_path = "assets/flutter_assets/packages/project_pulse/assets/palette.json"
        checksum = artifact_fixtures.checksum
        self.extension = {
            "name": "project_pulse", "dart_entrypoint": "pulse.dart", "dart_extension": "Extension",
            "control_types": ["project_pulse.PulseDial"], "service_types": [],
            "python_files": {"project_pulse/__init__.py": checksum(self.python)},
            "dart_files": {"pubspec.yaml": checksum(b"name: project_pulse\n"),
                           "lib/pulse.dart": checksum(b"class Extension {}\n"),
                           "assets/palette.json": checksum(self.asset)},
            "assets": {self.asset_path: checksum(self.asset)},
            "license": {"path": "third-party-notices/project-extension-project_pulse-LICENSE.txt",
                        "sha256": checksum(self.license)},
        }
        self.project = copy.deepcopy(self.fixture.project)
        self.project.update(project_setup="my_app:register", extensions=[self.extension])
        self.project["python_files"].update(self.extension["python_files"])
        self.private = dict(self.fixture.private)
        self.private.update({"project_pulse/__init__.py": self.python,
                             self.extension["license"]["path"]: self.license})
        self.private["project_config.py"] += b'PROJECT_SETUP = "my_app:register"\n'

    def apk(self, *, project=None, private=None, asset=None):
        project = self.project if project is None else project
        original = self.fixture.apk(project=project, private=self.private if private is None else private)
        with zipfile.ZipFile(original) as archive:
            files = {name: archive.read(name) for name in archive.namelist()}
        inventory = json.loads(files["assets/runner-capabilities.json"])
        for extension in project.get("extensions", []):
            inventory["android_assets"].update(extension["assets"])
        files["assets/runner-capabilities.json"] = json.dumps(inventory).encode()
        files[self.asset_path] = self.asset if asset is None else asset
        output = self.fixture.root / "extension.apk"
        with zipfile.ZipFile(output, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        return output

    def inspect(self, **options):
        return inspect_apk(self.apk(**options), ("x86_64",), "app", build_type="release")

    def test_claims_require_paired_package_notice_asset_and_literal_setup(self):
        receipt = self.inspect()
        self.assertEqual(len(receipt["extensions"]), 19)
        self.assertEqual(receipt["project"]["extensions"], [self.extension])
        self.assertEqual(receipt["project"]["project_setup"], "my_app:register")

    def test_modified_missing_python_and_notice_and_asset_are_rejected(self):
        for name in ("project_pulse/__init__.py", self.extension["license"]["path"]):
            for removed in (False, True):
                with self.subTest(name=name, removed=removed):
                    private = dict(self.private)
                    if removed:
                        private.pop(name)
                    else:
                        private[name] = b"modified package bytes"
                    with self.assertRaises((AssertionError, RuntimeError)):
                        self.inspect(private=private)
        with self.assertRaisesRegex(AssertionError, "Changed Android asset"):
            self.inspect(asset=b"modified package asset")

    def test_invalid_or_duplicate_extension_claims_fail_even_when_metadata_is_resealed(self):
        cases = [
            {"name": "flet"}, {"control_types": ["Text"]}, {"service_types": ["project_pulse.PulseDial"]},
            {"python_files": {}}, {"dart_files": {}}, {"dart_entrypoint": "../pulse.dart"},
            {"assets": {self.asset_path: "a" * 64}},
            {"license": {"path": "third-party-notices/another-LICENSE.txt", "sha256": "a" * 64}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                project = copy.deepcopy(self.project)
                project["extensions"][0].update(changes)
                with self.assertRaises(RuntimeError):
                    self.inspect(project=project)
        project = copy.deepcopy(self.project)
        project["extensions"].append(copy.deepcopy(self.extension))
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            self.inspect(project=project)

    def test_setup_module_inventory_and_unique_literal_must_match(self):
        project = copy.deepcopy(self.project)
        project["project_setup"] = "missing:register"
        with self.assertRaisesRegex(RuntimeError, "Project setup"):
            self.inspect(project=project)
        for configuration in (self.private["project_config.py"].replace(b'"my_app:register"', b'"my_app:other"'),
                              self.private["project_config.py"] + b'PROJECT_SETUP = None\n',
                              self.private["project_config.py"].replace(b'"my_app:register"', b'load_setup()')):
            with self.subTest(configuration=configuration):
                with self.assertRaisesRegex(RuntimeError, "packaged startup template"):
                    self.inspect(private=self.private | {"project_config.py": configuration})


if __name__ == "__main__":
    unittest.main()
