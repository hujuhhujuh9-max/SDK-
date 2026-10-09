"""Reject unbound or altered supplied inputs without preparing an Android SDK."""

import copy
import hashlib
import io
import json
import tarfile
import tempfile
import unittest
import warnings
import zipfile
from pathlib import Path

from scripts.check_apk import inspect_apk
from scripts.check_apk_source import apk_inputs_changed


def checksum(data):
    return hashlib.sha256(data).hexdigest()


class ProjectArtifactTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.private = {
            "renpy/__init__.py": b"retained SDK package",
            "project_config.py": b'STARTUP_TEMPLATE = "app"\nAPP_HOME = "my_app:app_home_view"\n',
            "my_app.py": b"def app_home_view(*args): pass\n",
            "flet-assets/runner.svg": b"supplied asset",
        }
        self.files = {"assets/x-game/x-story.rpy": b'label start:\n    "Supplied native story"\n'}
        self.project = {
            "application_id": "org.renfletpy.example", "display_name": "RenFletPy Example",
            "version_code": 7, "version_name": "1.2", "startup_template": "app",
            "app_home": "my_app:app_home_view", "input_sha256": "",
            "game_files": {name: checksum(data) for name, data in self.files.items()},
            "python_files": {"my_app.py": checksum(self.private["my_app.py"])},
            "asset_files": {"flet-assets/runner.svg": checksum(self.private["flet-assets/runner.svg"])},
            "icon_sha256": None,
        }

    def apk(self, *, project=None, private=None, files=None, build_type="release",
            seal=True, duplicate_private=(), duplicate_zip=(), links=()):
        project = copy.deepcopy(self.project if project is None else project)
        private = dict(self.private if private is None else private)
        files = dict(self.files if files is None else files)
        if seal:
            data = json.dumps({key: value for key, value in project.items() if key != "input_sha256"},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
            project["input_sha256"] = checksum(data)
        bundle = io.BytesIO()
        with tarfile.open(fileobj=bundle, mode="w:gz") as archive:
            for name, data in [*private.items(), *duplicate_private]:
                member = tarfile.TarInfo(name)
                if name in links:
                    member.type = tarfile.SYMTYPE
                    member.linkname = "my_app.py"
                    archive.addfile(member)
                else:
                    member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
        common = "assets/x-renpy/x-common/x-screen.rpy"
        inventory = {
            "startup_template": "app", "build_type": build_type, "source_sha": "a" * 40,
            "project_config_sha256": checksum(private["project_config.py"]),
            "extensions": json.loads((Path(__file__).resolve().parents[1] /
                                      "runtime/flet_extensions.json").read_text()),
            "python_files": {"renpy/__init__.py": checksum(self.private["renpy/__init__.py"])},
            "android_assets": {common: checksum(b"retained common asset")}, "project": project,
        }
        files.update({"assets/private.mp3": bundle.getvalue(), common: b"retained common asset",
                      "assets/runner-capabilities.json": json.dumps(inventory).encode(),
                      "lib/x86_64/libflutter.so": b"Flutter", "lib/x86_64/librenpython.so": b"RenPy",
                      "lib/x86_64/libapp.so": b"release AOT"})
        path = self.root / "project.apk"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with zipfile.ZipFile(path, "w") as apk:
                for name, data in [*files.items(), *duplicate_zip]:
                    apk.writestr(name, data)
        return path

    def inspect(self, **options):
        return inspect_apk(self.apk(**options), ("x86_64",), "app", build_type="release",
                           project={"application_id": "org.renfletpy.example"})

    def test_release_checks_retained_project_game_module_assets_and_canonical_identity(self):
        report = self.inspect()
        self.assertEqual(report["build_type"], "release")
        self.assertEqual(report["project"]["version_code"], 7)
        self.assertEqual(report["project"]["game_files"], self.project["game_files"])
        self.assertEqual(report["python_files_verified"], 1)
        self.assertEqual(report["extensions"], json.loads((Path(__file__).resolve().parents[1] /
                                                         "runtime/flet_extensions.json").read_text()))
        with self.assertRaisesRegex(RuntimeError, "does not match expectation"):
            inspect_apk(self.apk(), ("x86_64",), "app", project={"application_id": "org.other.app"})
        with self.assertRaisesRegex(RuntimeError, "does not match expectation"):
            inspect_apk(self.apk(), ("x86_64",), "app", project={"input_sha256": "f" * 64})

    def test_missing_changed_or_nonregular_supplied_payload_is_rejected(self):
        for name in ("my_app.py", "flet-assets/runner.svg"):
            for missing in (False, True):
                with self.subTest(name=name, missing=missing):
                    private = dict(self.private)
                    if missing:
                        del private[name]
                    else:
                        private[name] = b"different input"
                    with self.assertRaises((AssertionError, RuntimeError)):
                        self.inspect(private=private)
        files = {"assets/x-game/x-story.rpy": b"different story"}
        with self.assertRaisesRegex(AssertionError, "Changed Android asset"):
            self.inspect(files=files)
        with self.assertRaisesRegex(RuntimeError, "nonregular"):
            self.inspect(links=("my_app.py",))

    def test_literal_factory_must_match_the_retained_module_and_configuration(self):
        for source in (b'STARTUP_TEMPLATE="app"\nAPP_HOME=load_factory()\n',
                       b'STARTUP_TEMPLATE="app"\nAPP_HOME="other:home"\n',
                       b'STARTUP_TEMPLATE="app"\nAPP_HOME="my_app:app_home_view"\nAPP_HOME=None\n',
                       b'STARTUP_TEMPLATE="app"\n'):
            with self.subTest(source=source):
                with self.assertRaisesRegex(RuntimeError, "packaged startup template"):
                    self.inspect(private=self.private | {"project_config.py": source})
        project = copy.deepcopy(self.project)
        project["python_files"] = {}
        with self.assertRaisesRegex(RuntimeError, "App home"):
            self.inspect(project=project)

    def test_metadata_hash_and_complete_identity_schema_cannot_be_skipped(self):
        with self.assertRaisesRegex(RuntimeError, "Changed supplied project input"):
            self.inspect(seal=False)
        for field, value in (("version_code", True), ("version_code", 0),
                             ("application_id", "bad/name"), ("startup_template", "story"),
                             ("app_home", "package.module:home"), ("extra", "untracked")):
            with self.subTest(field=field, value=value):
                with self.assertRaisesRegex(RuntimeError, "metadata"):
                    self.inspect(project=self.project | {field: value})

    def test_untrusted_inventory_paths_and_sdk_shadowing_are_rejected(self):
        for path in ("../my_app.py", "/my_app.py", "./my_app.py", ".", "a//b.py",
                     "sdk_bridge.py", "renpy/__init__.py", "lib/python3.12/a.py"):
            with self.subTest(path=path):
                project = copy.deepcopy(self.project)
                project["python_files"][path] = "b" * 64
                with self.assertRaisesRegex(RuntimeError, "project file"):
                    self.inspect(project=project)

    def test_icon_requires_retained_original_bytes_not_just_a_claimed_digest(self):
        icon = b"\x89PNG\r\n\x1a\noriginal supplied icon"
        name = "flet-assets/_renfletpy_project_icon.png"
        project = copy.deepcopy(self.project)
        project["icon_sha256"] = checksum(icon)
        with self.assertRaisesRegex(RuntimeError, "project icon"):
            self.inspect(project=project)
        project["asset_files"][name] = checksum(icon)
        self.inspect(project=project, private=self.private | {name: icon})
        with self.assertRaisesRegex(AssertionError, "Changed component file"):
            self.inspect(project=project, private=self.private | {name: b"changed icon"})

    def test_duplicate_entries_and_wrong_build_type_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError, "Duplicate"):
            self.inspect(duplicate_private=(("my_app.py", self.private["my_app.py"]),))
        with self.assertRaisesRegex(RuntimeError, "Duplicate APK"):
            self.inspect(duplicate_zip=(("lib/x86_64/libflutter.so", b"substituted"),))
        with self.assertRaisesRegex(RuntimeError, "build type"):
            self.inspect(build_type="debug")

    def test_relabelled_debug_flutter_and_empty_upstream_inventory_cannot_pass_release(self):
        for change in ("missing-aot", "debug-kernel", "empty-upstream"):
            with self.subTest(change=change):
                path = self.apk()
                with zipfile.ZipFile(path) as apk:
                    files = {name: apk.read(name) for name in apk.namelist()}
                if change == "missing-aot":
                    del files["lib/x86_64/libapp.so"]
                elif change == "debug-kernel":
                    files["assets/flutter_assets/kernel_blob.bin"] = b"debug Dart code"
                else:
                    inventory = json.loads(files["assets/runner-capabilities.json"])
                    inventory["python_files"] = {}
                    files["assets/runner-capabilities.json"] = json.dumps(inventory).encode()
                with zipfile.ZipFile(path, "w") as apk:
                    for name, data in files.items():
                        apk.writestr(name, data)
                with self.assertRaises((AssertionError, RuntimeError)):
                    inspect_apk(path, ("x86_64",), "app", build_type="release")

    def test_project_loader_and_template_changes_require_a_new_apk_including_renames(self):
        for name in ("project.py", "create_project.py", "templates/app/renfletpy.json", "templates/app/app/my_app.py"):
            with self.subTest(name=name):
                self.assertTrue(apk_inputs_changed({"status": "ahead", "files": [{"filename": name}]}))
                self.assertTrue(apk_inputs_changed({"status": "ahead", "files": [
                    {"filename": "docs/moved", "previous_filename": name}]}))
        self.assertFalse(apk_inputs_changed({"status": "ahead", "files": [
            {"filename": "scripts/check_project_device.py"}]}))
