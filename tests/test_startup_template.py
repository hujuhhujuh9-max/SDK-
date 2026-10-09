"""Verify optional startup selection reaches native compilation and APK packaging."""

import contextlib
import hashlib
import io
import json
import os
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import build_android as build


class StartupTemplateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.source = self.root / "source"
        self.work = self.root / "cache/integration"
        self.work.mkdir(parents=True)
        self.sdks = {name: self.root / name for name in ("renpy", "renpy-rapt", "flet", "flutter")}
        self.inputs = SimpleNamespace(
            cache=self.work.parent, components={"renpy-rapt": {"notices": []}},
            sdk_root=lambda name: self.sdks[name], setup=lambda name: None,
        )
        self.write(self.source / "runtime/project_config.py",
                   (build.ROOT / "runtime/project_config.py").read_text())
        self.write(self.source / "runtime/example.py", "VALUE = 1\n")
        self.write(self.source / "runtime/flet_extensions.json",
                   (build.ROOT / "runtime/flet_extensions.json").read_text())
        self.write(self.source / "runtime/requirements.txt", "")
        self.write(self.source / "game/script.rpy", "label start:\n    return\n")
        self.write(self.source / "assets/fixture.svg", "local asset")
        self.write(self.source / "LICENSE", "project notice")
        self.write(self.source / "android/app/src/main/AndroidManifest.xml",
                   (build.ROOT / "android/app/src/main/AndroidManifest.xml").read_text())
        self.write(self.source / "android/renpyandroid-dependencies.gradle", "host dependencies")
        rapt = self.sdks["renpy-rapt"]
        self.write(rapt / "templates/app-AndroidManifest.xml", "<manifest><application /></manifest>")
        self.write(rapt / "templates/Constants.java", "class Constants {}")
        self.write(rapt / "prototype/renpyandroid/build.gradle", "native host")
        self.write(rapt / "prototype/renpyandroid/src/main/java/org/renpy/android/Constants.java", "old constants")
        self.write(rapt / "prototype/gradle/wrapper/gradle-wrapper.properties", "Gradle wrapper")
        for name in ("gradlew", "gradlew.bat", "gradle.properties", "build.gradle"):
            self.write(rapt / "prototype" / name, "build fixture")
        renpy = self.sdks["renpy"]
        self.write(renpy / "renpy.py", "native startup")
        self.write(renpy / "renpy/__init__.py", "retained native package")
        self.write(renpy / "renpy/common/screen.rpy", "retained common asset")
        self.write(renpy / "lib/python3.12/example.py", "retained stdlib")
        self.write(renpy / "LICENSE.txt", "native notice")
        flet = self.sdks["flet"]
        self.write(flet / "sdk/python/packages/flet/src/flet/__init__.py", "retained Flet package")
        self.write(flet / "LICENSE", "Flet notice")
        self.write(self.sdks["flutter"] / "LICENSE", "Flutter notice")
        self.write(self.root / "android-sdk/platforms/android-36/android.jar", "platform fixture")
        self.compiled = []
        self.addCleanup(patch.stopall)
        patch.object(build, "ROOT", self.source).start()
        patch.object(build, "run", side_effect=self.run_command).start()
        patch.object(build, "copy_flet_extensions").start()
        patch.object(build, "extension_projects", return_value=[]).start()
        patch.object(build.subprocess, "check_output", return_value="a" * 40 + "\n").start()
        environment = SimpleNamespace(from_string=lambda text: SimpleNamespace(render=lambda **kwargs: text))
        patch.dict(sys.modules, {"jinja2": SimpleNamespace(Environment=lambda: environment)}).start()
        patch.dict(os.environ, {"ANDROID_HOME": str(self.root / "android-sdk")}).start()

    @staticmethod
    def write(path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)

    def run_command(self, *command, cwd=None):
        if str(command[0]).endswith("renpy.sh"):
            project = Path(command[1])
            self.compiled.append((project, (project / "project_config.py").read_bytes()))
        elif command[0] == "ffmpeg":
            Path(command[-1]).write_bytes(b"media fixture")

    def test_compile_and_private_bundle_receive_identical_selected_configuration(self):
        checked_in = (self.source / "runtime/project_config.py").read_bytes()
        for template in ("story", "app", "story"):
            with self.subTest(template=template):
                android = build.stage_android(self.inputs, self.work, self.sdks["flet"],
                                              self.root / "maven", template)
                assets = android / "app/src/main/assets"
                with tarfile.open(assets / "private.mp3", "r:gz") as private:
                    config = private.extractfile("project_config.py").read()
                    self.assertEqual(private.extractfile("example.py").read(), b"VALUE = 1\n")
                self.assertEqual(config, self.compiled[-1][1])
                self.assertIn(('STARTUP_TEMPLATE = "' + template + '"').encode(), config)
                expected_project = "renpy-project-app" if template == "app" else "renpy-project"
                self.assertEqual(self.compiled[-1][0].name, expected_project)
                inventory = json.loads((assets / "runner-capabilities.json").read_text())
                self.assertEqual(inventory["startup_template"], template)
                self.assertEqual(inventory["source_sha"], "a" * 40)
                self.assertEqual(inventory["project_config_sha256"], hashlib.sha256(config).hexdigest())
                self.assertEqual(len(inventory["extensions"]), 19)
        self.assertEqual((self.source / "runtime/project_config.py").read_bytes(), checked_in)
        self.assertEqual(self.compiled[-1][1], checked_in)

    def test_invalid_selection_does_not_overwrite_staged_runtime(self):
        target = self.root / "staged"
        build.stage_runtime(target, "story")
        before = (target / "project_config.py").read_bytes()
        with self.assertRaisesRegex(ValueError, "Unsupported startup template"):
            build.stage_runtime(target, "automatic")
        self.assertEqual((target / "project_config.py").read_bytes(), before)

    def test_cli_preserves_default_outputs_and_identifies_app_outputs(self):
        built = self.work / "android/app/build/outputs/apk/debug/app-debug.apk"
        self.write(built, "verified APK fixture")
        for arguments, mode, prefix, receipt in (
                ([], "story", "runner-debug", "apk-builds.json"),
                (["--startup-template", "app"], "app", "runner-app-debug", "apk-builds-app.json")):
            with self.subTest(mode=mode), contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(sys, "argv", ["build_android.py", *arguments]))
                stack.enter_context(patch.object(build, "BuildInputs", return_value=self.inputs))
                stack.enter_context(patch.object(build, "stage_flet", return_value=self.sdks["flet"]))
                stack.enter_context(patch.object(build, "stage_flutter", return_value=self.root / "maven"))
                staged = stack.enter_context(patch.object(build, "stage_android", return_value=self.work / "android"))
                stack.enter_context(patch.object(build, "compare_apk_payloads", return_value=100))
                inspected = stack.enter_context(patch.object(build, "inspect_apk", side_effect=lambda path, abis, startup_template:
                                                             {"file": path.name, "abis": list(abis),
                                                              "startup_template": startup_template, "source_sha": "a" * 40}))
                stack.enter_context(patch.object(build.subprocess, "check_output", return_value="permissions without camera"))
                with contextlib.redirect_stdout(io.StringIO()):
                    build.main()
                self.assertEqual(staged.call_args.args[-1], mode)
                self.assertEqual([call.kwargs["startup_template"] for call in inspected.call_args_list], [mode, mode])
                output = self.inputs.cache / "outputs"
                self.assertTrue((output / (prefix + ".apk")).is_file())
                self.assertTrue((output / (prefix + "-x86_64.apk")).is_file())
                report = json.loads((output / receipt).read_text())
                self.assertEqual(report["startup_template"], mode)
                self.assertEqual(report["source_sha"], "a" * 40)
                self.assertEqual(len(report["apks"]), 2)

    def test_cli_rejects_unknown_template_before_sdk_preparation(self):
        with patch.object(sys, "argv", ["build_android.py", "--startup-template", "automatic"]), \
                patch.object(build, "BuildInputs") as inputs, contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as error:
                build.main()
        self.assertEqual(error.exception.code, 2)
        inputs.assert_not_called()
