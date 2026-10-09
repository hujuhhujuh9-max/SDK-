"""Exercise project packaging and release paths without preparing SDKs or APKs."""

import ast
import contextlib
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import build_android as build
import test_flutter_cache as cache_fixtures
import test_startup_template as packaging_fixtures


class ReleaseCacheTests(unittest.TestCase):
    # Reuse the existing isolated source/tool fixtures without inheriting their tests.
    setUp = cache_fixtures.FlutterCacheTests.setUp
    write = cache_fixtures.FlutterCacheTests.write
    aar_builds = cache_fixtures.FlutterCacheTests.aar_builds

    def run_flutter(self, *command, cwd=None):
        args = tuple(str(part) for part in command[1:])
        if args[:2] != ("build", "aar"):
            return cache_fixtures.FlutterCacheTests.run_flutter(self, *command, cwd=cwd)
        self.calls.append(args)
        if self.fail == "build":
            raise subprocess.CalledProcessError(1, command)
        mode = "release" if "--no-debug" in args else "debug"
        repo = cwd / "build/host/outputs/repo"
        for suffix in (".aar", ".pom"):
            self.write(repo / (build.flutter_artifact(mode) + suffix), "Flutter " + mode + suffix)
            self.write(repo / ("plugins/audio/audio_" + mode + "/1.0/audio_" + mode + "-1.0" + suffix),
                       "retained audio " + mode + suffix)

    def stage(self, mode="debug", force=False):
        with contextlib.redirect_stdout(io.StringIO()):
            return build.stage_flutter(self.inputs, self.work, force_build=force, build_type=mode)

    def test_modes_build_separately_then_reuse_only_their_verified_repository(self):
        debug = self.stage()
        debug_receipt = (debug.parent / "manifest.json").read_bytes()
        release = self.stage("release")
        self.assertEqual(debug, self.inputs.cache / "flutter-aar/repo")
        self.assertEqual(release, self.inputs.cache / "flutter-aar-release/repo")
        self.assertNotEqual(json.loads(debug_receipt)["fingerprint"],
                            json.loads((release.parent / "manifest.json").read_text())["fingerprint"])
        self.assertEqual(self.stage(), debug)
        self.assertEqual(self.stage("release"), release)
        self.assertEqual(self.aar_builds(), [
            ("build", "aar", "--no-pub", "--no-profile", "--no-release"),
            ("build", "aar", "--no-pub", "--no-profile", "--no-debug"),
        ])
        self.assertEqual((debug.parent / "manifest.json").read_bytes(), debug_receipt)
        for cache, wrong_mode in ((debug.parent, "release"), (release.parent, "debug")):
            receipt = json.loads((cache / "manifest.json").read_text())
            self.assertFalse(build.reusable_flutter_repo(cache, receipt["fingerprint"], wrong_mode))
        for command in (("pub", "get"), ("analyze", "--no-pub", "lib", "test"), ("test", "--no-pub")):
            self.assertEqual(self.calls.count(command), 4)

    def test_failed_release_rebuild_does_not_invalidate_verified_debug_output(self):
        debug = self.stage()
        receipt = (debug.parent / "manifest.json").read_bytes()
        self.stage("release")
        self.fail = "build"
        with self.assertRaises(subprocess.CalledProcessError):
            self.stage("release", force=True)
        self.assertFalse((self.inputs.cache / "flutter-aar-release/manifest.json").exists())
        self.assertEqual((debug.parent / "manifest.json").read_bytes(), receipt)
        self.assertTrue(build.reusable_flutter_repo(debug.parent, json.loads(receipt)["fingerprint"]))
        self.fail = None
        self.stage()
        self.assertEqual(len(self.aar_builds()), 3)


class ProjectPackagingTests(unittest.TestCase):
    write = staticmethod(packaging_fixtures.StartupTemplateTests.write)

    def setUp(self):
        packaging_fixtures.StartupTemplateTests.setUp(self)
        self.project = SimpleNamespace(
            path=self.root / "external/renfletpy.json", application_id="org.example.stories",
            display_name='Écho & "Stories"', version_code=12, version_name="2.3.0+owner",
            startup_template="app", app_home="my_app:app_home_view",
            game_dir=self.root / "external/game", python_dir=self.root / "external/app",
            assets_dir=self.root / "external/assets", icon=self.root / "external/icon.png",
        )
        self.write(self.project.game_dir / "script.rpy", "label start:\n    return\n")
        self.write(self.project.game_dir / "chapter/dialog.rpy", "label project_dialog:\n    return\n")
        self.write(self.project.python_dir / "my_app.py", "def app_home_view(*args):\n    return None\n")
        self.write(self.project.python_dir / "views/__init__.py", "CUSTOM = True\n")
        self.write(self.project.python_dir / "views/home.py", "TITLE = 'Project home'\n")
        self.write(self.project.assets_dir / "images/custom.svg", "project asset")
        self.write(self.project.assets_dir / "runner.wav", "owner audio")
        self.write(self.project.assets_dir / "runner.mp4", "owner video")
        self.project.icon.write_bytes(b"project PNG fixture")
        self.write(self.source / "android/app/src/main/res/drawable/runner_icon.xml", "default icon")

    def run_command(self, *command, cwd=None):
        packaging_fixtures.StartupTemplateTests.run_command(self, *command, cwd=cwd)
        if str(command[0]).endswith("renpy.sh"):
            for source in (Path(command[1]) / "game").rglob("*.rpy"):
                source.with_suffix(".rpyc").write_bytes(b"compiled native fixture")

    def stage(self):
        return build.stage_android(self.inputs, self.work, self.sdks["flet"], self.root / "maven",
                                   "app", project=self.project, build_type="release")

    def test_supplied_inputs_identity_and_configuration_are_retained_in_packaged_paths(self):
        before = build.tree_fingerprints(self.source)
        android = self.stage()
        assets = android / "app/src/main/assets"
        inventory = json.loads((assets / "runner-capabilities.json").read_text())
        self.assertEqual(inventory["build_type"], "release")
        metadata = inventory["project"]
        expected_digest = metadata.pop("input_sha256")
        self.assertEqual(hashlib.sha256(json.dumps(metadata, sort_keys=True, separators=(",", ":"),
                                                  ensure_ascii=False).encode("utf-8")).hexdigest(), expected_digest)
        self.assertEqual(metadata["application_id"], self.project.application_id)
        with tarfile.open(assets / "private.mp3", "r:gz") as private:
            config = private.extractfile("project_config.py").read()
            self.assertEqual(config, self.compiled[-1][1])
            values = {node.targets[0].id: ast.literal_eval(node.value) for node in ast.parse(config).body
                      if isinstance(node, ast.Assign)}
            self.assertEqual(values, {"STARTUP_TEMPLATE": "app", "APP_HOME": self.project.app_home})
            for field in ("python_files", "asset_files"):
                for name, digest in metadata[field].items():
                    self.assertEqual(hashlib.sha256(private.extractfile(name).read()).hexdigest(), digest, name)
            self.assertEqual(private.extractfile("flet-assets/runner.wav").read(), b"owner audio")
            self.assertEqual(private.extractfile("flet-assets/runner.mp4").read(), b"owner video")
            self.assertEqual(private.extractfile("example.py").read(), b"VALUE = 1\n")
        for name, digest in metadata["game_files"].items():
            self.assertEqual(build.file_sha256(android / "app/src/main" / name), digest, name)
        self.assertTrue((assets / "x-game/x-chapter/x-dialog.rpyc").is_file())
        native_config = self.compiled[-1][0] / "game" / build.PROJECT_NATIVE_CONFIG
        self.assertIn("config.save_directory = 'org.example.stories'", native_config.read_text())
        self.assertIn(repr(self.project.display_name), native_config.read_text())
        self.assertEqual(build.tree_fingerprints(self.source), before)
        self.assertFalse((self.project.game_dir / build.PROJECT_NATIVE_CONFIG).exists())
        properties = (android / "gradle.properties").read_text()
        for declaration in ("runnerApplicationId=org.example.stories", "runnerVersionCode=12",
                            "runnerVersionName=2.3.0+owner", "runnerLabel=@string/renfletpy_project_name",
                            "runnerScheme=org-example-stories"):
            self.assertIn(declaration, properties)
        label = ET.parse(android / "app/src/main/res/values/project.xml").getroot().find("string").text
        self.assertEqual(label, '"Écho & \\"Stories\\""')
        drawable = android / "app/src/main/res/drawable"
        self.assertEqual((drawable / "runner_icon.png").read_bytes(), self.project.icon.read_bytes())
        self.assertFalse((drawable / "runner_icon.xml").exists())
        self.assertEqual(metadata["icon_sha256"], build.file_sha256(self.project.icon))

    def test_deleted_inputs_and_previous_project_identity_cannot_survive_rebuild(self):
        self.stage()
        (self.project.game_dir / "chapter/dialog.rpy").unlink()
        (self.project.python_dir / "views/home.py").unlink()
        (self.project.assets_dir / "images/custom.svg").unlink()
        self.project.application_id = "org.example.second"
        self.project.icon = None
        android = self.stage()
        assets = android / "app/src/main/assets"
        self.assertFalse((assets / "x-game/x-chapter/x-dialog.rpy").exists())
        self.assertFalse((assets / "x-game/x-chapter/x-dialog.rpyc").exists())
        self.assertFalse((self.compiled[-1][0] / "views/home.py").exists())
        with tarfile.open(assets / "private.mp3", "r:gz") as private:
            self.assertNotIn("views/home.py", private.getnames())
            self.assertNotIn("flet-assets/images/custom.svg", private.getnames())
            self.assertNotIn("flet-assets/" + build.PROJECT_ICON_ASSET, private.getnames())
        metadata = json.loads((assets / "runner-capabilities.json").read_text())["project"]
        self.assertEqual(metadata["application_id"], "org.example.second")
        self.assertIsNone(metadata["icon_sha256"])
        self.assertNotIn("org.example.stories", (android / "gradle.properties").read_text())
        self.assertTrue((android / "app/src/main/res/drawable/runner_icon.xml").is_file())
        self.assertFalse((android / "app/src/main/res/drawable/runner_icon.png").exists())

    def test_missing_media_is_generated_without_replacing_remaining_supplied_asset(self):
        (self.project.assets_dir / "runner.mp4").unlink()
        private = build.make_private(self.inputs, self.work, self.sdks["flet"], "app", self.project)
        self.assertEqual((private / "flet-assets/runner.wav").read_bytes(), b"owner audio")
        self.assertEqual((private / "flet-assets/runner.mp4").read_bytes(), b"media fixture")


class ReleaseCLITests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.android = self.root / "cache/integration/android"
        self.android.mkdir(parents=True)
        self.inputs = SimpleNamespace(cache=self.root / "cache", components={}, setup=lambda name: None)
        self.addCleanup(patch.stopall)
        patch.dict(os.environ, {"ANDROID_HOME": str(self.root / "android-sdk")}).start()
        for name in build.SIGNING_ENVIRONMENT:
            os.environ.pop(name, None)
        patch.object(build.sys, "version_info", (3, 12, 0)).start()

    def run_main(self, arguments, project=None):
        calls = []

        def fake_run(*command, cwd=None):
            calls.append(tuple(str(part) for part in command))
            if str(command[0]).endswith("gradlew"):
                signed = all(os.environ.get(name) for name in build.SIGNING_ENVIRONMENT)
                name = "app-release.apk" if signed else "app-release-unsigned.apk"
                apk = self.android / "app/build/outputs/apk/release" / name
                apk.parent.mkdir(parents=True, exist_ok=True)
                apk.write_bytes(b"verified release fixture")

        stream = io.StringIO()
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(sys, "argv", ["build_android.py", *arguments]))
            stack.enter_context(patch.object(build, "BuildInputs", return_value=self.inputs))
            stack.enter_context(patch.object(build, "stage_flet", return_value=self.root / "flet"))
            flutter = stack.enter_context(patch.object(build, "stage_flutter", return_value=self.root / "maven"))
            android = stack.enter_context(patch.object(build, "stage_android", return_value=self.android))
            stack.enter_context(patch.object(build, "run", side_effect=fake_run))
            stack.enter_context(patch.object(build, "check_merged_android_capabilities"))
            inspected = stack.enter_context(patch.object(build, "inspect_apk", side_effect=lambda path, abis, **kwargs:
                                                        {"file": path.name, "abis": list(abis),
                                                         "source_sha": "a" * 40, **kwargs}))
            stack.enter_context(patch.object(build, "compare_apk_payloads", return_value=100))
            if project is not None:
                stack.enter_context(patch.dict(sys.modules, {"project": SimpleNamespace(load_project=lambda path: project)}))
                stack.enter_context(patch.object(build, "project_input_inventory", return_value={
                    "application_id": project.application_id, "input_sha256": "b" * 64}))
            with contextlib.redirect_stdout(stream):
                build.main()
        return calls, flutter, android, inspected, stream.getvalue()

    def test_unsigned_release_selects_release_task_artifacts_and_receipt(self):
        calls, flutter, _, inspected, output = self.run_main(["--build-type", "release"])
        self.assertEqual(flutter.call_args.kwargs["build_type"], "release")
        gradle = [command for command in calls if command[0].endswith("gradlew")]
        self.assertEqual(len(gradle), 2)
        self.assertTrue(all(command[-1] == ":app:assembleRelease" for command in gradle))
        self.assertIn("-PrunnerAbi=x86_64", gradle[1])
        self.assertFalse(any(command[0].endswith("apksigner") for command in calls))
        self.assertEqual([call.kwargs["build_type"] for call in inspected.call_args_list], ["release", "release"])
        result = json.loads((self.inputs.cache / "outputs/apk-builds-release.json").read_text())
        self.assertEqual((result["build_type"], result["signing"], result["startup_template"]),
                         ("release", "unsigned", "story"))
        self.assertEqual([apk["file"] for apk in result["apks"]],
                         ["runner-release.apk", "runner-release-x86_64.apk"])
        self.assertIn("Release APKs are unsigned", output)

    def test_signed_project_release_uses_owner_environment_and_verifies_both_signatures(self):
        keystore = self.root / "owner.keystore"
        keystore.write_bytes(b"owner keystore fixture")
        signing = dict(zip(build.SIGNING_ENVIRONMENT, (str(keystore), "owner-alias", "store-secret", "key-secret")))
        project = SimpleNamespace(application_id="org.renfletpy.example", startup_template="app")
        with patch.dict(os.environ, signing):
            calls, _, android, inspected, output = self.run_main(
                ["--project", str(self.root / "external/renfletpy.json"), "--build-type", "release"], project)
        self.assertIs(android.call_args.kwargs["project"], project)
        self.assertEqual(android.call_args.args[-1], "app")
        verified = [command for command in calls if command[0].endswith("apksigner")]
        self.assertEqual(len(verified), 2)
        self.assertTrue(all(command[1:3] == ("verify", "--verbose") for command in verified))
        for secret in signing.values():
            self.assertNotIn(secret, repr(calls) + output)
        self.assertTrue(all(call.kwargs["project"]["application_id"] == project.application_id
                            for call in inspected.call_args_list))
        result = json.loads((self.inputs.cache / "outputs/apk-builds-org-renfletpy-example-release.json").read_text())
        self.assertEqual(result["signing"], "signed")
        self.assertEqual([apk["file"] for apk in result["apks"]],
                         ["runner-org-renfletpy-example-release.apk", "runner-org-renfletpy-example-release-x86_64.apk"])
        self.assertNotIn("Release APKs are unsigned", output)

    def test_partial_signing_or_project_startup_conflict_fails_before_preparation(self):
        stderr = io.StringIO()
        with patch.object(sys, "argv", ["build_android.py", "--build-type", "release"]), \
                patch.dict(os.environ, {"RENFLETPY_STORE_PASSWORD": "private-value"}), \
                patch.object(build, "BuildInputs") as prepare, contextlib.redirect_stderr(stderr):
            with self.assertRaises(SystemExit) as error:
                build.main()
            self.assertEqual(error.exception.code, 2)
            self.assertIn("Invalid release signing", stderr.getvalue())
            self.assertIn("requires all four", stderr.getvalue())
            self.assertNotIn("private-value", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            prepare.assert_not_called()
        project = SimpleNamespace(startup_template="app")
        with patch.object(sys, "argv", ["build_android.py", "--project", "project.json", "--startup-template", "story"]), \
                patch.dict(sys.modules, {"project": SimpleNamespace(load_project=lambda path: project)}), \
                patch.object(build, "BuildInputs") as prepare, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                build.main()
            self.assertEqual(error.exception.code, 2)
            prepare.assert_not_called()

    def test_project_read_and_validation_errors_are_concise_before_preparation(self):
        for failure in (FileNotFoundError("project configuration is missing"),
                        ValueError("application_id must have at least two segments")):
            stderr = io.StringIO()
            with self.subTest(error=type(failure).__name__), \
                    patch.object(sys, "argv", ["build_android.py", "--project", "project.json"]), \
                    patch.dict(sys.modules, {"project": SimpleNamespace(
                        load_project=Mock(side_effect=failure))}), \
                    patch.object(build, "BuildInputs") as prepare, contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as error:
                    build.main()
                self.assertEqual(error.exception.code, 2)
                self.assertIn("Invalid project: " + str(failure), stderr.getvalue())
                self.assertNotIn("Traceback", stderr.getvalue())
                prepare.assert_not_called()

    def test_missing_keystore_is_rejected_without_disclosing_environment_values(self):
        signing = dict(zip(build.SIGNING_ENVIRONMENT,
                           (str(self.root / "missing.key"), "owner-alias", "store-secret", "key-secret")))
        with self.assertRaisesRegex(ValueError, "existing keystore file") as error:
            build.release_signing(signing)
        for value in signing.values():
            self.assertNotIn(value, str(error.exception))


class MergedPermissionTests(unittest.TestCase):
    def test_exact_disabled_permission_names_are_rejected_but_similar_names_are_allowed(self):
        for name in build.DISABLED_ANDROID_PERMISSIONS:
            with self.subTest(permission=name), patch.object(build.subprocess, "check_output",
                    return_value="uses-permission: name='" + name + "'\n"):
                with self.assertRaisesRegex(RuntimeError, "disabled Android permissions"):
                    build.check_merged_android_capabilities(Path("runner.apk"), Path("aapt"))
        with patch.object(build.subprocess, "check_output", side_effect=[
                "uses-permission: name='android.permission.CAMERA_EXTRA'\n", "manifest fixture"]):
            build.check_merged_android_capabilities(Path("runner.apk"), Path("aapt"))

    def test_disabled_location_service_is_rejected_from_binary_manifest_dump(self):
        with patch.object(build.subprocess, "check_output", side_effect=[
                "uses-permission: name='android.permission.INTERNET'\n",
                'A: android:name(0x01010003)="com.baseflow.geolocator.GeolocatorLocationService" (Raw: "same")\n']):
            with self.assertRaisesRegex(RuntimeError, "disabled Android location service"):
                build.check_merged_android_capabilities(Path("runner.apk"), Path("aapt"))


if __name__ == "__main__":
    unittest.main()
